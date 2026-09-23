#!/usr/bin/env python3
"""Frozen CP4 C6 evaluator for T402 / EH-20260923-003 v1.

Governance: do not edit constants or logic after first empirical execution.
Uses preregistered OI tail expansion + premium-skew crowding only.
"""
from __future__ import annotations
import argparse, bisect, csv, json, math
from collections import deque
from pathlib import Path

SYMBOLS=("BTCUSDT","ETHUSDT")
OI_START_MS=1704067200000
EVAL_START_MS=1706745600000  # 2024-02-01T00:00:00Z
EVAL_END_MS=1767211200000    # 2025-12-31T20:00:00Z exclusive, leaves 4h exit room
MINUTE=60_000
FIVE_MIN=5*MINUTE
ONE_HOUR=60*MINUTE
FOUR_HOUR=4*ONE_HOUR
LOOKBACK_MS=30*24*ONE_HOUR
PREMIUM_TRIGGER=0.0005
QUANTILE=0.95
MIN_ROLLING_OBS=7000
MIN_EPISODES=50
MIN_SIGN_EPISODES=10
HURDLE=0.0013

def load_oi(path:Path):
    out={}
    with path.open(newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f):
            t=int(r['timestamp_ms']); out[t]=float(r['open_interest'])
    return out

def load_prices(path:Path):
    out={}
    with path.open(newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f): out[int(r['start_ms'])]=float(r['open'])
    return out

def load_premium(path:Path):
    out={}
    with path.open(newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f): out[int(r['start_ms'])]=float(r['close'])
    return out

def nearest_rank(sorted_vals, q):
    if not sorted_vals: raise RuntimeError('BLOCK empty rolling distribution')
    rank=math.ceil(q*len(sorted_vals))
    return sorted_vals[rank-1]

def remove_one(sorted_vals, x):
    i=bisect.bisect_left(sorted_vals,x)
    if i>=len(sorted_vals) or sorted_vals[i]!=x:
        raise RuntimeError('BLOCK rolling multiset corruption')
    sorted_vals.pop(i)

def evaluate_symbol(symbol:str, oi_root:Path, history:Path):
    oi=load_oi(oi_root/'normalized'/f'{symbol}.open_interest_5m.csv')
    premium=load_premium(history/'normalized'/f'{symbol}.premium.csv')
    px=load_prices(history/'normalized'/f'{symbol}.tradeable.csv')
    growth=[]
    for t in sorted(oi):
        if t-OI_START_MS < ONE_HOUR: continue
        if t-ONE_HOUR in oi and oi[t-ONE_HOUR]>0:
            growth.append((t,oi[t]/oi[t-ONE_HOUR]-1.0))
    window=deque()
    sorted_window=[]
    rows=[]
    active_until=None
    for t,g in growth:
        cutoff=t-LOOKBACK_MS
        while window and window[0][0] < cutoff:
            _,old=window.popleft(); remove_one(sorted_window,old)
        threshold=nearest_rank(sorted_window,QUANTILE) if len(sorted_window)>=MIN_ROLLING_OBS else None
        if EVAL_START_MS <= t < EVAL_END_MS and threshold is not None:
            d=t+FIVE_MIN
            if active_until is None or d>=active_until:
                if g>threshold:
                    prem_t=d-MINUTE
                    if prem_t not in premium:
                        raise RuntimeError(f'BLOCK missing premium {symbol} oi={t}')
                    p=premium[prem_t]
                    if p>=PREMIUM_TRIGGER or p<=-PREMIUM_TRIGGER:
                        entry_t=d; exit_t=d+FOUR_HOUR
                        if entry_t not in px or exit_t not in px:
                            raise RuntimeError(f'BLOCK missing price {symbol} oi={t}')
                        side='short' if p>=PREMIUM_TRIGGER else 'long'
                        entry,exit_=px[entry_t],px[exit_t]
                        raw=exit_/entry-1
                        contra=(entry/exit_-1) if side=='short' else raw
                        rows.append({
                            'oi_timestamp_ms':t,'decision_time_ms':d,'oi_growth_1h':g,
                            'rolling_q95':threshold,'premium':p,'side':side,
                            'entry':entry,'exit':exit_,'raw_return':raw,
                            'contrarian_return':contra,
                        })
                        active_until=exit_t
        window.append((t,g)); bisect.insort(sorted_window,g)
    pos=[r['raw_return'] for r in rows if r['premium']>=PREMIUM_TRIGGER]
    neg=[r['raw_return'] for r in rows if r['premium']<=-PREMIUM_TRIGGER]
    n=len(rows)
    mean_contra=sum(r['contrarian_return'] for r in rows)/n if n else None
    mean_pos=sum(pos)/len(pos) if pos else None
    mean_neg=sum(neg)/len(neg) if neg else None
    enough=n>=MIN_EPISODES and len(pos)>=MIN_SIGN_EPISODES and len(neg)>=MIN_SIGN_EPISODES
    direction=(mean_pos is not None and mean_neg is not None and mean_pos<mean_neg)
    clears=(mean_contra is not None and mean_contra>HURDLE)
    return {
        'symbol':symbol,'episodes':n,'positive_premium_episodes':len(pos),
        'negative_premium_episodes':len(neg),'mean_contrarian_return':mean_contra,
        'mean_raw_return_positive_premium':mean_pos,
        'mean_raw_return_negative_premium':mean_neg,'hurdle':HURDLE,
        'minimum_events_pass':enough,'direction_pass':direction,
        'hurdle_pass':clears,'symbol_pass':bool(enough and direction and clears)
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--oi',type=Path,required=True)
    p.add_argument('--history',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    results=[evaluate_symbol(s,a.oi,a.history) for s in SYMBOLS]
    if any(not r['minimum_events_pass'] for r in results):
        decision='BLOCKED(INSUFFICIENT_C6_EVENTS)'
    elif all(r['symbol_pass'] for r in results):
        decision='PASS_TO_CP5'
    else:
        decision='CHEAP_REJECT(CR-TEMPORAL)'
    payload={
        'trial_id':'T402','edge_id':'EH-20260923-003','version':1,
        'frozen_constants':{
            'oi_start_ms':OI_START_MS,'evaluation_start_ms':EVAL_START_MS,
            'evaluation_end_ms_exclusive':EVAL_END_MS,'oi_change_minutes':60,
            'rolling_lookback_days':30,'rolling_quantile':QUANTILE,
            'nearest_rank':True,'minimum_rolling_observations':MIN_ROLLING_OBS,
            'decision_lag_minutes':5,'premium_abs_trigger':PREMIUM_TRIGGER,
            'holding_hours':4,'minimum_episodes':MIN_EPISODES,
            'minimum_each_premium_sign':MIN_SIGN_EPISODES,
            'round_trip_hurdle':HURDLE,'non_overlapping':True
        },
        'symbols':results,'decision':decision
    }
    a.out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(decision)

if __name__=='__main__': main()
