#!/usr/bin/env python3
"""Frozen T405 / EH-20260924-009 CP4 C6 evaluator.
Do not modify after performance inspection. Input must reconstruct the frozen DI manifest.
"""
import argparse, hashlib, json, math
from datetime import datetime, timezone, timedelta
from pathlib import Path

START=datetime(2026,8,24,tzinfo=timezone.utc); END=datetime(2026,9,24,tzinfo=timezone.utc)
EXPECTED_N=1531794
EXPECTED_SHA="bfc8775ca2aa337a82c0a89d157ed4f5d8cb4e132e1cec221df03423da02b855"
HURDLE=0.002; HIGH=0.20; CONTROL=0.02; MIN_N=30

def dt(s):
    t=datetime.fromisoformat(s.replace('Z','+00:00'))
    if t.tzinfo is None:
        t=t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)
def canonical(records):
    h=hashlib.sha256()
    for x in sorted(records,key=lambda z:int(z['id'])):
        h.update((json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode())
    return h.hexdigest()
def load(root):
    seen={}
    for f in sorted(Path(root).rglob('page-*.json')):
        for x in json.loads(f.read_text()):
            i=int(x['id'])
            if i in seen: raise SystemExit(f'duplicate execution id {i}')
            seen[i]=x
    r=[x for x in seen.values() if START <= dt(x['exec_date']) < END]
    if len(r)!=EXPECTED_N or canonical(r)!=EXPECTED_SHA: raise SystemExit('DI manifest mismatch')
    return sorted(r,key=lambda x:(dt(x['exec_date']),int(x['id'])))
def first_at_or_after(records,t,limit=60):
    end=t+timedelta(seconds=limit)
    for x in records:
        tx=dt(x['exec_date'])
        if tx>=t: return x if tx<=end else None
    return None
def build_bins(records):
    bins={}
    for x in records:
        t=dt(x['exec_date']); b=t.replace(minute=(t.minute//15)*15,second=0,microsecond=0)
        q=float(x['price'])*float(x['size']); side=x['side'].upper()
        if side not in ('BUY','SELL'): raise SystemExit('invalid side')
        z=bins.setdefault(b,[0.0,0.0]); z[0 if side=='BUY' else 1]+=q
    return bins
def events(records,bins,predicate):
    out=[]; blocked_until=None
    for b in sorted(bins):
        buy,sell=bins[b]; total=buy+sell
        if total<=0: raise SystemExit('zero-notional populated bin')
        I=(buy-sell)/total
        if not predicate(I): continue
        boundary=b+timedelta(minutes=15)
        if blocked_until is not None and boundary<blocked_until: continue
        entry=first_at_or_after(records,boundary)
        if entry is None: continue
        et=dt(entry['exec_date']); exitx=first_at_or_after(records,et+timedelta(hours=4))
        if exitx is None: continue
        s=1 if I>0 else -1 if I<0 else 0
        ret=s*math.log(float(exitx['price'])/float(entry['price']))
        out.append({'bin':b.isoformat(),'imbalance':I,'entry_id':int(entry['id']),'exit_id':int(exitx['id']),'signed_gross_log_return':ret})
        blocked_until=dt(exitx['exec_date'])
    return out
def summary(ev):
    n=len(ev); vals=[x['signed_gross_log_return'] for x in ev]
    return {'n':n,'mean_signed_gross_log_return':sum(vals)/n if n else None,'fraction_gt_20bp':sum(v>HURDLE for v in vals)/n if n else None}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('raw_root'); ap.add_argument('--out',default='T405-c6-result.json'); a=ap.parse_args()
    r=load(a.raw_root); bins=build_bins(r)
    high=events(r,bins,lambda I: abs(I)>=HIGH); hs=summary(high)
    # Frozen sequential C6: minimum-N failure is decisive temporal rejection.
    if hs['n']<MIN_N: result={'trial_id':'T405','edge_id':'EH-20260924-009','decision':'CHEAP_REJECT(CR-TEMPORAL)','decisive_gate':'HIGH_MIN_N','high':hs,'control':'NOT_EXECUTED_FROZEN_EARLY_STOP'}
    elif not (hs['mean_signed_gross_log_return']>HURDLE and hs['fraction_gt_20bp']>0.55): result={'trial_id':'T405','edge_id':'EH-20260924-009','decision':'CHEAP_REJECT(CR-TEMPORAL)','decisive_gate':'HIGH_PRIMARY','high':hs,'control':'NOT_EXECUTED_FROZEN_EARLY_STOP'}
    else:
        ctl=events(r,bins,lambda I: abs(I)<=CONTROL); cs=summary(ctl)
        passed=cs['n']>=MIN_N and hs['mean_signed_gross_log_return']-cs['mean_signed_gross_log_return']>0.001
        result={'trial_id':'T405','edge_id':'EH-20260924-009','decision':'PROMOTE_TO_EMPIRICAL' if passed else 'CHEAP_REJECT(CR-TEMPORAL)','decisive_gate':'PASS' if passed else 'NEGATIVE_CONTROL','high':hs,'control':cs}
    result['input_manifest']={'records':EXPECTED_N,'normalized_sha256':EXPECTED_SHA}
    Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,sort_keys=True))
if __name__=='__main__': main()
