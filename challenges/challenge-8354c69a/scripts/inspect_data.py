#!/usr/bin/env python3
"""Inventory actual experiment inputs; previews are not scientific interpretation."""
import argparse,csv,hashlib,json,os,tempfile
from pathlib import Path

def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1<<20),b''):h.update(block)
 return h.hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--input',required=True);a.add_argument('--out',required=True);x=a.parse_args()
 root=Path(x.input).resolve(strict=True);out=Path(x.out).resolve()
 if not root.is_dir() or out==root or out.is_relative_to(root):raise ValueError('inventory output must be outside source tree')
 files=[]
 for p in sorted(root.rglob('*')):
  if p.is_symlink() or not p.is_file():continue
  rec={'path':str(p.relative_to(root)),'sha256':digest(p),'bytes':p.stat().st_size,'status':'ok'}
  try:
   ext=p.suffix.lower()
   if ext in ('.xlsx','.xlsm'):
    import openpyxl
    wb=openpyxl.load_workbook(p,read_only=True,data_only=False); rec['sheets']=[{'name':s.title,'rows':s.max_row,'columns':s.max_column,'preview':[[str(v)[:200] if v is not None else None for v in row] for row in s.iter_rows(min_row=1,max_row=min(3,s.max_row),max_col=min(12,s.max_column),values_only=True)]} for s in wb.worksheets];wb.close()
   elif ext in ('.csv','.tsv'):
    with p.open(encoding='utf-8-sig',newline='') as f:
     reader=csv.reader(f,delimiter='\t' if ext=='.tsv' else ','); rec['header']=next(reader,[]);rec['rows']=sum(1 for _ in reader)
   elif ext=='.mat':
    import scipy.io
    rec['arrays']=[{'name':n,'shape':list(shape),'class':kind} for n,shape,kind in scipy.io.whosmat(str(p))]
  except Exception as e:rec.update(status='partial',error=type(e).__name__+': '+str(e)[:300])
  files.append(rec)
 out.parent.mkdir(parents=True,exist_ok=True);fd,t=tempfile.mkstemp(dir=out.parent,prefix='.inventory-')
 try:
  with os.fdopen(fd,'w') as f:json.dump({'source':str(root),'files':files,'status':'partial' if any(r['status']!='ok' for r in files) else 'ok'},f,ensure_ascii=False,indent=2,allow_nan=False)
  os.replace(t,out)
 finally:
  if os.path.exists(t):os.unlink(t)
 print('inventoried',len(files))
if __name__=='__main__':main()
