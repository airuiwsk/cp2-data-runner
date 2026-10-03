#!/usr/bin/env python3
"""T414 non-performance synthetic fixtures for frozen execution/source-completeness semantics."""
import csv, importlib.util, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

spec=importlib.util.spec_from_file_location("e","scripts/t414_c6_evaluator.py")
e=importlib.util.module_from_spec(spec); spec.loader.exec_module(e)
UTC=timezone.utc
assert e.ceil5(datetime(2024,1,2,3,4,0,tzinfo=UTC))==datetime(2024,1,2,3,5,tzinfo=UTC)
assert e.ceil5(datetime(2024,1,2,3,5,0,tzinfo=UTC))==datetime(2024,1,2,3,5,tzinfo=UTC)
assert e.ceil5(datetime(2024,1,2,3,5,1,tzinfo=UTC))==datetime(2024,1,2,3,10,tzinfo=UTC)
with tempfile.TemporaryDirectory() as td:
    e.DATA=Path(td); e._cache.clear()
    entry=datetime(2024,1,2,3,5,tzinfo=UTC); exit_=entry+timedelta(hours=4)
    def write(sym, rows):
        p=e.DATA/f"{sym}-2024-01-02.csv"
        with p.open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=["timestamp","price","size"]); w.writeheader()
            for t,price,size in rows:w.writerow({"timestamp":t.timestamp(),"price":price,"size":size})
    write("XMRUSDT",[(entry,100,1),(entry+timedelta(minutes=1),110,3),(exit_,120,2)])
    write("BTCUSDT",[(entry,200,1),(entry+timedelta(minutes=1),220,3),(exit_,240,2)])
    t=entry
    assert e.source_complete(t)
    assert abs(e.vwap("XMRUSDT",entry)-107.5)<1e-12
    net,res=e.ep(t)
    assert abs(net-(120/107.5-1-e.COST))<1e-12
    assert abs(res-((120/107.5-1)-(240/215-1)))<1e-12
    # Source completeness is strict: removing BTC exit makes the timestamp ineligible.
    write("BTCUSDT",[(entry,200,1),(entry+timedelta(minutes=1),220,3)])
    e._cache.clear()
    assert not e.source_complete(t)
print("T414_SYNTHETIC_FIXTURES_PASS")
