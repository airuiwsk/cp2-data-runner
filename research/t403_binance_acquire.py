#!/usr/bin/env python3
"""T403 data-only acquisition. No spread/return/performance computation."""
from pathlib import Path
import hashlib, json, urllib.request

BASE='https://data.binance.vision/data/futures/um/monthly/klines'
OUT=Path('out/t403-binance'); OUT.mkdir(parents=True, exist_ok=True)
SYMS=['BTCUSDT','ETHUSDT']; YEARS=[2024,2025]

def get(url, path):
    with urllib.request.urlopen(url, timeout=120) as r: data=r.read()
    path.write_bytes(data); return hashlib.sha256(data).hexdigest()

records=[]
for sym in SYMS:
  for y in YEARS:
    for m in range(1,13):
      fn=f'{sym}-1m-{y}-{m:02d}.zip'; url=f'{BASE}/{sym}/1m/{fn}'
      zp=OUT/fn; cp=OUT/(fn+'.CHECKSUM')
      zsha=get(url,zp); get(url+'.CHECKSUM',cp)
      expected=cp.read_text().strip().split()[0].lower()
      if zsha.lower()!=expected: raise SystemExit(f'CHECKSUM FAIL {fn}: {zsha} != {expected}')
      records.append({'symbol':sym,'year':y,'month':m,'url':url,'file':fn,'sha256':zsha,'official_checksum':expected,'checksum_ok':True})
manifest={'trial_id':'T403','purpose':'data_acquisition_only','performance_computed':False,'source':'Binance Public Data USD-M monthly klines','interval':'1m','records':records}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'files':len(records),'all_checksums_ok':all(x['checksum_ok'] for x in records),'performance_computed':False}))
