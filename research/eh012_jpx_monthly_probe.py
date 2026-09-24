#!/usr/bin/env python3
"""EH-012 JPX monthly quotations non-performance source probe.

Discovers public Monthly Quotations archive pages/files and checks N225MC
coverage metadata. Does not compute price changes or returns.
"""
import json, hashlib, re, urllib.parse, collections
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import pandas as pd

OUT=Path("out/eh012-jpx-monthly-probe"); OUT.mkdir(parents=True,exist_ok=True)
ROOT="https://www.jpx.co.jp"
START="https://www.jpx.co.jp/markets/statistics-derivatives/monthly-quotations/"
session=requests.Session()

queue=collections.deque([START])
seen_pages=set(); file_urls=set(); page_meta=[]
while queue and len(seen_pages)<40:
    url=queue.popleft()
    if url in seen_pages: continue
    seen_pages.add(url)
    r=session.get(url,timeout=30); r.raise_for_status()
    b=r.content
    page_meta.append({"url":url,"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)})
    soup=BeautifulSoup(b,"html.parser")
    for a in soup.find_all("a",href=True):
        href=urllib.parse.urljoin(url,a["href"])
        low=href.lower()
        if "/markets/statistics-derivatives/monthly-quotations/" in low and low.endswith((".html","/")):
            if href not in seen_pages: queue.append(href)
        if re.search(r"\.xlsx?(\?|$)",low) and ("sif" in low or "monthly-quotations" in low):
            file_urls.add(href)

# Keep plausible 2023-2026 index-future monthly files; download all SIF links if filename opaque.
selected=[]
for u in sorted(file_urls):
    low=u.lower()
    if any(y in low for y in ("2023","2024","2025","2026")) or "sif" in low:
        selected.append(u)

files=[]
for i,u in enumerate(selected):
    b=session.get(u,timeout=60).content
    fn=f"source_{i}_"+u.split("/")[-1].split("?")[0]
    (OUT/fn).write_bytes(b)
    rec={"url":u,"file":fn,"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b),"sheets":[]}
    try:
        xl=pd.ExcelFile(OUT/fn)
        for s in xl.sheet_names:
            df=pd.read_excel(OUT/fn,sheet_name=s,header=None,dtype=str)
            mask=df.apply(lambda col: col.fillna("").str.contains(r"N225MC|225MC|日経225.*マイクロ|Nikkei 225 Micro",case=False,regex=True))
            hits=int(mask.to_numpy().sum())
            rec["sheets"].append({"sheet":s,"rows":int(len(df)),"cols":int(len(df.columns)),"nikkei_micro_label_hits":hits})
    except Exception as e:
        rec["parse_error"]=repr(e)
    files.append(rec)

meta={
 "start_page":START,
 "pages_scanned":page_meta,
 "discovered_excel_count":len(file_urls),
 "selected_download_count":len(selected),
 "downloaded_files":files,
 "files_with_n225mc":sum(any(s.get("nikkei_micro_label_hits",0)>0 for s in f.get("sheets",[])) for f in files),
 "performance_statistics_computed":False,
 "forbidden":["returns","price_change","mean_return","sharpe","hit_rate","t_stat"]
}
(OUT/"probe.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(meta,ensure_ascii=False,indent=2))
