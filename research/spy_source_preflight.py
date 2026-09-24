from pathlib import Path
import json, hashlib
from datetime import datetime, timezone
import yfinance as yf
out=Path('evidence/spy-source-preflight'); out.mkdir(parents=True,exist_ok=True)
# Non-performance source-access probe only. Do not calculate returns/signals.
df=yf.download('SPY',start='2007-01-01',end='2024-01-01',auto_adjust=False,actions=False,progress=False,threads=False)
csv=df.to_csv().encode()
(out/'raw.csv').write_bytes(csv)
summary={'performance_computed':False,'provider':'yfinance/Yahoo chart backend','retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'rows':len(df),'columns':[str(c) for c in df.columns],'date_min':str(df.index.min()) if len(df) else None,'date_max':str(df.index.max()) if len(df) else None,'sha256':hashlib.sha256(csv).hexdigest(),'usable':len(df)>4000 and not df.empty}
(out/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
if not summary['usable']: raise SystemExit(2)
