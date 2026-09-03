#!/usr/bin/env python
"""
Scripted DR failover rehearsal (non-disruptive).

Collects the healthy state, prints the operator-gated failover timeline for each
trigger method, collects the failover state, and diffs the two.

    python scripts/run_failover.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import reports  # noqa: E402
from app.scenario import run  # noqa: E402


def main() -> int:
    result = run()
    b, a = result["before"]["readiness"], result["after"]["readiness"]
    print("=" * 78)
    print(" Catalyst 9800 Wireless DR -- scripted failover rehearsal")
    print("=" * 78)
    print(f"  BEFORE readiness {b['overall']:5} ({b['score']}%)   "
          f"WLC-PRI APs: {len(result['before']['controllers']['WLC-PRI']['aps'])}")
    for ev in result["pre"]:
        print(f"  {ev['clock']:7} {ev['headline']}")
    print(f"\n  GATE: {result['gate']['headline']}")
    for key, m in result["methods"].items():
        print(f"\n  -- method '{key}': {m['label']}  (RTO ~{m['rto_s']}s) --")
        print(f"     trigger on {m['where']}:")
        for cmd in m["commands"]:
            print(f"       {cmd}")
        for ev in m["steps"]:
            print(f"     {ev['clock']:7} [{ev['phase']:>11}] {ev['headline']}")
    print("\n" + "-" * 78)
    print(f"  AFTER readiness  {a['overall']:5} ({a['score']}%)   "
          f"APs failed over: {result['diff']['aps_failed_over_count']}")
    print(f"  Report: {reports.write_failover(result)}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
