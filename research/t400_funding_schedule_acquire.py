#!/usr/bin/env python3
"""Acquire T400 funding timestamps only, raw-first. No strategy/performance logic."""
from __future__ import annotations
import argparse,csv,hashlib,json,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
BASE_URL='https://api.manepa.jp'; START_MS=1704067200000; END_MS=1767225600000
SYMBOLS=('BTCUSDT','ETHUSDT'); ENDPOINT='/v5/market/funding/history'
def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def canon(x): return (json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode()
def req(params,base):
 q=urllib.parse.urlencode(sorted(params.items())); url=f"{base.rstrip('/')}{ENDPOINT}?{q}"; started=now()
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'AI-Trading-CP2-T400-Funding/1.0'}),timeout=30) as h: body=h.read(); status=h.status
 received=now(); p=json.loads(body)
 if status!=200 or p.get('retCode')!=0: raise RuntimeError(f"fail-closed HTTP={status} retCode={p.get('retCode')}")
 return body,p,{'source_venue':'Bybit','source_base_url':base.rstrip('/'),'source_endpoint':ENDPOINT,'request_parameters':dict(sorted(params.items())),'request_started_at_utc':started,'response_received_at_utc':received,'http_status':status,'raw_sha256':sha(body),'raw_bytes':len(body),'schema_contract_version':'CP2-v1/T400-funding-schedule-v1'}
def acquire(root,base):
 root.mkdir(parents=True,exist_ok=False); (root/'raw').mkdir(); (root/'normalized').mkdir(); manifest=[]; quality={}
 for symbol in SYMBOLS:
  end=END_MS-1; page=0; events={}
  while end>=START_MS:
   params={'category':'linear','symbol':symbol,'endTime':end,'limit':200}; body,p,prov=req(params,base); xs=p.get('result',{}).get('list',[])
   name=f'{symbol}.funding.{page:05d}'; rp=root/'raw'/f'{name}.json'; pp=root/'raw'/f'{name}.provenance.json'; rp.write_bytes(body); pp.write_bytes(canon(prov))
   manifest.append({'path':str(rp.relative_to(root)),'sha256':sha(body),'provenance_path':str(pp.relative_to(root)),'provenance_sha256':sha(pp.read_bytes())})
   ts=[]
   for x in xs:
    t=int(x['fundingRateTimestamp']); ts.append(t)
    if START_MS<=t<END_MS:
     if t in events and events[t]!=x.get('fundingRate'): raise RuntimeError(f'BLOCK conflicting funding event {symbol} {t}')
     events[t]=x.get('fundingRate','')
   if not ts or min(ts)<START_MS: break
   new_end=min(ts)-1
   if new_end>=end: raise RuntimeError('BLOCK non-progressing funding pagination')
   end=new_end; page+=1; time.sleep(0.07)
  out=root/'normalized'/f'{symbol}.funding.csv'
  with out.open('w',newline='',encoding='utf-8') as f:
   w=csv.writer(f,lineterminator='\n'); w.writerow(['symbol','funding_time_ms','funding_rate'])
   for t in sorted(events): w.writerow([symbol,t,events[t]])
  times=sorted(events); quality[symbol]={'events':len(times),'first_ms':times[0] if times else None,'last_ms':times[-1] if times else None,'strictly_increasing':all(b>a for a,b in zip(times,times[1:])),'in_window':all(START_MS<=t<END_MS for t in times),'pass':bool(times) and all(b>a for a,b in zip(times,times[1:])) and all(START_MS<=t<END_MS for t in times)}
 (root/'manifest.json').write_bytes(canon({'contract':'CP2-v1/T400-funding-schedule-v1','files':manifest})); (root/'quality-report.json').write_bytes(canon({'checks':quality,'overall_pass':all(v['pass'] for v in quality.values())}))
 if not all(v['pass'] for v in quality.values()): raise RuntimeError('BLOCK funding schedule quality gate failed')
def verify(root):
 m=json.loads((root/'manifest.json').read_text())
 for x in m['files']:
  if sha((root/x['path']).read_bytes())!=x['sha256'] or sha((root/x['provenance_path']).read_bytes())!=x['provenance_sha256']: raise RuntimeError('BLOCK SHA mismatch')
 if not json.loads((root/'quality-report.json').read_text())['overall_pass']: raise RuntimeError('BLOCK quality report')
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('cmd',choices=['acquire','verify']); p.add_argument('--out',required=True); p.add_argument('--base-url',default=BASE_URL); a=p.parse_args(); root=Path(a.out); acquire(root,a.base_url) if a.cmd=='acquire' else verify(root)
