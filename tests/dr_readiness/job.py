"""pyATS job: run the DR readiness testcase.

    pyats run job tests/dr_readiness/job.py [--scenario failover]
"""

import argparse
import os
from pathlib import Path

from pyats.easypy import run

TESTFILE = Path(__file__).parent / "dr_readiness_test.py"
REPO = Path(__file__).resolve().parents[2]


def main(runtime):
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="healthy", choices=("healthy", "failover"))
    args, _ = parser.parse_known_args()

    # app.connect also sets these, but set here too so a bare `pyats run job` works.
    os.environ.setdefault("C9800DR_MOCK_ROOT", str(REPO / "mock"))
    os.environ["C9800DR_SCENARIO"] = args.scenario

    run(testscript=str(TESTFILE), runtime=runtime, scenario=args.scenario,
        taskid=f"dr-readiness-{args.scenario}")
