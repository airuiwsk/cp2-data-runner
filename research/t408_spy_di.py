from pathlib import Path
import hashlib,json
from datetime import datetime,timezone
import yfinance as yf
out=Path('evidence/t408-spy-di');out.mkdir(parents=True,exist_ok=True)
df=yf.download('SPY',start='2007-01-01',end='2024-01-01',auto_adjust=False,actions=False,progress=False,threads=False)
raw=df.to_csv().encode();(out/'spy_yahoo_raw.csv').write_bytes(raw)
cols=[str(c) for c in df.columns]; idx=df.index
unique=idx.is_unique; ascending=idx.is_monotonic_increasing
has_fields=all(any(name in c for c in cols) for name in ['Close','Open','High','Low','Volume'])
null_close=int(df['Close'].isna().sum().iloc[0]) if len(df) else -1
coverage=len(df)>4000 and str(idx.min())[:10]<='2007-01-03' and str(idx.max())[:10]>='2023-12-29'
summary={'trial_id':'T408','performance_computed':False,'provider':'Yahoo via yfinance','retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'rows':len(df),'columns':cols,'date_min':str(idx.min()) if len(df) else None,'date_max':str(idx.max()) if len(df) else None,'unique_dates':bool(unique),'ascending_dates':bool(ascending),'null_close':null_close,'raw_sha256':hashlib.sha256(raw).hexdigest(),'coverage_ok':coverage,'required_fields_present':has_fields,'di_pass':bool(len(df) and unique and ascending and has_fields and null_close==0 and coverage)}
(out/'di_summary.json').write_text(json.dumps(summary,indent=2));(out/'raw.sha256').write_text(summary['raw_sha256']+'  spy_yahoo_raw.csv\n')
print(json.dumps(summary,indent=2))
if not summary['di_pass']: raise SystemExit(2)
