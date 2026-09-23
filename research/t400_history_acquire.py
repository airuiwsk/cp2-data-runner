#!/usr/bin/env python3
"""Acquire only the preregistered T400 input surfaces under CP2 raw-first rules.

No signal, return, PnL, threshold evaluation, or strategy metric is computed here.
Window is frozen by T400: 2024-01-01 through 2025-12-31 UTC.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL="https://api.manepa.jp"
START_MS=1704067200000
END_MS=1767225600000  # 2026-01-01T00:00:00Z exclusive
SYMBOLS=("BTCUSDT","ETHUSDT")
SURFACES={"premium":"/v5/market/premium-index-price-kline","tradeable":"/v5/market/kline"}
STEP_MS=1000*60*1000


def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def canon(x): return (json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode()

def req(endpoint, params, base):
    q=urllib.parse.urlencode(sorted(params.items())); url=f"{base.rstrip('/')}{endpoint}?{q}"
    started=now(); r=urllib.request.Request(url,headers={'User-Agent':'AI-Trading-CP2-T400/1.0'})
    with urllib.request.urlopen(r,timeout=30) as h: body=h.read(); status=h.status
    received=now(); p=json.loads(body)
    if status!=200 or p.get('retCode')!=0: raise RuntimeError(f"fail-closed HTTP={status} retCode={p.get('retCode')}")
    return body, {'source_venue':'Bybit','source_base_url':base.rstrip('/'),'source_endpoint':endpoint,
      'request_parameters':dict(sorted(params.items())),'request_started_at_utc':started,
      'response_received_at_utc':received,'http_status':status,'raw_sha256':sha(body),'raw_bytes':len(body),
      'schema_contract_version':'CP2-v1/T400-input-v1'}

def acquire(root:Path,base:str):
    root.mkdir(parents=True,exist_ok=False); manifest=[]; quality={}
    for symbol in SYMBOLS:
      for surface,endpoint in SURFACES.items():
        norm=root/'normalized'/f'{symbol}.{surface}.csv'; norm.parent.mkdir(parents=True,exist_ok=True)
        seen=set(); rows=0; missing_chunks=[]
        with norm.open('w',newline='',encoding='utf-8') as f:
          w=csv.writer(f,lineterminator='\n'); w.writerow(['symbol','dataset','start_ms','open','high','low','close','volume','turnover','raw_sha256'])
          chunk=0
          for s in range(START_MS,END_MS,STEP_MS):
            e=min(s+STEP_MS,END_MS); params={'category':'linear','symbol':symbol,'interval':'1','start':s,'end':e-1,'limit':1000}
            body,prov=req(endpoint,params,base); name=f'{symbol}.{surface}.{chunk:05d}'
            rp=root/'raw'/f'{name}.json'; pp=root/'raw'/f'{name}.provenance.json'; rp.parent.mkdir(parents=True,exist_ok=True)
            rp.write_bytes(body); pp.write_bytes(canon(prov)); manifest.append({'path':str(rp.relative_to(root)),'sha256':sha(body),'provenance_path':str(pp.relative_to(root)),'provenance_sha256':sha(pp.read_bytes())})
            payload=json.loads(body); xs=[]
            for x in payload['result']['list']:
              t=int(x[0])
              if s<=t<e: xs.append(x)
            xs.sort(key=lambda x:int(x[0])); expected=(e-s)//60000
            if len(xs)!=expected or any(int(x[0])!=s+i*60000 for i,x in enumerate(xs)): missing_chunks.append({'chunk':chunk,'start_ms':s,'end_ms':e,'rows':len(xs),'expected':expected})
            for x in xs:
              t=int(x[0]);
              if t in seen: raise RuntimeError(f'BLOCK duplicate {symbol} {surface} {t}')
              seen.add(t); extra=(x[5],x[6]) if surface=='tradeable' else ('','')
              w.writerow([symbol,surface,t,x[1],x[2],x[3],x[4],extra[0],extra[1],prov['raw_sha256']]); rows+=1
            chunk+=1; time.sleep(0.07)
        quality[f'{symbol}.{surface}']={'rows':rows,'expected_rows':(END_MS-START_MS)//60000,'bad_chunks':missing_chunks,'pass':not missing_chunks and rows==(END_MS-START_MS)//60000}
    (root/'manifest.json').write_bytes(canon({'contract':'CP2-v1/T400-input-v1','files':manifest}))
    (root/'quality-report.json').write_bytes(canon({'checks':quality,'overall_pass':all(v['pass'] for v in quality.values())}))
    if not all(v['pass'] for v in quality.values()): raise RuntimeError('BLOCK historical continuity gate failed')

def verify(root:Path):
    m=json.loads((root/'manifest.json').read_text())
    for x in m['files']:
      if sha((root/x['path']).read_bytes())!=x['sha256'] or sha((root/x['provenance_path']).read_bytes())!=x['provenance_sha256']: raise RuntimeError('BLOCK SHA mismatch')
    q=json.loads((root/'quality-report.json').read_text())
    if not q['overall_pass']: raise RuntimeError('BLOCK quality report')

if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('cmd',choices=['acquire','verify']); p.add_argument('--out',required=True); p.add_argument('--base-url',default=BASE_URL); a=p.parse_args(); root=Path(a.out)
 acquire(root,a.base_url) if a.cmd=='acquire' else verify(root)
