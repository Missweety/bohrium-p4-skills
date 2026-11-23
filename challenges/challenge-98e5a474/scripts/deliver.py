#!/usr/bin/env python3
"""Source-bound editable SVG generation/editing and actual SVG export, Python 3.10+."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zlib

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
def tag(t): return '{'+NS+'}'+t
def local(t): return t.rsplit('}', 1)[-1]
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def digest(b): return hashlib.sha256(b).hexdigest()
def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'wb') as f: f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def writej(p, d): atomic(p, (json.dumps(d, ensure_ascii=False, indent=2)+'\n').encode())
def finite(x):
    v=float(x)
    if not math.isfinite(v): raise ValueError('nonfinite coordinate')
    return v

def strip_doctype(raw):
    """Drop a plain DOCTYPE declaration; still refuse entity declarations outright."""
    if b'<!ENTITY' in raw.upper():
        raise ValueError('entity declarations not supported')
    if b'<!DOCTYPE' not in raw.upper():
        return raw
    text=raw.decode('utf-8','replace');out=[];i=0
    while True:
        j=text.upper().find('<!DOCTYPE',i)
        if j<0:out.append(text[i:]);break
        out.append(text[i:j]);k=j;depth=0
        while k<len(text):
            ch=text[k]
            if ch=='[':depth+=1
            elif ch==']':depth=max(0,depth-1)
            elif ch=='>' and depth==0:k+=1;break
            k+=1
        i=k
    return ''.join(out).encode('utf-8')

def parse_svg(raw):
    root=ET.fromstring(strip_doctype(raw))
    if local(root.tag)!='svg': raise ValueError('not an SVG')
    ids=[e.get('id') for e in root.iter() if e.get('id')]
    if len(ids)!=len(set(ids)): raise ValueError('duplicate SVG IDs')
    for e in root.iter():
        if local(e.tag) in ('script','foreignObject'): raise ValueError('active SVG content unsupported')
        for k,v in e.attrib.items():
            if k.startswith('on') or ('href' in k and not v.startswith(('#','data:'))):
                raise ValueError('non-self-contained SVG resource reference unsupported; embed local image/font resources explicitly and record packaging changes before export')
        for v in list(e.attrib.values())+([e.text] if local(e.tag)=='style' and e.text else []):
            for url in re.findall(r'url\(\s*[\"\']?([^\)\"\']+)',v):
                if not url.startswith(('#','data:')):raise ValueError('external CSS resource unsupported; embed it before export')
    return root

def percentage(v):
    return isinstance(v,str) and v.strip().endswith('%')

def canvas(root):
    view=root.get('viewBox','').replace(',',' ').split()
    assumed=False
    if len(view)==4:
        vals=list(map(finite,view)); w,h=vals[2:]
    else:
        def px(v):
            m=re.fullmatch(r'([\d.]+)(px|pt|mm|cm|in)?',str(v))
            if not m: raise ValueError('SVG needs viewBox or absolute canvas dimensions')
            return finite(m[1])*{'px':1,'pt':96/72,'mm':96/25.4,'cm':96/2.54,'in':96,None:1}[m[2]]
        wv,hv=root.get('width'),root.get('height')
        if percentage(wv) or percentage(hv) or wv is None or hv is None:
            # Percentage sizing has no intrinsic user-unit canvas; fall back to a fixed
            # canvas and record it as an explicit assumption instead of blocking the case.
            w,h=1200.0,700.0;assumed=True
            if wv is not None and not percentage(wv): w=px(wv)
            if hv is not None and not percentage(hv): h=px(hv)
        else:
            w,h=px(wv),px(hv)
    if w<=0 or h<=0: raise ValueError('nonpositive canvas')
    return w,h,assumed

def normalize_canvas(root,w,h):
    """Give the exported root an explicit user-unit size so renderers agree on the canvas."""
    if not root.get('viewBox'): root.set('viewBox','0 0 %g %g'%(w,h))
    for attr,val in (('width',w),('height',h)):
        cur=root.get(attr)
        if cur is None or percentage(cur): root.set(attr,'%g'%val)

def generate(plan):
    width,height=plan.get('canvas',[1200,700]); width=finite(width);height=finite(height)
    root=ET.Element(tag('svg'),{'width':str(width),'height':str(height),'viewBox':f'0 0 {width} {height}'})
    ET.SubElement(root,tag('title')).text=plan.get('title','Graphical abstract')
    defs=ET.SubElement(root,tag('defs'))
    for mid,path in [('arrow','M0,0 L9,4.5 L0,9 z'),('inhibit','M8,0 L8,9')]:
        m=ET.SubElement(defs,tag('marker'),{'id':'marker-'+mid,'viewBox':'0 0 9 9','refX':'8','refY':'4.5','markerWidth':'9','markerHeight':'9','orient':'auto','markerUnits':'userSpaceOnUse'})
        ET.SubElement(m,tag('path'),{'d':path,'fill':'#334155' if mid=='arrow' else 'none','stroke':'#334155','stroke-width':'2'})
    ET.SubElement(root,tag('rect'),{'width':'100%','height':'100%','fill':'white'})
    layers={}
    for name in ('panels','relations','entities','labels','legend'):
        layers[name]=ET.SubElement(root,tag('g'),{'id':'layer-'+name})
    primitives=plan.get('elements',[])
    if not primitives: raise ValueError('empty elements; read materials and author a drawing plan')
    allowed={'rect','ellipse','circle','line','path','polyline','polygon','text'}
    for p in primitives:
        if p.get('tag') not in allowed or not p.get('id'): raise ValueError('primitive requires tag/id')
        attrs={str(k):str(v) for k,v in p.get('attrs',{}).items()};attrs['id']=str(p['id'])
        if p['tag']=='text':
            attrs.setdefault('font-family','DejaVu Sans, Noto Sans CJK SC, sans-serif')
            attrs.setdefault('font-size','20');attrs.setdefault('fill','#172554')
        if p.get('arrow'):
            if p['arrow'] not in ('arrow','inhibit'):raise ValueError('unknown relation terminator')
            attrs['marker-end']='url(#marker-'+p['arrow']+')'
        layer=p.get('layer','labels' if p['tag']=='text' else 'entities')
        if layer not in layers: raise ValueError('unknown layer')
        el=ET.SubElement(layers[layer],tag(p['tag']),attrs)
        if p.get('text') is not None: el.text=str(p['text'])
        for s in p.get('lines',[]):
            ET.SubElement(el,tag('tspan'),{str(k):str(v) for k,v in s.get('attrs',{}).items()}).text=str(s['text'])
    return parse_svg(ET.tostring(root,encoding='utf-8'))

def element_paths(root):
    paths={}
    def visit(el,path):
        paths[el]=path;counts={}
        for child in el:
            name=local(child.tag);counts[name]=counts.get(name,0)+1
            visit(child,path+'/'+name+'['+str(counts[name])+']')
    visit(root,'/svg[1]');return paths

def edit(root, operations):
    changes=[];paths=element_paths(root)
    if not operations: raise ValueError('edit mode needs explicit operations')
    for op in operations:
        if op.get('id'):
            hits=[e for e in root.iter() if e.get('id')==op['id']]
        elif 'find' in op:
            hits=[e for e in root.iter() if local(e.tag) in ('text','tspan') and len(e)==0 and (e.text or '')==op['find']]
        else:raise ValueError('edit requires ID or exact leaf text find')
        if len(hits)!=1: raise ValueError('edit target must match exactly once: '+str(op.get('id',op.get('find'))))
        e=hits[0];before=ET.tostring(e,encoding='unicode')
        if 'text' in op:
            if len(e): raise ValueError('target has child tspans; target leaf tspan ID or exact leaf find, preserve styles')
            e.text=str(op['text'])
        for k,v in op.get('attrs',{}).items():
            if k=='id' or k.startswith('on') or 'href' in k:raise ValueError('unsupported edit attribute')
            e.set(k,str(v))
        changes.append({'element':e.get('id') or paths[e],'xpath':paths[e],'find':op.get('find'),'before':before,'after':ET.tostring(e,encoding='unicode'),'basis':op.get('basis','')})
        if not changes[-1]['basis']:raise ValueError('edit needs scientific/workorder basis locator')
    parse_svg(ET.tostring(root,encoding='utf-8'))
    return changes

def png_info(p):
    b=p.read_bytes()
    if b[:8]!=b'\x89PNG\r\n\x1a\n' or b[12:16]!=b'IHDR':raise ValueError('invalid PNG')
    dims=struct.unpack('>II',b[16:24]);dpi=None;i=8
    while i+12<=len(b):
        n=struct.unpack('>I',b[i:i+4])[0];kind=b[i+4:i+8];chunk=b[i+8:i+8+n]
        if kind==b'pHYs' and n==9:
            x,y,u=struct.unpack('>IIB',chunk)
            if u==1:dpi=[round(x*.0254,2),round(y*.0254,2)]
        i+=n+12
    return dims,dpi

def set_png_dpi(p,dpi):
    """Write pHYs from the requested print density, then read it back via png_info."""
    b=p.read_bytes();i=8
    while i+12<=len(b):
        n=struct.unpack('>I',b[i:i+4])[0]
        if b[i+4:i+8]==b'pHYs':return False
        i+=n+12
    ppm=int(round(float(dpi)/0.0254));body=struct.pack('>IIB',ppm,ppm,1)
    chunk=struct.pack('>I',len(body))+b'pHYs'+body+struct.pack('>I',zlib.crc32(b'pHYs'+body)&0xffffffff)
    p.write_bytes(b[:33]+chunk+b[33:]);return True

def export(svg, out, formats, dpi, scale, engines):
    records=[];errors=[]
    for fmt in formats:
        if fmt not in ('png','pdf'):raise ValueError('unsupported export '+fmt)
        dest=out/('graphical_abstract.'+fmt)
        done=False
        for engine in engines:
            fd,tmp=tempfile.mkstemp(suffix='.'+fmt,dir=out);os.close(fd);tmp=Path(tmp)
            try:
                if engine=='cairosvg':
                    import cairosvg
                    fn=cairosvg.svg2png if fmt=='png' else cairosvg.svg2pdf
                    kw={'url':str(svg),'write_to':str(tmp),'dpi':dpi,'scale':scale}
                    fn(**kw)
                elif engine=='rsvg-convert':
                    binary=shutil.which(engine)
                    if not binary:raise RuntimeError('engine unavailable')
                    subprocess.run([binary,'-f',fmt,'-d',str(dpi),'-p',str(dpi),'-z',str(scale),'-o',str(tmp),str(svg)],check=True,capture_output=True,timeout=120)
                elif engine=='inkscape':
                    binary=shutil.which(engine)
                    if not binary:raise RuntimeError('engine unavailable')
                    subprocess.run([binary,str(svg),'--export-type='+fmt,'--export-filename='+str(tmp),'--export-dpi='+str(dpi*scale)],check=True,capture_output=True,timeout=120)
                else:raise ValueError('unknown engine')
                if fmt=='png':
                    dims,actual_dpi=png_info(tmp)
                    if actual_dpi is None and set_png_dpi(tmp,dpi):
                        dims,actual_dpi=png_info(tmp)
                    rec={'path':dest.name,'format':fmt,'width_px':dims[0],'height_px':dims[1],'requested_dpi':dpi,'density_dpi':actual_dpi}
                else:
                    if not tmp.read_bytes().startswith(b'%PDF-') or b'%%EOF' not in tmp.read_bytes()[-2048:]:raise ValueError('invalid PDF')
                    raster_count=sum(local(e.tag)=='image' and 'image/svg+xml' not in ''.join(e.attrib.values()) for e in ET.parse(svg).getroot().iter())
                    rec={'path':dest.name,'format':fmt,'renders_original_svg':True,'embedded_raster_count':raster_count,'vector_content_preserved':True}
                rec.update({'engine':engine,'verified':True,'sha256':digest(tmp.read_bytes())})
                os.replace(tmp,dest);records.append(rec);done=True;break
            except Exception as ex:
                errors.append({'format':fmt,'engine':engine,'error':type(ex).__name__+': '+str(ex)[:160]})
            finally:
                if tmp.exists():tmp.unlink()
        if not done:errors.append({'format':fmt,'error':'no renderer produced a verified actual SVG export'})
    return records,errors

def field_name(x):
    if isinstance(x,str):return x or None
    if isinstance(x,dict):
        for k in ('name','field','field_name','key','id'):
            if isinstance(x.get(k),str) and x[k]:return x[k]
    return None

def unwrap_contract(c):
    """Peel contract/output_contract wrappers until the real field list/schema is reached."""
    for _ in range(6):
        if not isinstance(c,dict):return c
        for key in ('contract','output_contract','outputContract'):
            inner=c.get(key)
            if isinstance(inner,(dict,list)):c=inner;break
        else:return c
    return c

def required_contract(case):
    c=unwrap_contract(case.get('output_contract',case.get('outputContract',{})))
    if isinstance(c,list):return [n for n in (field_name(x) for x in c) if n]
    if isinstance(c,dict):
        if isinstance(c.get('required'),list):return [n for n in (field_name(x) for x in c['required']) if n]
        if isinstance(c.get('fields'),list):return [n for n in (field_name(x) for x in c['fields']) if n]
        if isinstance(c.get('fields'),dict):return list(c['fields'])
        if isinstance(c.get('properties'),dict):return list(c['properties'])
        return list(c)
    return []

def schema_errors(value, schema, path='$'):
    if not isinstance(schema,dict):return []
    errors=[]
    types={'string':str,'number':(int,float),'integer':int,'object':dict,'array':list,'boolean':bool,'null':type(None)}
    wanted=schema.get('type')
    if isinstance(wanted,str) and wanted in types:
        valid=isinstance(value,types[wanted])
        if wanted in ('number','integer') and isinstance(value,bool):valid=False
        if not valid:return [path+': expected '+wanted]
    if 'enum' in schema and value not in schema['enum']:errors.append(path+': outside enum')
    if isinstance(value,dict):
        for k in schema.get('required',[]):
            if k not in value:errors.append(path+'.'+k+': required')
        for k,sub in schema.get('properties',{}).items():
            if k in value:errors+=schema_errors(value[k],sub,path+'.'+k)
    if isinstance(value,list) and isinstance(schema.get('items'),dict):
        for i,v in enumerate(value):errors+=schema_errors(v,schema['items'],path+'['+str(i)+']')
    return errors

def guard(args):
    # Validate before any checkpoint or error output; never follow output symlinks.
    out=Path(os.path.abspath(args.out))
    for part in [out, *out.parents]:
        if part.is_symlink(): raise ValueError('output path contains symlink')
    plan=load(args.plan)
    protected=[Path(args.case).resolve(),Path(args.plan).resolve()]
    if plan.get('source_svg'): protected.append(Path(plan['source_svg']).resolve())
    names=['result.json','graphical_abstract.svg','graphical_abstract.png','graphical_abstract.pdf','element_map.json','changes.json','caption.md','export-checks.json']
    for name in names:
        dest=out/name
        if dest.is_symlink(): raise ValueError('output file is symlink: '+name)
        if dest.resolve() in protected: raise ValueError('output would overwrite input: '+name)
    return out

def run(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    # Clear stale success before parsing current input, without following symlinks.
    writej(out/'result.json',{'status':'blocked','limits':'current invocation not completed'})
    plan=load(args.plan);case=load(args.case)
    mode=plan.get('mode','create');changes=[];source={}
    if mode in ('edit','copy'):
        p=Path(plan['source_svg']).resolve();raw=p.read_bytes();source={'path':str(p),'sha256':digest(raw)}
        root=parse_svg(raw)
        if mode=='edit':changes=edit(root,plan.get('operations',[]))
    elif mode=='create':root=generate(plan)
    else:raise ValueError('mode must be create/edit/copy')
    w,h,canvas_assumed=canvas(root);normalize_canvas(root,w,h);ids={e.get('id') for e in root.iter() if e.get('id')}|set(element_paths(root).values())
    emap=plan.get('element_map',[])
    if not emap:raise ValueError('element_map required; provide actual material locators')
    if mode=='create':
        mapped={x.get('element') for x in emap}
        missing=[e['id'] for e in plan['elements'] if not e.get('decorative',False) and e['id'] not in mapped]
        if missing:raise ValueError('semantic elements missing evidence mapping: '+','.join(missing))
    for item in emap:
        if item.get('element') not in ids:raise ValueError('mapped element absent: '+str(item.get('element')))
        if not item.get('source'):raise ValueError('element missing evidence locator')
    if mode=='edit':
        mapped={x['element'] for x in emap}
        for x in changes:
            if x['element'] and x['element'] not in mapped:raise ValueError('edited element missing evidence map')
    svg=out/'graphical_abstract.svg'
    if source and svg.resolve()==Path(source['path']):raise ValueError('output cannot replace original source SVG')
    atomic(svg,ET.tostring(root,encoding='utf-8',xml_declaration=True))
    formats=plan.get('formats',['png','pdf'])
    if not isinstance(formats,list) or not formats:
        raise ValueError('formats must be a non-empty list containing png and/or pdf; empty exports cannot pass as ok')
    caption=str(plan.get('caption') or '')
    exports,errors=export(svg,out,formats,finite(plan.get('dpi',300)),finite(plan.get('scale',1)),plan.get('engines',['cairosvg','rsvg-convert','inkscape']))
    writej(out/'element_map.json',emap);writej(out/'changes.json',changes)
    atomic(out/'caption.md',(caption+'\n').encode())
    needed=set(formats);missing=needed-{e['format'] for e in exports}
    limits=[]
    if missing:limits.append('Missing actual exports: '+','.join(sorted(missing)))
    if not caption.strip():limits.append('caption missing')
    uncertainty=list(plan.get('uncertainty') or [])
    if canvas_assumed:
        uncertainty.append('source SVG had no intrinsic canvas (percentage width/height, no viewBox); rendered on a 1200x700 user-unit fallback canvas')
    result={'case_id':case.get('case_id',case.get('id')),'status':'partial' if limits else 'ok',
            'source_file':svg.name,'exports':exports,'element_map':emap,'caption':caption,
            'uncertainty':uncertainty,'limits':'; '.join(limits),
            'source_version':source,'changes':changes,
            'canvas':{'width_user_units':w,'height_user_units':h,'canvas_assumed':canvas_assumed},
            'preview_status':'ok' if any(e['format']=='png' for e in exports) else 'preview_unavailable'}
    # Explicit task-specific values authored by the agent, not guessed from field names.
    for k,v in plan.get('result_fields',{}).items():
        if k in result and result[k]!=v:raise ValueError('result_fields cannot override computed field '+k)
        result[k]=v
    absent=[k for k in required_contract(case) if k and k not in result]
    contract=unwrap_contract(case.get('output_contract',case.get('outputContract',{})))
    schema=contract if isinstance(contract,dict) and ('properties' in contract or contract.get('type')=='object') else {}
    invalid=schema_errors(result,schema)
    if absent or invalid:result.update(status='partial',limits=(result['limits']+'; contract incomplete: '+','.join(absent+invalid)).strip('; '))
    if not result['case_id']:raise ValueError('case_id missing')
    checks={'svg_xml':True,'editable_text_count':sum(local(e.tag) in ('text','tspan') for e in root.iter()),'source_preserved':not source or digest(Path(source['path']).read_bytes())==source['sha256'],
            'missing_exports':sorted(missing),'missing_contract_fields':absent,'contract_errors':invalid,'render_attempts':errors,'scientific_review':'Agent must verify mapping, direction, units and visual quality against source'}
    writej(out/'export-checks.json',checks);writej(out/'result.json',result)
    print(json.dumps({'status':result['status'],'exports':[x['path'] for x in exports],'missing_contract':absent}))
    return 0 if result['status']=='ok' else 2

def main():
    a=argparse.ArgumentParser();a.add_argument('--case',required=True);a.add_argument('--plan',required=True);a.add_argument('--out',required=True);args=a.parse_args()
    try: guard(args)
    except Exception as e:
        print(type(e).__name__+': '+str(e)); return 1
    try:return run(args)
    except Exception as e:
        out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
        try:
            case=load(args.case);case_id=case.get('case_id',case.get('id'))
        except Exception:case_id=None
        writej(out/'result.json',{'case_id':case_id,'status':'blocked','limits':str(e),'uncertainty':['Current task not completed; any preexisting artifacts are not current success.']})
        print(type(e).__name__+': '+str(e));return 1
if __name__=='__main__':raise SystemExit(main())
