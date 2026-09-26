#!/usr/bin/env python3
"""Non-performance source feasibility preflight for XL-20260926-001.

Checks whether free public pages expose enough historical incident coverage to
construct an outcome-independent hack universe. No market data is loaded.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

SOURCES = {
    "defillama_hacks": "https://defillama.com/hacks",
    "defillama_downloads": "https://defillama.com/downloads",
    "immunefi_research": "https://immunefi.com/blog/research/",
}
SENTINELS = [
    "Ronin",
    "Nomad",
    "WazirX",
    "DMM",
    "Bitget",
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent":"AI-Trading-source-preflight/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        code = getattr(r, "status", 200)
        ctype = r.headers.get("content-type")
    return code, ctype, raw


def main():
    report = {
        "lead_id": "XL-20260926-001",
        "stage": "NON_PERFORMANCE_EVENT_UNIVERSE_SOURCE_PREFLIGHT",
        "market_data_loaded": False,
        "market_performance_computed": False,
        "sources": {},
    }

    for name, url in SOURCES.items():
        try:
            code, ctype, raw = fetch(url)
            text = raw.decode("utf-8", errors="replace")
            low = text.lower()
            report["sources"][name] = {
                "url": url,
                "http_status": code,
                "content_type": ctype,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "sentinels_present": {s: s.lower() in low for s in SENTINELS},
                "contains_csv_token": ".csv" in low or "csv" in low,
                "contains_next_data": "__NEXT_DATA__" in text or "self.__next_f.push" in text,
                "contains_hacks_term": "hack" in low or "exploit" in low,
            }
        except Exception as exc:
            report["sources"][name] = {"url": url, "error": str(exc)}

    d = report["sources"].get("defillama_hacks", {})
    hist_hits = sum(1 for s in ["Ronin","Nomad","WazirX","DMM"] if d.get("sentinels_present",{}).get(s))
    report["diagnostics"] = {
        "defillama_html_historical_sentinel_hits": hist_hits,
        "defillama_page_embeds_next_data_or_rsc": bool(d.get("contains_next_data")),
        "defillama_public_page_accessible": d.get("http_status") == 200,
    }

    # This preflight does not declare the universe source sufficient unless the
    # public page itself visibly carries several old sentinels. A later parser
    # may still recover embedded data if present, but that is a separate step.
    report["status"] = "PASS_PARTIAL" if report["diagnostics"]["defillama_public_page_accessible"] else "FAIL"
    Path("xl001-universe-source-preflight.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "status": report["status"],
        "market_data_loaded": False,
        "market_performance_computed": False,
        "diagnostics": report["diagnostics"],
        "sources": report["sources"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
