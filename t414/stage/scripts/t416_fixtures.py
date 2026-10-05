#!/usr/bin/env python3
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
spec=importlib.util.spec_from_file_location("e","t414/stage/scripts/t416_c6_evaluator.py")
e=importlib.util.module_from_spec(spec); spec.loader.exec_module(e)
U=timezone.utc
assert e.DATA == Path.cwd()/"data/t414"
assert e.LEDGER == Path.cwd()/"t414/stage/research/external-leads/XL-20260926-001-timestamp-provenance-ledger-v0.csv"
assert e.ceil5(datetime(2024,1,2,3,4,0,tzinfo=U))==datetime(2024,1,2,3,5,tzinfo=U)
assert e.ceil5(datetime(2024,1,2,3,5,0,tzinfo=U))==datetime(2024,1,2,3,5,tzinfo=U)
assert e.ceil5(datetime(2024,1,2,3,5,1,tzinfo=U))==datetime(2024,1,2,3,10,tzinfo=U)
assert e.ceil5(datetime(2024,1,2,3,59,59,tzinfo=U))==datetime(2024,1,2,4,0,tzinfo=U)
print("T416_PATH_BOUNDARY_FIXTURES_PASS")
