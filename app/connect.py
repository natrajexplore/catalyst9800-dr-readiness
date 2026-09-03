"""
Testbed loading and device connection.

Everything the toolkit does starts here: load the pyATS testbed, point each
device's unicon mock at the scenario under test, and open the CLI session the
way a real SSH connection would be opened.

Swapping in real hardware is a testbed-only change (lab/testbed.yaml) -- nothing
here assumes the connection is mocked.
"""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from pyats.topology import loader

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTBED_FILE = REPO_ROOT / "lab" / "testbed.yaml"
MOCK_ROOT = REPO_ROOT / "mock"

SCENARIOS = ("healthy", "failover")

# In the "failover" scenario the primary data centre (LAB-DC1) is gone, so
# WLC-PRI is simply unreachable -- there is no mock to connect to.
UNREACHABLE = {
    "failover": {"WLC-PRI": "LAB-DC1 site outage - management IP not responding"},
}


@dataclass
class ConnectResult:
    """Outcome of a single connection attempt, with an SSH-style transcript."""

    name: str
    scenario: str
    mgmt_ip: str
    site: str
    reachable: bool
    device: object | None = None
    error: str | None = None
    transcript: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0


def load_testbed(scenario: str):
    """Load lab/testbed.yaml with the mock pointed at *scenario*."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; pick one of {SCENARIOS}")
    os.environ["C9800DR_MOCK_ROOT"] = str(MOCK_ROOT)
    os.environ["C9800DR_SCENARIO"] = scenario
    return loader.load(str(TESTBED_FILE))


def _log(result: ConnectResult, line: str) -> None:
    result.transcript.append(line)


@contextlib.contextmanager
def connect_device(testbed, name: str, scenario: str) -> Iterator[ConnectResult]:
    """
    Connect to one controller and guarantee disconnect.

    Yields a :class:`ConnectResult`. An unreachable controller still yields
    (``reachable=False``) so callers record the outage instead of crashing.
    """
    dev = testbed.devices[name]
    mgmt_ip = dev.custom.get("mgmt_ip", "?")
    site = dev.custom.get("site", "?")
    result = ConnectResult(name=name, scenario=scenario, mgmt_ip=mgmt_ip, site=site,
                           reachable=False)

    planned_outage = UNREACHABLE.get(scenario, {}).get(name)
    started = time.monotonic()

    _log(result, f"ssh admin@{mgmt_ip}    # {name} ({site})")
    if planned_outage:
        _log(result, f"ssh: connect to host {mgmt_ip} port 22: No route to host")
        result.error = planned_outage
        result.elapsed_s = time.monotonic() - started
        yield result
        return

    try:
        dev.connect(log_stdout=False)
        result.reachable = True
        result.device = dev
        _log(result, "Password: ********")
        _log(result, f"{dev.name}#            # CLI session established")
    except Exception as exc:  # noqa: BLE001 - any connect failure is data, not a crash
        result.error = f"{type(exc).__name__}: {exc}".splitlines()[0][:200]
        _log(result, f"ssh: {result.error}")

    result.elapsed_s = time.monotonic() - started

    try:
        yield result
    finally:
        with contextlib.suppress(Exception):
            if result.reachable and dev.connected:
                dev.disconnect()
                _log(result, f"{dev.name}# exit")
                _log(result, f"Connection to {mgmt_ip} closed.")
