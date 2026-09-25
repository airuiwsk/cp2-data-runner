import json,hashlib,datetime as dt
import yfinance as yf
p=yf.download("SPY",start="1993-01-01",end="2026-09-25",auto_adjust=False,actions=False,progress=False)
out={"ticker":"SPY","rows":int(len(p)),"start":str(p.index.min().date()) if len(p) else None,"end":str(p.index.max().date()) if len(p) else None,"columns":[str(x) for x in p.columns],"performance_computed":False,"retrieved_at_utc":dt.datetime.now(dt.timezone.utc).isoformat()}
raw=p.to_csv().encode();out["raw_sha256"]=hashlib.sha256(raw).hexdigest();open("spy_1993_2026_raw.csv","wb").write(raw);open("spy_1993_2026_preflight.json","w").write(json.dumps(out,indent=2));print(json.dumps(out))
