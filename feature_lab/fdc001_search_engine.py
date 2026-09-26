"""Execution-aware random symbolic search engine for the first real FDC pilot.

Real search is allowed only with a frozen manifest and D0-only artifact.
This file also contains a synthetic integration self-test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from dsl import evaluate, expression_hash, normalized_ast, validate
from manifest import validate_manifest
from search_ledger import write_jsonl

FIELDS=["ret1","gap1","intraday","range1","volume_chg1"]
FIELD_DIMS={k:"dimensionless" for k in FIELDS}
LAGS=[1,2,3,5,10,20,60]
WINDOWS=[2,3,5,10,20,60]


def complexity(ast):
    if ast.get("type")=="field":
        return 1
    return 1+sum(complexity(a) for a in ast.get("args",[]))


def median(xs):
    s=sorted(xs)
    n=len(s)
    if not n:
        return float("nan")
    return s[n//2] if n%2 else 0.5*(s[n//2-1]+s[n//2])


def build_terminals(df):
    c=df["Close"].astype(float)
    o=df["Open"].astype(float)
    h=df["High"].astype(float)
    l=df["Low"].astype(float)
    v=df["Volume"].astype(float)
    data={
      "ret1":(c/c.shift(1)-1.0).tolist(),
      "gap1":(o/c.shift(1)-1.0).tolist(),
      "intraday":(c/o-1.0).tolist(),
      "range1":(h/l-1.0).tolist(),
      "volume_chg1":(v/v.shift(1)-1.0).replace([float("inf"),float("-inf")],float("nan")).tolist(),
    }
    return {k:[float("nan") if pd.isna(x) else float(x) for x in vals] for k,vals in data.items()}


def leaf(r):
    f={"type":"field","name":r.choice(FIELDS)}
    if r.random()<0.55:
        return f
    return {"type":"op","op":"lag","args":[f],"params":{"n":r.choice(LAGS)}}


def random_ast(r,depth=0,max_gen_depth=4):
    if depth>=max_gen_depth or r.random()<0.34:
        return leaf(r)
    c=r.randrange(9)
    a=random_ast(r,depth+1,max_gen_depth)
    if c==0:
        return {"type":"op","op":"sign","args":[a],"params":{}}
    if c==1:
        return {"type":"op","op":"abs","args":[a],"params":{}}
    if c==2:
        return {"type":"op","op":"rolling_mean","args":[a],"params":{"window":r.choice(WINDOWS)}}
    if c==3:
        return {"type":"op","op":"rolling_std","args":[a],"params":{"window":r.choice(WINDOWS)}}
    if c==4:
        return {"type":"op","op":"zscore","args":[a],"params":{"window":r.choice([5,10,20,60])}}
    b=random_ast(r,depth+1,max_gen_depth)
    if c==5:
        return {"type":"op","op":"add","args":[a,b],"params":{}}
    if c==6:
        return {"type":"op","op":"sub","args":[a,b],"params":{}}
    if c==7:
        return {"type":"op","op":"mul","args":[a,b],"params":{}}
    return {"type":"op","op":"protected_div","args":[a,b],"params":{}}


def future_open_returns(df):
    o=df["Open"].astype(float).tolist()
    out=[None]*len(o)
    for t in range(len(o)-2):
        if o[t+1]>0:
            out[t]=o[t+2]/o[t+1]-1.0
    return out


def circular_shift_returns(ret,k):
    idx=[i for i,x in enumerate(ret) if x is not None and math.isfinite(x)]
    vals=[ret[i] for i in idx]
    if not vals:
        return list(ret)
    k%=len(vals)
    shifted=vals[-k:]+vals[:-k] if k else vals
    out=list(ret)
    for i,x in zip(idx,shifted):
        out[i]=x
    return out


def fold_metrics(score,df,ret,fold,one_way_cost,minimum_n,turnover_cap):
    dates=pd.to_datetime(df["Date"]).tolist()
    start=pd.Timestamp(fold["validation"]["start"])
    end=pd.Timestamp(fold["validation"]["end"])
    selected=[]
    for t in range(len(df)-2):
        entry_date=pd.Timestamp(dates[t+1])
        exit_date=pd.Timestamp(dates[t+2])
        if entry_date>=start and exit_date<end and ret[t] is not None and math.isfinite(ret[t]):
            selected.append(t)
    if not selected:
        return {"n":0,"structural_pass":False}

    positions=[]
    finite=0
    for t in selected:
        x=score[t]
        ok=x is not None and math.isfinite(x)
        finite+=int(ok)
        positions.append(1 if ok and x>0 else 0)

    strat=[]
    base=[]
    prev=0
    changes=0
    for j,(t,p) in enumerate(zip(selected,positions)):
        ch=abs(p-prev)
        changes+=ch
        strat.append(p*ret[t]-one_way_cost*ch)
        base.append(ret[t])
        prev=p
    if positions and positions[-1]==1:
        strat[-1]-=one_way_cost
        changes+=1
    # Independent fold baseline begins and ends invested once.
    base[0]-=one_way_cost
    base[-1]-=one_way_cost

    inc=[a-b for a,b in zip(strat,base)]
    n=len(selected)
    long_fraction=sum(positions)/n
    coverage=finite/n
    changes_per_year=changes/n*252.0
    mstrat=sum(strat)/n
    minc=sum(inc)/n
    structural=(
      n>=minimum_n and coverage>=0.90 and
      0.10<=long_fraction<=0.90 and
      changes_per_year<=turnover_cap
    )
    return {
      "n":n,
      "coverage":coverage,
      "long_fraction":long_fraction,
      "cash_fraction":1.0-long_fraction,
      "state_changes":changes,
      "state_changes_per_252":changes_per_year,
      "strategy_mean_net":mstrat,
      "incremental_mean_vs_always_long":minc,
      "structural_pass":structural,
    }


def candidate_summary(ast,df,data,ret,folds,cfg):
    v=validate(ast,FIELD_DIMS,max_depth=int(cfg["max_ast_depth"]))
    comp=complexity(ast)
    if not v["valid"] or comp>int(cfg["max_complexity"]):
        return {"valid":False,"reason":v["reason"] or "complexity","complexity":comp}
    score=evaluate(ast,data)
    fm=[fold_metrics(score,df,ret,f,float(cfg["cost_model"]["discovery_conservative_one_way"]),int(cfg["minimum_n"]),float(cfg["turnover_cap"])) for f in folds]
    structural=all(x.get("structural_pass",False) for x in fm)
    pos_strat=sum(x.get("strategy_mean_net",0)>0 for x in fm)
    pos_inc=sum(x.get("incremental_mean_vs_always_long",0)>0 for x in fm)
    incs=[x.get("incremental_mean_vs_always_long",float("-inf")) for x in fm]
    strats=[x.get("strategy_mean_net",float("-inf")) for x in fm]
    turns=[x.get("state_changes_per_252",float("inf")) for x in fm]
    eligible=structural and pos_strat>=3 and pos_inc>=3 and median(incs)>0
    return {
      "valid":True,"reason":None,"complexity":comp,"folds":fm,
      "positive_strategy_folds":pos_strat,
      "positive_incremental_folds":pos_inc,
      "median_incremental":median(incs),
      "min_incremental":min(incs),
      "median_strategy":median(strats),
      "median_state_changes_per_252":median(turns),
      "eligible":eligible,
    }


def rank_key(summary,h):
    return (
      summary["positive_incremental_folds"],
      summary["median_incremental"],
      summary["min_incremental"],
      summary["median_strategy"],
      -summary["median_state_changes_per_252"],
      -summary["complexity"],
      # deterministic final tie-break: prefer lexically smaller hash
      "".join(chr(255-ord(c)) for c in h)
    )


def search(df,cfg,budget,seed,ledger_path=None):
    data=build_terminals(df)
    real_ret=future_open_returns(df)
    null_ret=circular_shift_returns(real_ret,int(cfg["null_control"]["circular_shift_observations"]))
    folds=cfg["d1_walk_forward_folds"]
    r=random.Random(seed)
    cache={}
    rows=[]
    best_real=None
    best_null=None
    now=datetime.now(timezone.utc).isoformat()

    for i in range(budget):
        ast=random_ast(r)
        h=expression_hash(ast)
        if h not in cache:
            actual=candidate_summary(ast,df,data,real_ret,folds,cfg)
            null=candidate_summary(ast,df,data,null_ret,folds,cfg) if actual["valid"] else {"valid":False,"reason":actual.get("reason"),"complexity":actual.get("complexity")}
            cache[h]=(normalized_ast(ast),actual,null)
        norm,actual,null=cache[h]

        if actual.get("eligible"):
            key=rank_key(actual,h)
            if best_real is None or key>best_real[0]:
                best_real=(key,h,norm,actual,i)
        if null.get("eligible"):
            key=rank_key(null,h)
            if best_null is None or key>best_null[0]:
                best_null=(key,h,norm,null,i)

        rows.append({
          "fdc_id":cfg["fdc_id"],"evaluation_index":i,"expression_hash":h,
          "normalized_ast":norm,"generator":"G0_RANDOM","parent_hashes":[],
          "random_seed":seed,"valid":bool(actual.get("valid")),"invalid_reason":actual.get("reason"),
          "complexity":actual.get("complexity"),"discovery_fold_summary":actual,
          "turnover_summary":{"median_state_changes_per_252":actual.get("median_state_changes_per_252")},
          "cost_summary":{"discovery_conservative_one_way":cfg["cost_model"]["discovery_conservative_one_way"]},
          "redundancy_cluster":h[:16],"selected_as_champion":False,"evaluated_at_utc":now
        })

    champion=None
    if best_real:
        _,h,norm,summary,idx=best_real
        rows[idx]["selected_as_champion"]=True
        champion={"expression_hash":h,"normalized_ast":norm,"discovery_summary":summary,"evaluation_index":idx}
    null_champion=None
    if best_null:
        _,h,norm,summary,idx=best_null
        null_champion={"expression_hash":h,"normalized_ast":norm,"null_summary":summary,"evaluation_index":idx}

    if ledger_path:
        write_jsonl(rows,ledger_path)

    return {
      "raw_evaluations":budget,
      "unique_expression_hashes":len(cache),
      "valid_unique_expressions":sum(1 for _,a,_ in cache.values() if a.get("valid")),
      "eligible_unique_expressions":sum(1 for _,a,_ in cache.values() if a.get("eligible")),
      "null_eligible_unique_expressions":sum(1 for _,_,n in cache.values() if n.get("eligible")),
      "champion":champion,
      "null_champion":null_champion,
      "d2_loaded":False,
      "d3_loaded":False,
    }


def load_real(manifest_path,raw_path):
    cfg=json.loads(Path(manifest_path).read_text())
    validate_manifest(cfg,require_frozen_hash=True)
    raw=Path(raw_path).read_bytes()
    expected=cfg["data_manifest_refs"]["d0"]["sha256"]
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise SystemExit("D0 raw SHA mismatch")
    df=pd.read_csv(raw_path)
    df["Date"]=pd.to_datetime(df["Date"],errors="raise")
    if not df["Date"].is_monotonic_increasing or not df["Date"].is_unique:
        raise SystemExit("D0 date integrity failure")
    return cfg,df


def synthetic_frame():
    r=random.Random(991)
    dates=pd.bdate_range("2005-01-03","2016-12-30")
    n=len(dates)
    sig=[0.008]\n    for _ in range(1,n):\n        sig.append(sig[-1] if r.random()<0.85 else -sig[-1])
    close=[100.0]
    for i in range(1,n):
        close.append(close[-1]*(1+sig[i]))
    op=[100.0,100.0]
    for t in range(n-2):
        rr=(0.0025 if sig[t]>0 else -0.0015)+r.gauss(0,0.0008)
        op.append(op[-1]*(1+rr))
    high=[max(a,b)*1.001 for a,b in zip(op,close)]
    low=[min(a,b)*0.999 for a,b in zip(op,close)]
    vol=[1_000_000+r.randrange(100_000) for _ in range(n)]
    return pd.DataFrame({"Date":dates,"Open":op,"High":high,"Low":low,"Close":close,"Adj Close":close,"Volume":vol})


def selftest():
    df=synthetic_frame()
    cfg={
      "fdc_id":"FDC000","max_ast_depth":6,"max_complexity":15,"minimum_n":350,"turnover_cap":80,
      "cost_model":{"discovery_conservative_one_way":0.0001},
      "null_control":{"circular_shift_observations":503},
      "d1_walk_forward_folds":[
        {"train":{"start":"2005-01-01","end":"2007-01-01"},"validation":{"start":"2007-01-01","end":"2009-01-01"}},
        {"train":{"start":"2005-01-01","end":"2009-01-01"},"validation":{"start":"2009-01-01","end":"2011-01-01"}},
        {"train":{"start":"2005-01-01","end":"2011-01-01"},"validation":{"start":"2011-01-01","end":"2013-01-01"}},
        {"train":{"start":"2005-01-01","end":"2013-01-01"},"validation":{"start":"2013-01-01","end":"2015-01-01"}},
        {"train":{"start":"2005-01-01","end":"2015-01-01"},"validation":{"start":"2015-01-01","end":"2017-01-01"}}
      ]
    }
    known={"type":"field","name":"ret1"}
    s=candidate_summary(known,df,build_terminals(df),future_open_returns(df),cfg["d1_walk_forward_folds"],cfg)
    if not s["eligible"]:
        raise SystemExit("known synthetic signal did not pass execution-aware gates")
    a=search(df,cfg,budget=500,seed=20260926)
    b=search(df,cfg,budget=500,seed=20260926)
    stable=lambda x:json.dumps(x,sort_keys=True,separators=(",",":"))
    if stable(a)!=stable(b):
        raise SystemExit("search not deterministic")
    if a["champion"] is None:
        raise SystemExit("synthetic search found no eligible champion")
    print(json.dumps({
      "fd_stage":"FD4_ENGINE_SYNTHETIC_PROOF","status":"PASS",
      "real_market_data_loaded":False,"real_market_performance_inspected":False,
      "known_signal_eligible":True,"search_champion_found":True,
      "unique_expressions":a["unique_expression_hashes"]
    },sort_keys=True))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--selftest",action="store_true")
    ap.add_argument("--manifest")
    ap.add_argument("--raw")
    ap.add_argument("--out-prefix",default="fdc001")
    args=ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.manifest or not args.raw:
        raise SystemExit("--manifest and --raw required")
    cfg,df=load_real(args.manifest,args.raw)
    budget=int(cfg["evaluation_budget_by_generator"]["G0_RANDOM"])
    seed=int(cfg["random_seeds"]["G0_RANDOM"])
    ledger_path=f"{args.out_prefix}_search_ledger.jsonl"
    result=search(df,cfg,budget,seed,ledger_path)
    result.update({
      "fdc_id":cfg["fdc_id"],"manifest_sha256":cfg["manifest_sha256"],
      "d0_raw_sha256":cfg["data_manifest_refs"]["d0"]["sha256"],
      "generator":"G0_RANDOM","performance_scope":"D0_D1_CONTAMINATED_DISCOVERY_ONLY"
    })
    Path(f"{args.out_prefix}_search_summary.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    if result["champion"] is not None:
        Path(f"{args.out_prefix}_champion.json").write_text(json.dumps(result["champion"],indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:result[k] for k in ["fdc_id","raw_evaluations","unique_expression_hashes","valid_unique_expressions","eligible_unique_expressions","null_eligible_unique_expressions","champion","d2_loaded","d3_loaded"]},sort_keys=True))


if __name__=="__main__":
    main()
