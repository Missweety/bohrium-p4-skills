#!/usr/bin/env python3
"""Audit case-sourced finite-domain experimental alternatives; no invented inputs."""
import argparse,json,math,sys,os,tempfile
from pathlib import Path

def number(x):
 return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def reject_nonfinite(x):
 if isinstance(x,float) and not math.isfinite(x):raise ValueError('nonfinite number')
 if isinstance(x,dict):
  for v in x.values():reject_nonfinite(v)
 if isinstance(x,list):
  for v in x:reject_nonfinite(v)

def audit(doc):
 reject_nonfinite(doc)
 errors=[];warnings=[];results=[]
 domains=doc.get('domains',{});contracts=doc.get('contracts',{});versions=doc.get('versions',[])
 if len(versions)!=3:errors.append('exactly three case-specific candidate versions required')
 ids=[v.get('id') for v in versions]
 if any(not isinstance(x,str) or not x.strip() for x in ids) or len(set(str(x) for x in ids))!=len(ids):errors.append('candidate IDs must be nonempty and unique')
 if not isinstance(domains,dict):raise ValueError('domains must be an object')
 if not domains:warnings.append('no finite domains supplied; cannot certify parameter choices')
 if 'budget_cap' not in contracts:warnings.append('budget cap missing; cannot certify budget')
 elif not number(contracts['budget_cap']) or contracts['budget_cap']<0:errors.append('invalid budget cap')
 if not contracts.get('source'):errors.append('missing resource contract source locator')
 for v in versions:
  name=v.get('id','?');err=[];params=v.get('parameters',{})
  for k,allowed in domains.items():
   if isinstance(params.get(k),bool) or (isinstance(params.get(k),float) and not math.isfinite(params[k])):err.append(f'{k}: invalid numeric value')
   if not isinstance(allowed,list) or not allowed:err.append(f'{k}: finite allowed domain missing')
   elif k not in params or params[k] not in allowed:err.append(f'{k}: value outside domain or missing')
  for p in v.get('parameter_evidence',[]):
   if not p.get('source') or not p.get('name'):err.append('parameter evidence missing source or name')
  missing=set(params)-{x.get('name') for x in v.get('parameter_evidence',[])}
  if missing:err.append('missing parameter provenance: '+','.join(sorted(missing)))
  cost=0
  for item in v.get('cost_items',[]):
   qty,price=item.get('quantity'),item.get('unit_price')
   if not number(qty) or not number(price) or qty<0 or price<0 or not item.get('source'):err.append('invalid quantity/price/source');continue
   amount=qty*price
   if not number(amount) or not number(cost+amount):err.append('cost overflow');continue
   cost+=amount
  if not v.get('cost_items'):warnings.append(name+': no priced items, budget cannot be certified')
  cap=contracts.get('budget_cap')
  if number(cap) and cost>cap+1e-9:err.append('budget exceeds cap')
  events=v.get('bookings',[])
  for e in events:
   if not number(e.get('start_h')) or not number(e.get('end_h')) or e['end_h']<=e['start_h'] or not e.get('resource'):err.append('invalid booking');continue
   windows=contracts.get('availability',{}).get(e['resource'],[])
   if not any(isinstance(w,list) and len(w)==2 and number(w[0]) and number(w[1]) and e['start_h']>=w[0] and e['end_h']<=w[1] for w in windows):err.append('booking outside availability: '+e['resource'])
  for i,a in enumerate(events):
   for b in events[i+1:]:
    if a.get('resource')==b.get('resource') and all(number(z) for z in [a.get('start_h'),a.get('end_h'),b.get('start_h'),b.get('end_h')]) and max(a['start_h'],b['start_h'])<min(a['end_h'],b['end_h']):err.append('overlapping bookings: '+str(a.get('resource')))
  if not events:warnings.append(name+': no bookings, schedule cannot be certified')
  power=v.get('power')
  if power:
   try:
    from statsmodels.stats.power import TTestIndPower
    if power.get('design')!='two_independent_equal_variance_two_sided':raise ValueError('unsupported power design')
    if not all(number(power.get(k)) for k in ('n_per_group','difference','sd','alpha')) or (power.get('target') is not None and not number(power['target'])):raise ValueError('invalid power numeric input')
    n=int(power['n_per_group']); effect=float(power['difference'])/float(power['sd']);alpha=float(power['alpha'])
    if n<2 or effect<=0 or not 0<alpha<1 or not power.get('source'):raise ValueError('invalid/missing inputs')
    calc=float(TTestIndPower().power(effect_size=effect,nobs1=n,alpha=alpha,ratio=1,alternative='two-sided'))
    if not number(calc):raise ValueError('nonfinite power')
    power_result={'calculated':calc,'target':power.get('target'),'inputs_source':power['source'],'model':power['design']}
    if power.get('target') is not None and calc<float(power['target']):err.append('power below stated target')
   except ImportError:power_result={'status':'unavailable'};warnings.append(name+': statsmodels unavailable; power not verified')
   except Exception as ex:power_result={'status':'invalid','reason':str(ex)};err.append('invalid or unsupported power calculation')
  else:power_result={'status':'not_requested'}
  results.append({'id':name,'cost':round(cost,4),'power':power_result,'errors':err});errors.extend(name+': '+e for e in err)
 return {'status':'fail' if errors else ('partial' if warnings else 'pass'),'errors':errors,'warnings':warnings,'candidates':results}
def main():
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True);a=p.parse_args();src=Path(a.input).resolve();dst=Path(a.out).resolve()
 if src==dst:raise ValueError('output cannot overwrite input')
 try:result=audit(json.loads(src.read_text(),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON constant: '+x))))
 except Exception as e:result={'status':'fail','errors':[str(e)],'warnings':[],'candidates':[]}
 dst.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(dir=dst.parent,prefix='.audit-')
 try:
  with os.fdopen(fd,'w',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
  os.replace(tmp,dst)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 print(result['status']);return 1 if result['status']=='fail' else 2 if result['status']=='partial' else 0
if __name__=='__main__':sys.exit(main())
