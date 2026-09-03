#!/usr/bin/env python
"""
Discover the wireless topology from the controllers (CDP, AP summary, AP CDP,
mobility, AAA) and write reports/topology.json.

    python scripts/discover_topology.py [--scenario healthy|failover]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import reports  # noqa: E402
from app.collectors import collect_all  # noqa: E402
from app.topology import build  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", default="healthy", choices=("healthy", "failover"))
    args = ap.parse_args()

    controllers = collect_all(args.scenario)
    topo = build(controllers, args.scenario)

    print(f"Discovered topology ({args.scenario}):")
    print(f"  controllers : {topo['stats']['controllers']}")
    print(f"  APs         : {topo['stats']['aps']}")
    print(f"  switches    : {topo['stats']['switches']}")
    print()
    for e in topo["edges"]:
        print(f"  {e['source']:16} --{e['type']:15}--> {e['target']:20} [{e['status']}] {e['label']}")
    path = reports.write_topology(topo)
    print(f"\n  Report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
