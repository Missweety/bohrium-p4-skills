#!/usr/bin/env python3
"""Bind an authored research synthesis to a frozen protocol and actual source paragraphs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def read_pages(path):
    if path.suffix.lower()=='.pdf':
        if not shutil.which('pdftotext'):raise ValueError('pdftotext unavailable')
        p=subprocess.run(['pdftotext','-layout',str(path),'-'],capture_output=True,timeout=60)
        if p.returncode:raise ValueError('PDF extraction failed')
        data=p.stdout.decode('utf-8','replace').split('\f')
        if data and not data[-1].strip():data.pop()
        return [(f'p.{i}',t) for i,t in enumerate(data,1)]
    if path.suffix.lower()=='.docx':
        with zipfile.ZipFile(path) as z:root=ET.fromstring(z.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        return [('document','\n\n'.join(''.join(e.itertext()) for e in root.findall('.//w:p',ns)))]
    return [('text',path.read_text(encoding='utf-8'))]

def prepare(a):
    if not a.input.is_dir():raise ValueError('material directory missing')
    protocol=json.loads(a.protocol.read_text())
    if not isinstance(protocol,dict) or not protocol.get('question') or not protocol.get('criteria'):
        raise ValueError('protocol needs research question and operational criteria')
    if not isinstance(protocol['criteria'],dict):
        raise ValueError('criteria must be an id-to-definition dictionary')
    snapshot={'input_root':str(a.input.resolve()),'protocol':protocol,'protocol_sha256':sha(a.protocol),
              'prepared_at':datetime.now(timezone.utc).isoformat(),
              'files':[],'paragraphs':[],'failures':[]}
    skip={a.protocol.resolve()}
    if a.records:skip.add(a.records.resolve())
    for path in sorted(a.input.rglob('*')):
        if not path.is_file():continue
        rel=str(path.relative_to(a.input))
        if path.is_symlink():
            snapshot['failures'].append({'source_id':rel,'error':'symlink skipped'});continue
        if path.resolve() in skip or path.name.lower() in {'case.json','task.md','resources.yaml','readme.md'}:continue
        if path.suffix.lower() not in {'.pdf','.docx','.md','.txt','.tex','.json','.csv','.tsv','.bib','.ris'}:
            snapshot['failures'].append({'source_id':rel,'error':'unsupported material; convert with provenance'})
            continue
        h=sha(path)
        snapshot['files'].append({'source_id':rel,'path':str(path.resolve()),'sha256':h})
        try:
            pages=read_pages(path)
            for page,text in pages:
                if not text.strip():
                    snapshot['failures'].append({'source_id':rel,'locator':page,'error':'empty_text_page'})
                for n,part in enumerate(re.split(r'\n\s*\n',text),1):
                    if part.strip():snapshot['paragraphs'].append({
                        'source_id':rel,'sha256':h,'locator':f'{page}/para.{n}','quote':part.strip()})
        except Exception as exc:snapshot['failures'].append({'source_id':rel,'error':str(exc)})
    records=json.loads(a.records.read_text()) if a.records else [
        {'id':f['source_id'],'source_id':f['source_id'],'record_basis':'one record per file; use supplied bibliography when present'}
        for f in snapshot['files']]
    if not isinstance(records,list) or not all(isinstance(r,dict) and isinstance(r.get('id'),str)
          and r['id'] and isinstance(r.get('source_id'),str) for r in records):
        raise ValueError('records must be objects with nonempty id and source_id')
    if len({r['id'] for r in records})!=len(records):raise ValueError('record ids must be unique')
    snapshot['records']=records
    save(a.out/'sources.json',snapshot)
    text='\n\n'.join(f"## {p['source_id']} — {p['locator']}\n\n{p['quote']}" for p in snapshot['paragraphs'])
    (a.out/'source-index.md').write_text(text,encoding='utf-8')
    template={'case_id':protocol.get('case_id'),'protocol_sha256':snapshot['protocol_sha256'],
              'title':'','question':protocol['question'],'decisions':[
                  {'record_id':r['id'],'title_abstract':'pending','fulltext':'pending',
                   'criterion':None,'reason':'','quality':[],'evidence':[]} for r in records],
              'sections':[],'gaps':[],'limitations':[]}
    save(a.out/'synthesis-template.json',template)
    return {'status':'partial' if snapshot['paragraphs'] else 'failed',
            'sources':len(snapshot['files']),'records':len(records),'stage':'evidence_prepared'}

def assemble(a):
    snapshot=json.loads(a.sources.read_text());work=json.loads(a.work.read_text())
    protocol=snapshot['protocol'];errors=[];warnings=list(snapshot['failures'])
    if work.get('protocol_sha256')!=snapshot['protocol_sha256']:errors.append('frozen protocol hash mismatch')
    if work.get('case_id')!=protocol.get('case_id'):errors.append('case_id mismatch')
    sources={f['source_id']:f for f in snapshot['files']}
    for f in sources.values():
        p=Path(f['path'])
        if not p.is_file() or p.is_symlink() or sha(p)!=f['sha256']:
            errors.append('source changed: '+f['source_id'])
    context_errors=list(errors)
    paragraphs={(p['source_id'],p['locator']):p for p in snapshot['paragraphs']}
    def evidence(items,allowed=None):
        if not isinstance(items,list) or not items:return ['evidence missing']
        bad=list(context_errors)
        for e in items:
            if not isinstance(e,dict):bad.append('malformed evidence');continue
            p=paragraphs.get((e.get('source_id'),e.get('locator')))
            if p is None or not isinstance(e.get('quote'),str) or not e['quote'].strip() or e['quote'] not in p['quote']:
                bad.append('exact quote/locator mismatch')
            elif e.get('sha256')!=p['sha256']:bad.append('quote source hash mismatch')
            if allowed is not None and e.get('source_id') not in allowed:bad.append('claim uses excluded/unretrieved source')
        return bad
    records={r['id']:r for r in snapshot['records']}
    decisions=work.get('decisions',[])
    if not isinstance(decisions,list):raise ValueError('decisions must be a list')
    decided={};counts=Counter();included=set()
    for d in decisions:
        rid=d.get('record_id')
        if rid not in records or rid in decided:
            errors.append('unknown/duplicate record decision: '+str(rid));continue
        decided[rid]=d
        title,full=d.get('title_abstract'),d.get('fulltext')
        if title not in {'include','exclude','duplicate','pending'}:
            errors.append('invalid title/abstract decision: '+rid);continue
        if title=='duplicate':
            parent=d.get('duplicate_of')
            if parent not in records or parent==rid:errors.append('invalid duplicate target: '+rid)
            elif parent in decided and decided[parent].get('title_abstract')=='duplicate':
                errors.append('duplicate chains must reference a retained primary record')
            counts['duplicates']+=1
        elif title=='exclude':counts['title_excluded']+=1
        elif title=='pending':counts['title_pending']+=1
        else:
            counts['fulltext_requested']+=1
            if full=='include':
                counts['included_records']+=1;included.add(records[rid]['source_id'])
                quality=d.get('quality')
                if a.systematic and (not isinstance(quality,list) or not quality):
                    errors.append('included study quality appraisal missing: '+rid)
                elif isinstance(quality,list):
                    for item in quality:
                        if not item.get('domain') or not item.get('judgment') or not item.get('basis'):
                            errors.append('incomplete quality appraisal: '+rid)
                        errors.extend(evidence(item.get('evidence'),{records[rid]['source_id']}))
            elif full=='exclude':counts['fulltext_excluded']+=1
            elif full=='unretrieved':counts['fulltext_unretrieved']+=1
            elif full=='pending':counts['fulltext_pending']+=1
            else:errors.append('invalid fulltext decision: '+rid)
        if title in {'duplicate','exclude','pending'} and full not in {None,'not_applicable'}:
            errors.append('fulltext state contradicts title decision: '+rid)
        if not d.get('reason'):errors.append('decision reason missing: '+rid)
        if title=='exclude' or (title=='include' and full=='exclude'):
            if d.get('criterion') not in protocol['criteria']:errors.append('unknown exclusion criterion: '+rid)
        if title!='pending' and not (title=='include' and full in {'unretrieved','pending'}):
            bad=evidence(d.get('evidence'),{records[rid]['source_id']})
            errors.extend(rid+': '+x for x in bad)
    for rid in records.keys()-decided.keys():errors.append('record not screened: '+rid)
    # Order-independent duplicate parent validation.
    for rid,d in decided.items():
        if d.get('title_abstract')=='duplicate':
            primary=decided.get(d.get('duplicate_of'),{})
            if primary.get('title_abstract')=='duplicate':errors.append('duplicate chain/cycle: '+rid)
            if not primary:errors.append('duplicate primary has no decision: '+rid)
            parent = records.get(d.get('duplicate_of'), {})
            original = records[rid]
            source = sources.get(original.get('source_id'), {})
            parent_source = sources.get(parent.get('source_id'), {})
            same_source = original.get('source_id') == parent.get('source_id')
            same_bytes = source.get('sha256') and source.get('sha256') == parent_source.get('sha256')
            if not (same_source or same_bytes):
                errors.append('duplicate identity not established by actual source mapping/hash: '+rid)
    counts['included_reports']=len({sources[s]['sha256'] if s in sources else s for s in included})
    pending=sum(counts[k] for k in ('title_pending','fulltext_pending','fulltext_unretrieved'))
    if pending:warnings.append({'pending_records':pending})
    sections=work.get('sections',[])
    if not isinstance(sections,list) or not sections:errors.append('readable synthesis sections missing')
    body=['# '+str(work.get('title') or '证据综述'),'',str(protocol['question'])]
    matrix=[];accepted_sections=[];rejected=[]
    for section in sections:
        if not section.get('heading') or not isinstance(section.get('claims'),list) or not section['claims']:
            errors.append('empty synthesis section');continue
        accepted_claims=[]
        section_body=[]
        for claim in section['claims']:
            if not isinstance(claim.get('text'),str) or not claim['text'].strip():
                errors.append('empty substantive claim');continue
            bad=evidence(claim.get('evidence'),included)
            if claim.get('kind') not in {'finding','comparison','inference','conflict'}:
                bad.append('claim kind missing/invalid')
            if claim.get('kind') in {'comparison','conflict'}:
                ids={e.get('source_id') for e in claim.get('evidence',[]) if isinstance(e,dict)}
                if len(ids)<2:bad.append('cross-source comparison needs at least two evidence sources')
            if bad:
                errors.extend(bad)
                rejected.append({'item':claim,'errors':bad})
                continue
            accepted_claims.append(claim)
            refs=[]
            for e in claim.get('evidence',[]):
                if not isinstance(e,dict):continue
                refs.append(f"[{e.get('source_id')} — {e.get('locator')}]")
                matrix.append({'claim':claim['text'],'kind':claim.get('kind'),'evidence':e})
            section_body+=['',claim['text']+' '+ ' '.join(refs)]
        if accepted_claims:
            accepted_sections.append({'heading':section['heading'],'claims':accepted_claims})
            body+=['','## '+section['heading'],*section_body]
    if not included:
        warnings.append('no included source; only a bounded empty-evidence review is possible')
    body+=['','## 研究空白与限制']
    for gap in work.get('gaps',[]):
        if not isinstance(gap,dict) or not gap.get('text') or gap.get('basis_type') not in {'author_stated','corpus_bounded_inference'}:
            errors.append('gap needs explicit scope and basis');continue
        bad=evidence(gap.get('evidence'),included)
        if bad:
            errors.extend(bad);rejected.append({'item':gap,'errors':bad})
            continue
        body+=['',gap['text']+' '+str(gap['basis_type'])]
    for limit in work.get('limitations',[]):body+=['','- '+str(limit)]
    body+=['','## 筛选计数','',json.dumps(dict(counts),ensure_ascii=False,indent=2)]
    flow={'records_identified':len(records),**dict(counts)}
    flow['closed']=len(records)==sum(counts[k] for k in ('duplicates','title_excluded','title_pending','fulltext_requested')) and counts['fulltext_requested']==sum(
        counts[k] for k in ('included_records','fulltext_excluded','fulltext_unretrieved','fulltext_pending'))
    if not flow['closed']:errors.append('screening flow does not close')
    status='partial' if errors or warnings else 'success'
    result={'case_id':work.get('case_id'),'status':status,'title':work.get('title'),'sections':accepted_sections,'rejected':rejected,
            'screening':decisions,'flow':flow,'evidence_matrix':matrix,'sources':snapshot['files'],
            'uncertainty':warnings,'errors':errors,'protocol_sha256':snapshot['protocol_sha256'],
            'change_log':['Screened each supplied record, checked source-bound evidence, rendered authored synthesis']}
    save(a.out/'result.json',result)
    save(a.out/'validation.json',{'passed':not errors,'errors':errors,'warnings':warnings})
    save(a.out/'flow.json',flow);save(a.out/'evidence-matrix.json',matrix)
    (a.out/'review.md').write_text('\n'.join(body)+'\n',encoding='utf-8')
    return {'status':status,'validation_passed':not errors,'flow':flow,'errors':errors}

def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('prepare');p.add_argument('--input',type=Path,required=True);p.add_argument('--protocol',type=Path,required=True);p.add_argument('--records',type=Path)
    p=sub.add_parser('assemble');p.add_argument('--sources',type=Path,required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--systematic',action='store_true')
    for p in sub.choices.values():p.add_argument('--out',type=Path,required=True)
    a=parser.parse_args()
    if a.mode=='prepare' and (a.out.resolve()==a.input.resolve() or a.input.resolve() in a.out.resolve().parents):
        print(json.dumps({'status':'failed','error':'work output must be outside source input'}));return
    if a.mode=='assemble':
        try:
            raw=json.loads(a.sources.read_text())
            roots=[Path(raw['input_root']).resolve()] if raw.get('input_root') else [
                Path(f['path']).resolve().parent for f in raw.get('files',[])]
            if any(a.out.resolve()==root or root in a.out.resolve().parents for root in roots):
                print(json.dumps({'status':'failed','error':'assembly output must be outside original source tree'}))
                return
        except Exception:
            pass
    a.out.mkdir(parents=True,exist_ok=True)
    if a.mode=='assemble':
        save(a.out/'result.json',{'status':'partial','uncertainty':['assembling current source-bound synthesis']})
        save(a.out/'validation.json',{'passed':False,'errors':['assembly in progress']})
        (a.out/'review.md').write_text('# 本轮综述处理中\n')
    try:r=prepare(a) if a.mode=='prepare' else assemble(a)
    except Exception as exc:
        r={'status':'failed','error':f'{type(exc).__name__}: {exc}'}
        if a.mode=='assemble':
            save(a.out/'result.json',r);save(a.out/'validation.json',{'passed':False,'errors':[r['error']]})
            (a.out/'review.md').write_text('# 本轮综述失败\n\n'+r['error'])
        else:
            save(a.out/'sources.json',{'files':[],'paragraphs':[],'records':[],'failures':[r['error']]})
    print(json.dumps(r,ensure_ascii=False))

if __name__=='__main__':main()
