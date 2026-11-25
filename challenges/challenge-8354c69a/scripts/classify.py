#!/usr/bin/env python3
"""Explicit repeated stratified holdout; each scaler fits training data only."""
import argparse,csv,hashlib,json,math,os,tempfile
from pathlib import Path

def main():
 a=argparse.ArgumentParser();a.add_argument('--data',required=True);a.add_argument('--plan',required=True);a.add_argument('--out',required=True);x=a.parse_args()
 data=Path(x.data).resolve(strict=True);planpath=Path(x.plan).resolve(strict=True);out=Path(x.out).resolve()
 if out in (data,planpath):raise ValueError('output overlaps input')
 plan=json.loads(planpath.read_text()); features=plan['features'];label=plan['label'];seeds=plan['seeds'];models=plan['models'];test_size=plan['test_size']
 if len(features)==0 or len(set(features))!=len(features) or label in features:raise ValueError('invalid features/label')
 if len(seeds)!=5 or any(isinstance(v,bool) or not isinstance(v,int) or not 0<=v<=4294967295 for v in seeds) or len(set(seeds))!=5 or len(models)!=2 or len({m.get('name') for m in models})!=2:raise ValueError('plan needs five distinct integer seeds in [0, 2^32-1] and two distinct named models')
 if isinstance(test_size,bool) or not 0<float(test_size)<1:raise ValueError('test_size must be a fraction between zero and one')
 import numpy as np
 from sklearn.model_selection import train_test_split
 from sklearn.impute import SimpleImputer
 from sklearn.preprocessing import StandardScaler
 from sklearn.pipeline import make_pipeline
 from sklearn.neighbors import KNeighborsClassifier
 from sklearn.linear_model import LogisticRegression
 from sklearn.metrics import accuracy_score,confusion_matrix,classification_report
 import sklearn
 raw=data.read_bytes();array=[];labels=[];ids=[]
 with data.open(encoding='utf-8-sig',newline='') as f:
  reader=csv.DictReader(f)
  if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames) or any(c not in reader.fieldnames for c in features+[label]):raise ValueError('missing/duplicate columns')
  for row in reader:
   vals=[]
   for c in features:
    v=row[c].strip(); n=float(v) if v else float('nan')
    if v and not math.isfinite(n):raise ValueError('nonfinite feature')
    vals.append(n)
   if not row[label].strip():raise ValueError('missing target')
   array.append(vals);labels.append(row[label]);ids.append(reader.line_num)
 X=np.asarray(array,dtype=float);y=np.asarray(labels);classes=sorted(set(labels));runs=[]
 for seed in seeds:
  tr,te=train_test_split(np.arange(len(y)),test_size=float(test_size),random_state=int(seed),stratify=y)
  for model in models:
   name=model['name'];params=model.get('params',{})
   if name=='knn': estimator=KNeighborsClassifier(**params)
   elif name=='logistic':estimator=LogisticRegression(**params)
   else:raise ValueError('unknown estimator; use required case estimator or implement separately')
   pipeline=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),estimator) if plan.get('standardize',True) else make_pipeline(SimpleImputer(strategy='median'),estimator)
   pipeline.fit(X[tr],y[tr]);pred=pipeline.predict(X[te]);runs.append({'seed':seed,'model':name,'parameters':params,'train_rows':[ids[i] for i in tr],'test_rows':[ids[i] for i in te],'true':y[te].tolist(),'predicted':pred.tolist(),'accuracy':float(accuracy_score(y[te],pred)),'class_order':classes,'confusion_matrix':confusion_matrix(y[te],pred,labels=classes).tolist(),'classification_report':classification_report(y[te],pred,labels=classes,output_dict=True,zero_division=0)})
 if data.read_bytes()!=raw:raise ValueError('source changed')
 summary={m['name']:{'mean_accuracy':float(np.mean([r['accuracy'] for r in runs if r['model']==m['name']])),'std_accuracy_ddof1':float(np.std([r['accuracy'] for r in runs if r['model']==m['name']],ddof=1))} for m in models}
 result={'status':'ok','data':str(data),'sha256':hashlib.sha256(raw).hexdigest(),'features':features,'label':label,'sklearn':sklearn.__version__,'plan':plan,'runs':runs,'summary':summary,'limits':['Random splits are repeated computational evaluations, not independent biological replicates.']}
 out.parent.mkdir(parents=True,exist_ok=True);fd,t=tempfile.mkstemp(dir=out.parent,prefix='.classify-')
 try:
  with os.fdopen(fd,'w') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
  os.replace(t,out)
 finally:
  if os.path.exists(t):os.unlink(t)
 print('saved',len(runs),'split-model results')
if __name__=='__main__':main()
