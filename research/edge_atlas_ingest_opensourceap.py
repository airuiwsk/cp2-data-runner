#!/usr/bin/env python3
import csv, io, json, os, re, hashlib, urllib.request
from collections import Counter

SOURCE_URL="https://raw.githubusercontent.com/OpenSourceAP/CrossSection/master/SignalDoc.csv"
OUTDIR="out/edge-atlas-opensourceap"

def clean(s):
    return (s or "").strip()

def num(s):
    s=clean(s)
    if not s: return None
    try: return float(s)
    except: return None

def safe_id(s):
    return re.sub(r"[^A-Za-z0-9_-]+","_",s).strip("_").upper()

def mechanism(row):
    econ=clean(row.get("Cat.Economic"))
    data=clean(row.get("Cat.Data"))
    if econ: return econ.lower().replace(" ","_")
    if data: return data.lower().replace(" ","_")
    return "unknown"

def evidence_status(row):
    q=clean(row.get("Signal Rep Quality")).lower()
    pred=clean(row.get("Predictability in OP")).lower()
    if "lack_data" in q: return "UNKNOWN"
    if "good" in q and "clear" in pred: return "REPLICATED"
    if "fair" in q: return "MIXED"
    return "CLAIMED"

def main():
    os.makedirs(OUTDIR,exist_ok=True)
    with urllib.request.urlopen(SOURCE_URL,timeout=60) as r:
        raw=r.read()
    open(f"{OUTDIR}/SignalDoc.csv","wb").write(raw)
    source_sha=hashlib.sha256(raw).hexdigest()
    text=raw.decode("utf-8-sig")
    rows=list(csv.DictReader(io.StringIO(text)))
    records=[]
    for row in rows:
        acr=clean(row.get("Acronym"))
        if not acr: continue
        cat_data=clean(row.get("Cat.Data"))
        cat_econ=clean(row.get("Cat.Economic"))
        aliases=[x for x in [clean(row.get("Acronym2"))] if x and x!=acr]
        pp=num(row.get("Portfolio Period"))
        sign=num(row.get("Sign"))
        hold=(f"{pp:g} months" if pp is not None else None)
        direction=("higher_signal_long" if sign and sign>0 else "higher_signal_short" if sign and sign<0 else None)
        rec={
            "atlas_id":f"EA-OSAP-{safe_id(acr)}",
            "canonical_name":clean(row.get("LongDescription")) or acr,
            "aliases":aliases,
            "source_type":"REPLICATION_LIBRARY",
            "source_refs":[{
                "database":"OpenSourceAP/CrossSection SignalDoc.csv",
                "source_url":SOURCE_URL,
                "source_sha256":source_sha,
                "acronym":acr,
                "authors":clean(row.get("Authors")),
                "year":clean(row.get("Year")),
                "journal":clean(row.get("Journal"))
            }],
            "asset_classes":["EQUITY"],
            "instruments":["STOCK"],
            "geographies":["US"],
            "mechanism_family":mechanism(row),
            "persistence_reason":None,
            "signal_family":cat_econ or cat_data or "unknown",
            "input_domains":[cat_data] if cat_data else [],
            "formation_horizon":None,
            "holding_horizon":hold,
            "rebalance_frequency":hold,
            "directionality":direction,
            "latency_class":"LOW_FREQUENCY",
            "evidence_status":evidence_status(row),
            "original_evidence":{
                "sample_start_year":clean(row.get("SampleStartYear")) or None,
                "sample_end_year":clean(row.get("SampleEndYear")) or None,
                "evidence_summary":clean(row.get("Evidence Summary")) or None,
                "test":clean(row.get("Test in OP")) or None,
                "reported_return":num(row.get("Return")),
                "reported_t_stat":num(row.get("T-Stat")),
                "stock_weight":clean(row.get("Stock Weight")) or None,
                "replication_quality_metadata":clean(row.get("Signal Rep Quality")) or None,
                "predictability_metadata":clean(row.get("Predictability in OP")) or None,
                "detailed_definition":clean(row.get("Detailed Definition")) or None,
                "notes":clean(row.get("Notes")) or None
            },
            "replication_evidence":[],
            "post_publication_evidence":[],
            "cost_sensitivity":None,
            "turnover_class":None,
            "capacity_class":None,
            "tail_risk_class":None,
            "data_accessibility":None,
            "retail_accessibility":None,
            "small_capital_fit":None,
            "execution_complexity":None,
            "equivalence_cluster":f"OSAP-{safe_id(cat_econ or cat_data or 'UNKNOWN')}",
            "canonical_family_id":None,
            "parent_atlas_ids":[],
            "contradictions":[],
            "knowledge_refs":[],
            "lesson_refs":[],
            "unknown_fields":["persistence_reason","cost_sensitivity","capacity_class","retail_accessibility","small_capital_fit"],
            "evidence_grade":None,
            "deployability_grade":None,
            "small_capital_grade":None,
            "whitespace_score":None,
            "priority_score":None,
            "priority_reason":None,
            "internal_status":"UNREVIEWED",
            "internal_trials":[]
        }
        records.append(rec)
    records.sort(key=lambda x:x["atlas_id"])
    with open(f"{OUTDIR}/atlas.jsonl","w",encoding="utf-8") as f:
        for r in records: f.write(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n")
    summary={
        "source_url":SOURCE_URL,
        "source_sha256":source_sha,
        "record_count":len(records),
        "evidence_status_counts":Counter(x["evidence_status"] for x in records),
        "input_domain_counts":Counter((x["input_domains"] or ["UNKNOWN"])[0] for x in records),
        "mechanism_family_counts":Counter(x["mechanism_family"] for x in records),
        "performance_statistics_recomputed":False,
        "note":"Metadata normalization only; no Method X candidate performance computed."
    }
    open(f"{OUTDIR}/summary.json","w").write(json.dumps(summary,ensure_ascii=False,indent=2,default=dict))
    manifest={}
    for fn in ["SignalDoc.csv","atlas.jsonl","summary.json"]:
        b=open(f"{OUTDIR}/{fn}","rb").read()
        manifest[fn]={"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)}
    open(f"{OUTDIR}/manifest.json","w").write(json.dumps(manifest,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2,default=dict))

if __name__=="__main__": main()
