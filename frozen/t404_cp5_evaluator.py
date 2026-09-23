#!/usr/bin/env python3
"""Frozen CP5 evaluator for T404 / EH-20260924-008 v1.

Implements research/t404-cp5-validation-plan-v1.md plus
research/t404-cp5-implementation-spec-v1.md.

Governance:
- 2026 OOS performance must not be inspected before this file is frozen.
- E1->E8 are evaluated sequentially.
- On first decisive failure, later gates are not computed.
- Do not edit constants or logic after first OOS performance execution.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

SYMBOLS=("BTCUSDT","ETHUSDT")
FAMILY="AEDE-PERP-TIMESERIES-MOMENTUM"
FIRST_ENTRY=datetime(2026,1,5,0,0,tzinfo=timezone.utc)
LAST_ENTRY=datetime(2026,8,24,0,0,tzinfo=timezone.utc)
WEEK=timedelta(days=7)
MINUTE=timedelta(minutes=1)
SCHEDULED_WEEKS=34
MIN_TRADES=30
GROSS_HURDLE=0.0013
TAKER_FEE=0.00055
BASE_SLIPPAGE=0.0002
CONSERVATIVE_SLIPPAGE=0.0010
PSR_MIN=0.95
MAX_DRAWDOWN=0.25
WORST_WEEK_FLOOR=-0.15


def ms(dt: datetime)->int:
    return int(dt.timestamp()*1000)


def sha_file(path: Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def write_and_exit(out: Path, payload: dict, decision: str):
    payload["decision"]=decision
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(decision)
    raise SystemExit(0)


def load_bar_map(path: Path):
    out={}
    with path.open(newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t=int(r["start_ms"])
            if t in out:
                raise RuntimeError(f"BLOCK duplicate normalized bar {path} {t}")
            out[t]={"open":float(r["open"]),"close":float(r["close"])}
    return out


def load_funding(path: Path):
    out=[]
    seen=set()
    with path.open(newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t=int(r["funding_time_ms"])
            if t in seen:
                raise RuntimeError(f"BLOCK duplicate funding {path} {t}")
            seen.add(t)
            out.append((t,float(r["funding_rate"])))
    out.sort()
    return out


def verify_input_root(root: Path):
    manifest_path=root/"input-manifest.json"
    quality_path=root/"quality-report.json"
    if not manifest_path.exists() or not quality_path.exists():
        return False,{"reason":"missing manifest/quality"}
    manifest=json.loads(manifest_path.read_text())
    quality=json.loads(quality_path.read_text())
    errors=[]
    if manifest.get("performance_computed") is not False:
        errors.append("manifest performance_computed != false")
    if quality.get("performance_computed") is not False:
        errors.append("quality performance_computed != false")
    if not quality.get("overall_pass"):
        errors.append("producer quality overall_pass != true")
    for x in manifest.get("raw_files",[]):
        p=root/x["path"]; q=root/x["provenance_path"]
        if not p.exists() or sha_file(p)!=x["sha256"]:
            errors.append(f"raw sha {x['path']}")
        if not q.exists() or sha_file(q)!=x["provenance_sha256"]:
            errors.append(f"prov sha {x['provenance_path']}")
    for x in manifest.get("normalized_files",[]):
        p=root/x["path"]
        if not p.exists() or sha_file(p)!=x["sha256"]:
            errors.append(f"normalized sha {x['path']}")
    if sha_file(quality_path)!=manifest.get("quality_report_sha256"):
        errors.append("quality-report sha")
    return not errors,{"manifest_sha256":sha_file(manifest_path),"quality_report_sha256":sha_file(quality_path),"raw_manifest_entries":len(manifest.get("raw_files",[])),"normalized_files":len(manifest.get("normalized_files",[])),"errors":errors}


def schedule():
    xs=[]; t=FIRST_ENTRY
    while t<=LAST_ENTRY:
        xs.append(t); t+=WEEK
    if len(xs)!=SCHEDULED_WEEKS: raise RuntimeError("internal schedule length mismatch")
    return xs

def mean(xs): return sum(xs)/len(xs) if xs else None
def sample_sd(xs): return statistics.stdev(xs) if len(xs)>=2 else None
def sharpe(xs):
    sd=sample_sd(xs)
    return None if sd is None or sd<=0 else mean(xs)/sd
def normal_cdf(z): return 0.5*(1.0+math.erf(z/math.sqrt(2.0)))
def psr(xs):
    n=len(xs); sr=sharpe(xs)
    if n<3 or sr is None: return None,{}
    mu=mean(xs); centered=[x-mu for x in xs]; m2=mean([x*x for x in centered])
    if m2 is None or m2<=0: return None,{}
    gamma3=mean([x**3 for x in centered])/(m2**1.5); gamma4=mean([x**4 for x in centered])/(m2**2)
    denom2=1.0-gamma3*sr+((gamma4-1.0)/4.0)*(sr**2)
    if denom2<=0: return None,{"sharpe":sr,"skewness":gamma3,"pearson_kurtosis":gamma4,"denominator_squared":denom2}
    z=sr*math.sqrt(n-1)/math.sqrt(denom2)
    return normal_cdf(z),{"n":n,"sharpe":sr,"skewness":gamma3,"pearson_kurtosis":gamma4,"denominator_squared":denom2,"z":z}
def max_drawdown(xs):
    equity=1.0; peak=1.0; mdd=0.0
    for r in xs:
        if r<=-1.0: return 1.0,False
        equity*=1.0+r
        if equity<=0: return 1.0,False
        peak=max(peak,equity); mdd=max(mdd,1.0-equity/peak)
    return mdd,True
def family_count(ledger: Path):
    count=0; ids=[]
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| T"): continue
        parts=[x.strip() for x in line.split("|")]
        if len(parts)>6 and parts[6]==FAMILY: count+=1; ids.append(parts[1])
    return count,ids

def build_symbol(symbol: str, root: Path):
    trade=load_bar_map(root/"normalized"/f"{symbol}.tradeable.csv"); mark=load_bar_map(root/"normalized"/f"{symbol}.mark.csv"); funding=load_funding(root/"normalized"/f"{symbol}.funding.csv")
    weeks=[]; missing=[]
    for entry_dt in schedule():
        formation_start=ms(entry_dt-WEEK); formation_end=ms(entry_dt-MINUTE); entry_t=ms(entry_dt); exit_t=ms(entry_dt+WEEK)
        for label,t in (("formation_start",formation_start),("formation_end",formation_end),("entry",entry_t),("exit",exit_t)):
            if t not in trade: missing.append({"entry_time_ms":entry_t,"field":label,"timestamp_ms":t})
        if any(x["entry_time_ms"]==entry_t for x in missing): continue
        formation_open=trade[formation_start]["open"]; formation_close=trade[formation_end]["close"]; formation_return=formation_close/formation_open-1.0
        entry=trade[entry_t]["open"]; exit_=trade[exit_t]["open"]; raw=exit_/entry-1.0
        if formation_return>0: side="long"; signed_price=raw
        elif formation_return<0: side="short"; signed_price=1.0-exit_/entry
        else: side="flat"; signed_price=0.0
        relevant=[(t,r) for t,r in funding if entry_t<t<=exit_t]; f_long=0.0; f_strategy=0.0; funding_rows=[]
        for ft,rate in relevant:
            if ft not in mark: missing.append({"entry_time_ms":entry_t,"field":"funding_mark","timestamp_ms":ft}); continue
            mark_open=mark[ft]["open"]; normalized_value=mark_open/entry; long_contribution=-normalized_value*rate; f_long+=long_contribution
            if side=="long": f_strategy+=long_contribution
            elif side=="short": f_strategy-=long_contribution
            funding_rows.append({"funding_time_ms":ft,"funding_rate":rate,"mark_open":mark_open,"normalized_position_value":normalized_value})
        exit_ratio=exit_/entry; fees=TAKER_FEE+TAKER_FEE*exit_ratio
        if side=="flat": base_net=0.0; conservative_net=0.0; strategy_fees=0.0; strategy_funding=0.0
        else: strategy_fees=fees; strategy_funding=f_strategy; base_net=signed_price+strategy_funding-strategy_fees-BASE_SLIPPAGE; conservative_net=signed_price+strategy_funding-strategy_fees-CONSERVATIVE_SLIPPAGE
        baseline_net=raw+f_long-fees-BASE_SLIPPAGE
        weeks.append({"entry_time_ms":entry_t,"exit_time_ms":exit_t,"formation_return":formation_return,"side":side,"entry":entry,"exit":exit_,"raw_next_week_return":raw,"signed_gross_return":signed_price,"strategy_funding_contribution":strategy_funding,"exact_taker_fees":strategy_fees,"base_net_return":base_net,"conservative_net_return":conservative_net,"baseline_long_funding_contribution":f_long,"baseline_long_base_net_return":baseline_net,"funding_events":funding_rows})
    return weeks,missing

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",type=Path,required=True); p.add_argument("--trial-ledger",type=Path,required=True); p.add_argument("--out",type=Path,required=True); a=p.parse_args()
    payload={"trial_id":"T404","edge_id":"EH-20260924-008","version":1,"selection_family":FAMILY,"frozen_plan":"research/t404-cp5-validation-plan-v1.md","implementation_spec":"research/t404-cp5-implementation-spec-v1.md","gates":{}}
    input_ok,input_evidence=verify_input_root(a.input); symbol_data={}; missing_all={}
    try:
        for s in SYMBOLS: weeks,missing=build_symbol(s,a.input); symbol_data[s]=weeks; missing_all[s]=missing
    except Exception as e: payload["gates"]["E1"]={"pass":False,"input_evidence":input_evidence,"exception":repr(e)}; write_and_exit(a.out,payload,"REJECT(E-INTEGRITY)")
    e1_pass=input_ok and all(len(symbol_data[s])==SCHEDULED_WEEKS for s in SYMBOLS) and all(not missing_all[s] for s in SYMBOLS)
    payload["gates"]["E1"]={"pass":e1_pass,"input_evidence":input_evidence,"scheduled_weeks":SCHEDULED_WEEKS,"built_weeks":{s:len(symbol_data[s]) for s in SYMBOLS},"missing":missing_all}
    if not e1_pass: write_and_exit(a.out,payload,"REJECT(E-INTEGRITY)")
    e2_symbols={}
    for s in SYMBOLS:
        w=symbol_data[s]; traded=[x for x in w if x["side"]!="flat"]; pos=[x["raw_next_week_return"] for x in traded if x["formation_return"]>0]; neg=[x["raw_next_week_return"] for x in traded if x["formation_return"]<0]; mean_gross=mean([x["signed_gross_return"] for x in traded]); direction=(bool(pos) and bool(neg) and mean(pos)>mean(neg)); ok=len(traded)>=MIN_TRADES and mean_gross is not None and mean_gross>GROSS_HURDLE and direction
        e2_symbols[s]={"traded_episodes":len(traded),"minimum_trades":MIN_TRADES,"mean_signed_gross_return":mean_gross,"gross_hurdle":GROSS_HURDLE,"positive_formation_episodes":len(pos),"negative_formation_episodes":len(neg),"mean_raw_after_positive_formation":mean(pos),"mean_raw_after_negative_formation":mean(neg),"direction_pass":direction,"pass":ok}
    e2=all(x["pass"] for x in e2_symbols.values()); payload["gates"]["E2"]={"pass":e2,"symbols":e2_symbols}
    if not e2: write_and_exit(a.out,payload,"REJECT(E-GROSS)")
    e3_symbols={}
    for s in SYMBOLS:
        traded=[x for x in symbol_data[s] if x["side"]!="flat"]; mb=mean([x["base_net_return"] for x in traded]); mc=mean([x["conservative_net_return"] for x in traded]); mf=mean([x["strategy_funding_contribution"] for x in traded]); ok=mb is not None and mc is not None and mb>0 and mc>0; e3_symbols[s]={"mean_base_executable_net":mb,"mean_conservative_executable_net":mc,"mean_funding_contribution":mf,"pass":ok}
    e3=all(x["pass"] for x in e3_symbols.values()); payload["gates"]["E3"]={"pass":e3,"symbols":e3_symbols}
    if not e3: write_and_exit(a.out,payload,"REJECT(E-COST)")
    e4_symbols={}
    for s in SYMBOLS:
        vec=[x["base_net_return"] for x in symbol_data[s]]; h1=mean(vec[:17]); h2=mean(vec[17:]); ok=h1 is not None and h2 is not None and h1>0 and h2>0; e4_symbols[s]={"h1_mean_base_net":h1,"h2_mean_base_net":h2,"pass":ok}
    e4=all(x["pass"] for x in e4_symbols.values()); payload["gates"]["E4"]={"pass":e4,"symbols":e4_symbols}
    if not e4: write_and_exit(a.out,payload,"REJECT(E-FRAGILE)")
    e5_symbols={}
    for s in SYMBOLS:
        ranked=sorted(symbol_data[s],key=lambda x:(abs(x["formation_return"]),x["entry_time_ms"])); control=ranked[:7]; active=ranked[7:]; mc=mean([x["signed_gross_return"] for x in control]); ma=mean([x["signed_gross_return"] for x in active]); ok=ma is not None and mc is not None and ma>mc; e5_symbols[s]={"control_n":len(control),"active_n":len(active),"control_mean_signed_gross":mc,"active_mean_signed_gross":ma,"pass":ok}
    e5=all(x["pass"] for x in e5_symbols.values()); payload["gates"]["E5"]={"pass":e5,"symbols":e5_symbols}
    if not e5: write_and_exit(a.out,payload,"REJECT(E-PLACEBO)")
    e6_symbols={}
    for s in SYMBOLS:
        cand=[x["base_net_return"] for x in symbol_data[s]]; base=[x["baseline_long_base_net_return"] for x in symbol_data[s]]; cs=sharpe(cand); bs=sharpe(base); cm=mean(cand); bm=mean(base); ok=(cs is not None and bs is not None and cm>bm and cs>bs); e6_symbols[s]={"candidate_mean_base_net":cm,"baseline_mean_base_net":bm,"candidate_nonannualized_sharpe":cs,"baseline_nonannualized_sharpe":bs,"pass":ok}
    e6=all(x["pass"] for x in e6_symbols.values()); payload["gates"]["E6"]={"pass":e6,"baseline":"weekly always-long same timestamps/costs","symbols":e6_symbols}
    if not e6: write_and_exit(a.out,payload,"REJECT(E-BASELINE)")
    fc,ids=family_count(a.trial_ledger); e7_symbols={}
    for s in SYMBOLS:
        vec=[x["base_net_return"] for x in symbol_data[s]]; pval,detail=psr(vec); ok=pval is not None and pval>PSR_MIN; e7_symbols[s]={"psr":pval,"minimum_psr":PSR_MIN,"detail":detail,"pass":ok}
    e7=(fc==1 and all(x["pass"] for x in e7_symbols.values())); payload["gates"]["E7"]={"pass":e7,"ledger_family_trial_count":fc,"ledger_family_trial_ids":ids,"within_family_dsr_note":"n_trials=1; no multiple-candidate uplift beyond SR*=0; cross-family correction deferred by frozen Trial Ledger rule","symbols":e7_symbols}
    if not e7: write_and_exit(a.out,payload,"REJECT(E-SELECTION)")
    e8_symbols={}
    for s in SYMBOLS:
        vec=[x["base_net_return"] for x in symbol_data[s]]; dd,solvent=max_drawdown(vec); worst=min(vec); ok=solvent and dd<MAX_DRAWDOWN and worst>WORST_WEEK_FLOOR; e8_symbols[s]={"max_compounded_drawdown":dd,"max_drawdown_limit":MAX_DRAWDOWN,"worst_week_base_net":worst,"worst_week_floor":WORST_WEEK_FLOOR,"normalized_notional_leverage":1.0,"solvent":solvent,"pass":ok}
    e8=all(x["pass"] for x in e8_symbols.values()); payload["gates"]["E8"]={"pass":e8,"symbols":e8_symbols}
    if not e8: write_and_exit(a.out,payload,"REJECT(E-RISK)")
    payload["validation_sharpe_nonannualized"]={s:sharpe([x["base_net_return"] for x in symbol_data[s]]) for s in SYMBOLS}; payload["weekly_details"]=symbol_data; write_and_exit(a.out,payload,"PROMOTE_TO_FORWARD")
if __name__=="__main__": main()
