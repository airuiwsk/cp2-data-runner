from pathlib import Path
import csv, hashlib, io, json, urllib.request
from datetime import datetime, timezone

URL='https://stooq.com/q/d/l/?s=spy.us&i=d&d1=20070101&d2=20231231'
out=Path('evidence/t407-spy-di'); out.mkdir(parents=True,exist_ok=True)
req=urllib.request.Request(URL,headers={'User-Agent':'Mozilla/5.0 MethodX-DI/1.0'})
with urllib.request.urlopen(req,timeout=60) as r:
    raw=r.read(); status=r.status; ctype=r.headers.get('Content-Type','')
(out/'spy_us_daily_raw.csv').write_bytes(raw)
sha=hashlib.sha256(raw).hexdigest()
text=raw.decode('utf-8-sig')
rows=list(csv.DictReader(io.StringIO(text)))
required=['Date','Open','High','Low','Close','Volume']
fields=list(rows[0].keys()) if rows else []
dates=[]; numeric_ok=True
for row in rows:
    try:
        d=datetime.strptime(row['Date'],'%Y-%m-%d').date(); dates.append(d)
        for k in ['Open','High','Low','Close','Volume']: float(row[k])
    except Exception:
        numeric_ok=False
unique=len(set(dates))==len(dates)
ascending=all(a<b for a,b in zip(dates,dates[1:]))
coverage=bool(dates) and dates[0].isoformat()<='2007-01-03' and dates[-1].isoformat()>='2023-12-28'
# Non-performance monthly shape only: dates/counts, never prices/returns/signals.
month_keys={(d.year,d.month) for d in dates}
expected_months=(2023-2007+1)*12
summary={
 'trial_id':'T407','performance_computed':False,'url':URL,'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),
 'http_status':status,'content_type':ctype,'raw_sha256':sha,'raw_bytes':len(raw),'rows':len(rows),
 'fields':fields,'required_fields_present':all(x in fields for x in required),'date_min':dates[0].isoformat() if dates else None,
 'date_max':dates[-1].isoformat() if dates else None,'unique_dates':unique,'strictly_ascending_dates':ascending,
 'numeric_parse_ok':numeric_ok,'calendar_months_present':len(month_keys),'expected_calendar_month_span':expected_months,
 'coverage_ok':coverage,'di_pass': bool(rows) and all(x in fields for x in required) and unique and ascending and numeric_ok and coverage
}
(out/'di_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
(out/'raw.sha256').write_text(sha+'  spy_us_daily_raw.csv\n',encoding='utf-8')
print(json.dumps(summary,indent=2))
if not summary['di_pass']: raise SystemExit(2)
