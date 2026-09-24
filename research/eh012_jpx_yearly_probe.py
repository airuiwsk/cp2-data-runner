#!/usr/bin/env python3
"""EH-012 JPX annual quotations non-performance source probe.

Discovers public annual Index Futures quotation files for 2023-2025 and checks
whether Nikkei 225 micro (N225MC) appears with sufficient date rows.
NO return/performance statistic is computed.
"""
import json, hashlib, re, urllib.parse
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import pandas as pd

OUT=Path("out/eh012-jpx-probe"); OUT.mkdir(parents=True,exist_ok=True)
URL="https://www.jpx.co.jp/markets/statistics-derivatives/yearly-price/"
html=requests.get(URL,timeout=30).content
(OUT/"yearly-price.html").write_bytes(html)
soup=BeautifulSoup(html,"html.parser")

links=[]
for a in soup.find_all("a",href=True):
    href=urllib.parse.urljoin(URL,a["href"])
    txt=" ".join(a.stripped_strings)
    blob=(txt+" "+href).lower()
    if any(y in blob for y in ("2023","2024","2025")) and any(k in blob for k in ("index","sif","future","指数","xlsx","xls")):
        links.append({"text":txt,"url":href})
# dedupe
seen=set(); links=[x for x in links if not (x["url"] in seen or seen.add(x["url"]))]

files=[]
for i,x in enumerate(links):
    if not re.search(r"\.(xlsx?|csv)(\?|$)",x["url"],re.I):
        continue
    b=requests.get(x["url"],timeout=60).content
    fn=f"source_{i}_"+x["url"].split("/")[-1].split("?")[0]
    (OUT/fn).write_bytes(b)
    rec={"label":x["text"],"url":x["url"],"file":fn,"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b),"sheets":[]}
    if fn.lower().endswith((".xls",".xlsx")):
        try:
            xl=pd.ExcelFile(OUT/fn)
            for s in xl.sheet_names:
                df=pd.read_excel(OUT/fn,sheet_name=s,header=None,dtype=str)
                # metadata only: count rows/cells containing Nikkei micro labels/codes
                mask=df.apply(lambda col: col.fillna("").str.contains(r"N225MC|225MC|日経225.*マイクロ|Nikkei 225 Micro",case=False,regex=True))
                hits=int(mask.to_numpy().sum())
                rec["sheets"].append({"sheet":s,"rows":int(len(df)),"cols":int(len(df.columns)),"nikkei_micro_label_hits":hits})
        except Exception as e:
            rec["parse_error"]=repr(e)
    files.append(rec)

meta={
 "source_page":URL,
 "source_page_sha256":hashlib.sha256(html).hexdigest(),
 "discovered_candidate_links":links,
 "downloaded_files":files,
 "performance_statistics_computed":False,
 "forbidden":["returns","mean_return","sharpe","hit_rate","cumulative_return","t_stat","price_change"],
}
(OUT/"probe.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(meta,ensure_ascii=False,indent=2))
