#!/usr/bin/env python3
"""Acquire only missing boundary minutes required by frozen T400 C6 evaluator.
No strategy/performance computation. Raw-first SHA/provenance preserved.
"""
from __future__ import annotations
import csv, hashlib, json, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE='https://api.manepa.jp'; SYMBOLS=('BTCUSDT','ETHUSDT')
# Frozen evaluator needs signal/entry t-1m for first event and exit t+5m for final in-window event.
# Fetch a narrow envelope, not a changed trial window.
TIMES=(1704067140000,1767225900000)  # 2023-12-31 23:59Z; 2026-01-01 00:05Z
SURFACES={'premium':'/v5/market/premium-index-price-kline','tradeable':'/v5/market/kline'}
def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def canon(x): return (json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode()
def request(endpoint,params):
 q=urllib.parse.urlencode(sorted(params.items())); url=f'{BASE}{endpoint}?{q}'; started=now()
 r=urllib.request.Request(url,headers={'User-Agent':'AI-Trading-T400-boundary/1.0'})
 with urllib.request.urlopen(r,timeout=30) as h: body=h.read(); status=h.status
 p=json.loads(body); received=now()
 if status!=200 or p.get('retCode')!=0: raise RuntimeError(f'BLOCK HTTP={status} retCode={p.get("retCode")}')
 prov={'source_venue':'Bybit','source_base_url':BASE,'source_endpoint':endpoint,'request_parameters':dict(sorted(params.items())),'request_started_at_utc':started,'response_received_at_utc':received,'http_status':status,'raw_sha256':sha(body),'raw_bytes':len(body),'schema_contract_version':'CP2-v1/T400-boundary-v1'}
 return body,prov

def acquire(root):
 root=Path(root); root.mkdir(parents=True,exist_ok=False); files=[]
 for symbol in SYMBOLS:
  for surface,endpoint in SURFACES.items():
   out=root/'normalized'/f'{symbol}.{surface}.csv'; out.parent.mkdir(parents=True,exist_ok=True)
   with out.open('w',newline='',encoding='utf-8') as f:
    w=csv.writer(f,lineterminator='\n'); w.writerow(['symbol','dataset','start_ms','open','high','low','close','volume','turnover','raw_sha256'])
    for t in TIMES:
     params={'category':'linear','symbol':symbol,'interval':'1','start':t,'end':t+59999,'limit':1}
     body,prov=request(endpoint,params); tag=f'{symbol}.{surface}.{t}'; rp=root/'raw'/f'{tag}.json'; pp=root/'raw'/f'{tag}.provenance.json'; rp.parent.mkdir(parents=True,exist_ok=True); rp.write_bytes(body); pp.write_bytes(canon(prov))
     files.append({'path':str(rp.relative_to(root)),'sha256':sha(body),'provenance_path':str(pp.relative_to(root)),'provenance_sha256':sha(pp.read_bytes())})
     xs=[x for x in json.loads(body)['result']['list'] if int(x[0])==t]
     if len(xs)!=1: raise RuntimeError(f'BLOCK boundary row {symbol} {surface} {t}: {len(xs)}')
     x=xs[0]; extra=(x[5],x[6]) if surface=='tradeable' else ('',''); w.writerow([symbol,surface,t,x[1],x[2],x[3],x[4],extra[0],extra[1],prov['raw_sha256']])
 (root/'manifest.json').write_bytes(canon({'contract':'CP2-v1/T400-boundary-v1','required_times_ms':TIMES,'files':files}))

def verify(root):
 root=Path(root); m=json.loads((root/'manifest.json').read_text())
 for x in m['files']:
  if sha((root/x['path']).read_bytes())!=x['sha256'] or sha((root/x['provenance_path']).read_bytes())!=x['provenance_sha256']: raise RuntimeError('BLOCK SHA mismatch')
 for symbol in SYMBOLS:
  for surface in SURFACES:
   rows=list(csv.DictReader((root/'normalized'/f'{symbol}.{surface}.csv').open(encoding='utf-8'))); got={int(r['start_ms']) for r in rows}
   if got!=set(TIMES): raise RuntimeError(f'BLOCK normalized boundary mismatch {symbol} {surface}: {got}')
 print('PASS T400 boundary integrity')
if __name__=='__main__':
 import argparse; p=argparse.ArgumentParser(); p.add_argument('cmd',choices=['acquire','verify']); p.add_argument('--out',required=True); a=p.parse_args(); (acquire if a.cmd=='acquire' else verify)(a.out)
