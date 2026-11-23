#!/usr/bin/env python3
"""Build a page/paragraph/line index and check exact quotations, not scientific truth."""
import argparse,hashlib,json,re,shutil,subprocess,zipfile,os,tempfile,xml.etree.ElementTree as ET
from pathlib import Path

def norm(s):return re.sub(r'\s+',' ',s).strip()
def scan(path,root):
 raw=path.read_bytes();r={'file':str(path.relative_to(root)),'sha256':hashlib.sha256(raw).hexdigest(),'units':[],'status':'ok'};ext=path.suffix.lower()
 if ext=='.pdf':
  if not shutil.which('pdftotext'):r['status']='pdftotext_unavailable';return r
  p=subprocess.run(['pdftotext','-layout',str(path),'-'],capture_output=True,timeout=90)
  if p.returncode:r['status']='pdf_error';r['error']=p.stderr.decode('utf8','replace')[:400];return r
  pages=p.stdout.decode('utf8','replace').split('\f')
  if pages and not pages[-1].strip():pages.pop()
  r['units']=[{'page':i+1,'text':s,'status':'ok' if s.strip() else 'empty_or_scanned'} for i,s in enumerate(pages)]
 elif ext=='.docx':
  with zipfile.ZipFile(path) as z:rootxml=ET.fromstring(z.read('word/document.xml'))
  ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
  paragraphs=rootxml.findall('.//w:p',ns)
  r['units']=[{'paragraph':i+1,'text':''.join(t.text or '' for t in p.findall('.//w:t',ns))} for i,p in enumerate(paragraphs)]
  r['limitations']=['drawings and page layout require visual inspection']
 elif ext in ('.txt','.md','.csv','.tsv','.json'):
  s=raw.decode('utf8');r['units']=[{'line':i+1,'text':v} for i,v in enumerate(s.splitlines())]
 else:r['status']='unsupported_visual_or_binary'
 return r

def write_atomic(path, value):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.evidence-')
 try:
  with os.fdopen(fd,'w',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def main():
 a=argparse.ArgumentParser();sp=a.add_subparsers(dest='cmd',required=True)
 p=sp.add_parser('extract');p.add_argument('--input',required=True);p.add_argument('--out',required=True)
 p=sp.add_parser('verify');p.add_argument('--index',required=True);p.add_argument('--review',required=True);p.add_argument('--out',required=True)
 x=a.parse_args()
 if x.cmd=='extract':
  root=Path(x.input).resolve(strict=True);out=Path(x.out).resolve()
  if out==root or out.is_relative_to(root):raise ValueError('output inside input refused')
  rows=[]
  for path in sorted(root.rglob('*')):
   if path.is_symlink():rows.append({'file':str(path.relative_to(root)),'status':'symlink_skipped','units':[]});continue
   if not path.is_file():continue
   try:rows.append(scan(path,root))
   except Exception as e:rows.append({'file':str(path.relative_to(root)),'status':'extraction_error','error':str(e)[:250],'units':[]})
  result={'input_root':str(root),'documents':rows,'notice':'Extracted text is not semantic review; inspect unreadable pages and figures.'};rc=0
 else:
  index_path=Path(x.index).resolve(strict=True);review_path=Path(x.review).resolve(strict=True);out=Path(x.out).resolve()
  if out in (index_path,review_path):raise ValueError('output cannot overwrite input index or review')
  index=json.loads(index_path.read_text());source_root=Path(index['input_root']).resolve(strict=True)
  if out==source_root or out.is_relative_to(source_root):raise ValueError('output inside source refused')
  # Invalidate previous success before parsing review or checking source versions.
  write_atomic(out,{'status':'failed','checks':[],'reason':'verification incomplete'})
  review=json.loads(review_path.read_text());docs={d['file']:d for d in index['documents']};checks=[]
  for doc in docs.values():
   if not doc.get('sha256'):continue
   source=(source_root/doc['file']).resolve()
   if not source.is_relative_to(source_root) or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=doc['sha256']:
    raise ValueError('source missing, changed or outside root: '+str(doc['file']))
  for finding in review.get('findings',[]):
   for key in ('claim','evidence'):
    quote=finding.get(key+'_quote');loc=finding.get(key+'_location') or {};doc=docs.get(loc.get('file'));matched=False;reason='missing quote or locator'
    if isinstance(quote,str) and norm(quote) and doc:
     matches=[u for u in doc.get('units',[]) if any(k in loc and loc[k]==u.get(k) for k in ('page','paragraph','line'))]
     matched=len(matches)==1 and norm(quote) in norm(matches[0].get('text',''))
     reason='matched' if matched else 'quote absent at specified unit or unit unavailable'
    checks.append({'finding':finding.get('id'),'kind':key,'matched':matched,'reason':reason})
  rc=0 if checks and all(c['matched'] for c in checks) else (0 if not review.get('findings') else 1);result={'status':'ok' if rc==0 else 'mismatch','checks':checks,'notice':'Literal match only; neither meaning nor scientific validity verified.'}
 p=Path(x.out);write_atomic(p,result);print(json.dumps({'status':'ok' if rc==0 else 'mismatch','count':len(rows) if x.cmd=='extract' else len(checks)}));return rc
if __name__=='__main__':raise SystemExit(main())
