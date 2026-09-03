# Catalyst 9800 Wireless Disaster-Recovery Readiness

Connects to a pair of Catalyst 9800 wireless LAN controllers over the CLI,
collects the state that actually determines whether wireless survives the loss
of a data centre, scores **DR readiness**, discovers and draws the **topology**,
and plays an **operator-gated site failover** (WLC-PRI → WLC-SEC) end to end.

There is no physical gear. Every device is a **pyATS / unicon mock** that
replays realistic `show` output, so the whole thing runs on a laptop but the
code path is the real one: `device.connect()`, `device.execute()`,
`device.parse()` (Genie). Pointing it at real controllers is a testbed-only
change (`lab/testbed.yaml`).

```
WLC-PRI  (LAB-DC1)  active controller, SSO HA pair ─┐
                                                     ├─ mobility tunnel (LAB-DR-GROUP)
WLC-SEC  (LAB-DC2)  DR controller, SSO HA pair    ─┘  N+1 secondary for every AP
AP-DC1-01/02, AP-DC2-01/02   4x C9130AXI, primary=WLC-PRI  secondary=WLC-SEC
ISE-PRIMARY / ISE-SECONDARY  RADIUS
```

## What it checks

| Area | Check |
|---|---|
| Connectivity | Both controllers reachable over CLI |
| Software | IOS-XE versions match (APs won't cross-join incompatible versions) |
| Redundancy | Each controller's SSO HA pair is converged (standby HOT, comms up) |
| Redundancy | DR controller wireless HA (RMI+RP) healthy, gateway reachable |
| DR data path | Inter-site mobility tunnel WLC-PRI ↔ WLC-SEC is Up |
| AP failover | Every AP has WLC-SEC as N+1 secondary **and** AP fallback enabled |
| Config parity | WLAN / SSID / security identical on both controllers |
| AAA | RADIUS (ISE) reachable from both controllers |
| Interfaces | Management / wireless-management VLANs symmetric and up |
| Capacity | DR controller can absorb the full primary-site AP + client load |

Each check reports **PASS / WARN / FAIL**, the evidence it used, and — on
anything less than PASS — what to do about it.

## Requirements & platform note

**pyATS and Genie are Linux/macOS only.** On Windows, run this project under
**WSL2** (Ubuntu). `unicon`'s mock CLI also can't cope with spaces in paths, so
setup installs into a venv on the Linux filesystem and exposes the repo via a
space-free symlink.

## Setup (WSL)

```bash
# from the repo folder on the Windows side, open a WSL shell here
wsl
bash setup_wsl.sh
```

`setup_wsl.sh` symlinks the repo to `~/c9800dr`, creates `~/.venvs/c9800dr`
(Python 3.12), and `pip install "pyats[library]" flask`. Then every session:

```bash
source ~/.venvs/c9800dr/bin/activate
export PATH="$HOME/.venvs/c9800dr/bin:$PATH"   # unicon needs mock_device_cli on PATH
cd ~/c9800dr
```

## Usage

```bash
# score DR readiness
python scripts/run_readiness.py
python scripts/run_readiness.py --scenario failover     # readiness mid-outage

# discover + dump the topology
python scripts/discover_topology.py

# the scripted, operator-gated failover
python scripts/run_failover.py

# the dashboard: readiness gauge + topology (Cisco icons) + failover playback
python app/web.py            # http://127.0.0.1:5000
#   - Play failover runs to a GATE and waits: you pick how to fail WLC-PRI
#       A) shut its uplink switchports (instant CAPWAP drop, ~55s RTO)
#       B) shut the DC core VLAN 200 SVI (heartbeat wait, ~95s RTO)
#     each shows the exact shutdown + restore CLI; the topology animates the
#     APs discovering and re-homing on WLC-SEC once you continue
#   - click any device -> Web UI (simulated login page) or CLI (copies ssh cmd)

# as a pyATS job (CI / pyATS reporting)
pyats run job tests/dr_readiness/job.py
pyats run job tests/dr_readiness/job.py --scenario failover

# scheduled readiness report (JSON + HTML, optional SMTP_* / REPORT_WEBHOOK_URL)
python scripts/scheduled_report.py
```

JSON + HTML artifacts land in `reports/`.

## How it works

```
lab/testbed.yaml        pyATS testbed. Each controller connection is a
                        unicon mock_device_cli pointed (via C9800DR_* env
                        vars) at mock/<device>/<scenario>/mock_data.yaml.

mock/<dev>/<scenario>/   realistic replayed CLI output.
  healthy/              steady state: WLC-PRI carries all 4 APs
  failover/             LAB-DC1 gone: APs + clients now on WLC-SEC,
                        mobility peer Down  (WLC-PRI has no mock -> unreachable)

app/connect.py          load testbed, select scenario, open the session
                        (with an SSH-style transcript), guarantee disconnect
app/collectors.py       run the DR command set; Genie parse where solid,
                        app/parsers.py text fallback for fussy eWLC output;
                        normalise into one flat `facts` dict. A read-only guard
                        refuses anything that isn't show / dir / more.
app/readiness.py        the checks above, over primary + DR facts
app/topology.py         facts -> {nodes, edges} graph (vis-network)
app/icons.py            inline SVG Cisco-style device glyphs for the diagram
app/scenario.py         collect healthy -> operator gate + per-method timeline
                        -> collect failover -> diff (APs moved, clients moved, RTO)
app/reports.py          JSON + HTML report writers
app/web.py              Flask dashboard
tests/dr_readiness/     the same engine as a pyATS aetest Testcase
tests/test_readonly.py  proves only 'show' commands can be issued
```

The failover timeline timings are **modelled** on real C9800 AP N+1 fallback
(3×10 s fast heartbeat, ~30 s primary discovery, CAPWAP join, 802.1X re-auth);
the before/after state on either side of it is really collected from the mocks.

## Running against real controllers

Edit `lab/testbed.yaml` — replace each `command: mock_device_cli ...` line with:

```yaml
connections:
  cli:
    protocol: ssh
    ip: 192.168.100.10
    port: 22
```

Nothing else changes: `collectors.py` already goes through `device.execute()` /
`device.parse()`, the read-only guard keeps it safe, and the "unreachable
primary" path is exactly what you want during a real outage.
