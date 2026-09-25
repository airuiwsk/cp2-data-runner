"""FD3 symbolic-search algorithm tournament.

Synthetic controls only. No real market data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from copy import deepcopy
from pathlib import Path

from dsl import evaluate, expression_hash, normalized_ast, validate

FIELDS=["x0","x1","x2","x3"]
FIELD_DIMS={k:"dimensionless" for k in FIELDS}
LAGS=[1,2,3,5,8]
WINDOWS=[2,3,5,8]
BUDGET=600


def corr(a,b):
    p=[(x,y) for x,y in zip(a,b) if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    if len(p)<30:
        return 0.0
    xs,ys=zip(*p)
    mx,my=sum(xs)/len(xs),sum(ys)/len(ys)
    vx=sum((x-mx)**2 for x in xs); vy=sum((y-my)**2 for y in ys)
    if vx<1e-18 or vy<1e-18:
        return 0.0
    return sum((x-mx)*(y-my) for x,y in p)/math.sqrt(vx*vy)


def standardize(v):
    xs=[x for x in v if x is not None and math.isfinite(x)]
    m=sum(xs)/len(xs)
    s=math.sqrt(sum((x-m)**2 for x in xs)/len(xs))
    return [None if x is None else (x-m)/s for x in v]


def make_fields(seed,n):
    r=random.Random(seed)
    return {f:[r.gauss(0,1) for _ in range(n)] for f in FIELDS}


def hidden_plant(seed):
    r=random.Random(seed ^ 0xA5A5A5A5)
    fam=r.randrange(4)
    f=FIELDS[r.randrange(4)]
    n=r.choice(LAGS)
    base={"type":"op","op":"lag","args":[{"type":"field","name":f}],"params":{"n":n}}
    if fam==0:
        return base
    if fam==1:
        return {"type":"op","op":"sign","args":[base],"params":{}}
    if fam==2:
        return {"type":"op","op":"rolling_mean","args":[base],"params":{"window":r.choice(WINDOWS)}}
    f2=FIELDS[r.randrange(4)]
    n2=r.choice(LAGS)
    b2={"type":"op","op":"lag","args":[{"type":"field","name":f2}],"params":{"n":n2}}
    return {"type":"op","op":"mul","args":[base,b2],"params":{}}


def make_target(data,seed,plant=None):
    r=random.Random(seed)
    noise=[r.gauss(0,1) for _ in range(len(next(iter(data.values()))))]
    if plant is None:
        return noise
    z=standardize(evaluate(plant,data))
    return [None if s is None else 0.14*s+e for s,e in zip(z,noise)]


def field_ast(r):
    return {"type":"field","name":FIELDS[r.randrange(4)]}


def lag_ast(r):
    return {"type":"op","op":"lag","args":[field_ast(r)],"params":{"n":r.choice(LAGS)}}


def random_expr(r):
    c=r.randrange(7)
    a=lag_ast(r)
    if c==0:
        return a
    if c==1:
        return {"type":"op","op":"sign","args":[a],"params":{}}
    if c==2:
        return {"type":"op","op":"rolling_mean","args":[a],"params":{"window":r.choice(WINDOWS)}}
    if c==3:
        return {"type":"op","op":"zscore","args":[a],"params":{"window":r.choice([5,8,13])}}
    b=lag_ast(r)
    if c==4:
        return {"type":"op","op":"mul","args":[a,b],"params":{}}
    if c==5:
        return {"type":"op","op":"add","args":[a,b],"params":{}}
    return {"type":"op","op":"sub","args":[a,b],"params":{}}


def mutate(parent,r):
    p=deepcopy(parent)
    c=r.randrange(5)
    if c==0:
        return random_expr(r)
    if c==1:
        return {"type":"op","op":"sign","args":[p],"params":{}}
    if c==2:
        return {"type":"op","op":"rolling_mean","args":[p],"params":{"window":r.choice(WINDOWS)}}
    q=random_expr(r)
    if c==3:
        return {"type":"op","op":r.choice(["add","sub","mul"]),"args":[p,q],"params":{}}
    return {"type":"op","op":"zscore","args":[p],"params":{"window":r.choice([5,8,13])}}


def score_ast(ast,data,target):
    v=validate(ast,FIELD_DIMS,max_depth=6)
    if not v["valid"]:
        return None
    return corr(evaluate(ast,data),target)


def random_search(data,target,seed):
    r=random.Random(seed)
    rows=[]; seen=set()
    for _ in range(BUDGET):
        ast=random_expr(r)
        h=expression_hash(ast)
        if h in seen:
            continue
        seen.add(h)
        s=score_ast(ast,data,target)
        if s is not None:
            rows.append((s,h,normalized_ast(ast)))
    rows.sort(key=lambda x:(x[0],x[1]),reverse=True)
    return rows


def evolutionary_search(data,target,seed,initial=None):
    r=random.Random(seed)
    population=[deepcopy(x) for x in (initial or [])]
    while len(population)<60:
        population.append(random_expr(r))
    rows_by_hash={}
    raw=0
    while raw<BUDGET:
        generation=[]
        for ast in population:
            if raw>=BUDGET:
                break
            raw+=1
            h=expression_hash(ast)
            s=score_ast(ast,data,target)
            if s is None:
                continue
            if h not in rows_by_hash or s>rows_by_hash[h][0]:
                rows_by_hash[h]=(s,h,normalized_ast(ast))
            generation.append((s,ast))
        ranked=sorted(generation,key=lambda x:x[0],reverse=True)
        elites=[a for _,a in ranked[:12]]
        if not elites:
            population=[random_expr(r) for _ in range(60)]
            continue
        nxt=[deepcopy(x) for x in elites[:6]]
        while len(nxt)<60:
            if r.random()<0.25 and len(elites)>=2:
                a=deepcopy(r.choice(elites)); b=deepcopy(r.choice(elites))
                child={"type":"op","op":r.choice(["add","sub","mul"]),"args":[a,b],"params":{}}
            else:
                child=mutate(r.choice(elites),r)
            nxt.append(child)
        population=nxt
    rows=list(rows_by_hash.values())
    rows.sort(key=lambda x:(x[0],x[1]),reverse=True)
    return rows


def load_seeds():
    p=Path(__file__).with_name("llm_seed_pool_v1.json")
    return json.loads(p.read_text())["seeds"]


def search(alg,data,target,seed):
    if alg=="G0_RANDOM":
        return random_search(data,target,seed)
    if alg=="G1_GP":
        return evolutionary_search(data,target,seed,initial=None)
    if alg=="G2_LLM_SEEDED":
        return evolutionary_search(data,target,seed,initial=load_seeds())
    raise ValueError(alg)


def one_rep(alg,kind,i):
    base=300_000+i*1237
    d0=make_fields(base+11,1000)
    d2=make_fields(base+12,500)
    plant=hidden_plant(base) if kind=="positive" else None
    y0=make_target(d0,base+13,plant)
    y2=make_target(d2,base+14,plant)
    rows=search(alg,d0,y0,base+15)
    if not rows:
        raise RuntimeError(f"{alg} no valid rows")
    ch=rows[0]
    d2c=corr(evaluate(ch[2],d2),y2)
    ph=expression_hash(plant) if plant else None
    return {
      "algorithm":alg,"kind":kind,"replicate":i,
      "unique_valid_expressions":len(rows),
      "champion_hash":ch[1],"d0_score":ch[0],"d2_corr":d2c,"d2_pass":d2c>0.08,
      "planted_hash":ph,"exact_planted_recovered":bool(ph and ph==ch[1])
    }


def run_once():
    algs=["G0_RANDOM","G1_GP","G2_LLM_SEEDED"]
    result={}
    all_rows=[]
    for alg in algs:
        null=[one_rep(alg,"null",i) for i in range(24)]
        pos=[one_rep(alg,"positive",i) for i in range(24)]
        all_rows+=null+pos
        d2s=sorted(r["d2_corr"] for r in pos)
        result[alg]={
          "null_false_confirmations":sum(r["d2_pass"] for r in null),
          "positive_d2_passes":sum(r["d2_pass"] for r in pos),
          "positive_exact_planted_recoveries":sum(r["exact_planted_recovered"] for r in pos),
          "positive_median_d2_corr":d2s[len(d2s)//2],
          "min_unique_valid_expressions":min(r["unique_valid_expressions"] for r in null+pos),
        }
    return {"algorithms":result,"rows":all_rows}


def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="fd3-tournament-report.json")
    args=ap.parse_args()
    a=run_once(); b=run_once()
    deterministic=digest(a)==digest(b)
    eligible={}
    for alg,m in a["algorithms"].items():
        eligible[alg]=(m["null_false_confirmations"]<=4 and m["positive_d2_passes"]>=12 and m["min_unique_valid_expressions"]>=50)
    ranking=sorted(
      [alg for alg,ok in eligible.items() if ok],
      key=lambda alg:(-a["algorithms"][alg]["positive_d2_passes"],
                      a["algorithms"][alg]["null_false_confirmations"],
                      -a["algorithms"][alg]["positive_median_d2_corr"],
                      alg)
    )
    gates={
      "deterministic_digest_match":deterministic,
      "at_least_one_eligible_algorithm":bool(ranking),
      "no_real_market_data":True,
      "no_real_market_performance":True
    }
    status="PASS" if all(gates.values()) else "FAIL"
    out={
      "fd_stage":"FD3_ALGORITHM_TOURNAMENT",
      "status":status,
      "gates":gates,
      "eligibility":eligible,
      "selected_pilot_generator":ranking[0] if ranking else None,
      "canonical_result_digest":digest(a),
      "algorithms":a["algorithms"],
      "rows":a["rows"],
      "real_market_data_loaded":False,
      "real_market_performance_inspected":False
    }
    Path(args.out).write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    small={k:out[k] for k in ["fd_stage","status","gates","eligibility","selected_pilot_generator","canonical_result_digest","algorithms"]}
    print(json.dumps(small,sort_keys=True))
    if status!="PASS":
        raise SystemExit(2)


if __name__=="__main__":
    main()
