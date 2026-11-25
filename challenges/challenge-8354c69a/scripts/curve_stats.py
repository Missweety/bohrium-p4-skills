#!/usr/bin/env python3
"""Calculate descriptive curve measurements for explicitly selected CSV columns."""
import argparse,csv,hashlib,json,math,os,tempfile
from pathlib import Path

def main():
 a=argparse.ArgumentParser();a.add_argument('--csv',required=True);a.add_argument('--x',required=True);a.add_argument('--y',required=True);a.add_argument('--out',required=True);x=a.parse_args()
 src=Path(x.csv).resolve(strict=True);out=Path(x.out).resolve()
 if out==src:raise ValueError('output cannot replace source')
 raw=src.read_bytes();rows=[];missing=[]
 with src.open(encoding='utf-8-sig',newline='') as f:
  r=csv.DictReader(f)
  if not r.fieldnames or len(r.fieldnames)!=len(set(r.fieldnames)) or x.x not in r.fieldnames or x.y not in r.fieldnames or x.x==x.y:raise ValueError('explicit, distinct unique columns required')
  for row in r:
   if not row[x.x] or not row[x.y]:missing.append(r.line_num);continue
   u,v=float(row[x.x]),float(row[x.y])
   if not math.isfinite(u) or not math.isfinite(v):raise ValueError('nonfinite value')
   rows.append((r.line_num,u,v))
 if len(rows)<3:raise ValueError('at least three complete rows required')
 ux=sum(r[1] for r in rows)/len(rows);uy=sum(r[2] for r in rows)/len(rows);den=sum((r[1]-ux)**2 for r in rows)
 if den==0:raise ValueError('constant x; slope undefined')
 slope=sum((r[1]-ux)*(r[2]-uy) for r in rows)/den; peak=max(rows,key=lambda r:r[2]);data={'source':str(src),'sha256':hashlib.sha256(raw).hexdigest(),'x':x.x,'y':x.y,'n':len(rows),'missing_rows':missing,'first':{'row':rows[0][0],'x':rows[0][1],'y':rows[0][2]},'last':{'row':rows[-1][0],'x':rows[-1][1],'y':rows[-1][2]},'peak':{'row':peak[0],'x':peak[1],'y':peak[2]},'slope':slope,'intercept':uy-slope*ux,'interpretation':'Descriptive whole-curve regression only; no physical modulus or outlier claim.'}
 if src.read_bytes()!=raw:raise ValueError('source changed during analysis')
 out.parent.mkdir(parents=True,exist_ok=True);fd,t=tempfile.mkstemp(dir=out.parent,prefix='.curve-')
 try:
  with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False)
  os.replace(t,out)
 finally:
  if os.path.exists(t):os.unlink(t)
 print('saved descriptive curve statistics')
if __name__=='__main__':main()
