#!/usr/bin/env python
"""
Connect to WLC-PRI + WLC-SEC and score wireless DR readiness.

    python scripts/run_readiness.py [--scenario healthy|failover]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import reports  # noqa: E402
from app.collectors import collect_all  # noqa: E402
from app.readiness import evaluate  # noqa: E402

_MARK = {"PASS": "PASS ", "WARN": "WARN ", "FAIL": "FAIL "}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", default="healthy", choices=("healthy", "failover"))
    args = ap.parse_args()

    print("=" * 78)
    print(f" Catalyst 9800 Wireless DR Readiness  --  scenario: {args.scenario}")
    print("=" * 78)

    controllers = collect_all(args.scenario)
    for name, cd in controllers.items():
        state = "reachable" if cd.reachable else f"UNREACHABLE ({'; '.join(cd.errors)})"
        print(f"  {name:8} {cd.mgmt_ip:16} {cd.site:8} {state}")
    print()

    report = evaluate(controllers)
    for c in report["checks"]:
        print(f"  {_MARK[c['status']]}| {c['title']}")
        print(f"        {c['detail']}")
        if c["status"] != "PASS" and c["remediation"]:
            print(f"        -> {c['remediation']}")
    print()
    print("-" * 78)
    cnt = report["counts"]
    print(f"  Overall: {report['overall']}   Score: {report['score']}%   "
          f"(PASS {cnt['pass']} / WARN {cnt['warn']} / FAIL {cnt['fail']})")
    path = reports.write_readiness(report, args.scenario)
    print(f"  Report: {path}")
    print("=" * 78)
    return 0 if report["overall"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
