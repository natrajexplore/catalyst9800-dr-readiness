"""
pyATS aetest: Catalyst 9800 wireless DR readiness.

Runs the same fact collection + readiness engine the CLI/dashboard use, but as a
proper aetest Testcase so it slots into CI / pyATS reporting.

    pyats run job tests/dr_readiness/job.py
    # or standalone:
    python tests/dr_readiness/dr_readiness_test.py --scenario healthy
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pyats import aetest  # noqa: E402

from app.collectors import collect_all  # noqa: E402
from app.readiness import evaluate  # noqa: E402


class CommonSetup(aetest.CommonSetup):
    @aetest.subsection
    def collect(self, steps, scenario="healthy"):
        with steps.start(f"Connect to controllers and collect facts ({scenario})"):
            self.parent.parameters["controllers"] = collect_all(scenario)
        with steps.start("Score DR readiness"):
            self.parent.parameters["report"] = evaluate(
                self.parent.parameters["controllers"])


class DRReadiness(aetest.Testcase):
    @aetest.setup
    def setup(self):
        self.report = self.parent.parameters["report"]
        aetest.loop.mark(self.check, check=self.report["checks"])

    @aetest.test
    def check(self, check):
        msg = f"{check['title']}: {check['detail']}"
        if check["status"] == "PASS":
            self.passed(msg)
        elif check["status"] == "WARN":
            self.passx(msg + f"  -> {check['remediation']}")
        else:
            self.failed(msg + f"  -> {check['remediation']}")

    @aetest.test
    def overall(self):
        r = self.report
        if r["overall"] == "FAIL":
            self.failed(f"DR readiness {r['overall']} ({r['score']}%): {r['counts']}")
        self.passed(f"DR readiness {r['overall']} ({r['score']}%)")


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def done(self):
        pass


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="healthy", choices=("healthy", "failover"))
    args, rest = ap.parse_known_args()
    sys.argv = [sys.argv[0]] + rest
    aetest.main(scenario=args.scenario)
