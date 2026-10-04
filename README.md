# Catalyst 9800 Wireless Disaster-Recovery Readiness

Connects to a pair of Catalyst 9800 wireless LAN controllers over the CLI,
collects the state that actually determines whether wireless survives the loss
of a data centre, scores **DR readiness**, discovers and draws the **topology**
in 2D and 3D, and plays an **operator-gated, CLI-driven site failover**
(WLC-PRI → WLC-SEC) end to end — clients dropping and reconnecting included.

There is no physical gear. Every device is a **pyATS / unicon mock** that
replays realistic `show` output, so the whole thing runs on a laptop but the
code path is the real one: `device.connect()`, `device.execute()`,
`device.parse()` (Genie). Pointing it at real controllers is a testbed-only
change (`lab/testbed.yaml`).

## Feature highlights

- **Readiness scoring** across connectivity, redundancy, mobility, AP
  failover, config parity, AAA, interfaces and capacity — PASS/WARN/FAIL with
  evidence and remediation.
- **Topology discovery** purely from `show` output (CDP, AP summary/CDP,
  mobility, AAA) — rendered as a CML-style 2D diagram *and* a toggleable,
  camera-fittable 3D view (same data, same click-through, your choice).
- **Realistic campus design**: two DC sites dual-homed over LACP bundles
  (Port-channel10 to WLC-PRI, Port-channel11 to WLC-SEC), a native `AP_MGMT`
  VLAN plus four client WLANs/SSIDs (`CORP_EMP`, `Robo_IOT`, `ClientVisit`,
  `Guest`), the Guest SSID's traffic illustrated through an edge firewall into
  a DMZ, and two FlexConnect branch sites (2 APs each) homed to WLC-SEC as
  their *primary* controller.
- **Per-AP clients**: every AP carries 2 clients. During the scripted failover
  they visibly drop when their AP loses CAPWAP and reconnect once that AP
  re-joins the fallback controller — not just the APs, the end-user sessions
  too.
- **Operator-gated failover, driven by a simulated CLI**: triggering the
  outage opens an interactive terminal (login, `configure terminal`, then the
  real Port-channel10/11 commands for whichever method you picked) instead of
  a button — you watch the commands "run" before the DR timeline continues.
- **Live SSH mode**: a second mode next to the scripted demo. The dashboard
  starts a real SSH server (`app/virtual_switch.py`) standing in for the core
  switch — open PuTTY (or any SSH client) yourself, log in, and run the actual
  `configure terminal` / `interface Port-channel10` / `shutdown` / `no
  shutdown`. The 2D (and 3D) topology polls that switch every 2 seconds and
  reacts to whatever you type, live.
- **Light / dark theme**, both fully contrast-checked on the topology diagram
  and the device-popup/terminal UI.

```
                    AP_MGMT (native Vlan200) trunk, Po10 / Po11
        ┌─────────────────────────────┬─────────────────────────────┐
  Po10  │                             │                             │  Po11
DC1-CORE-SW1/2 ── WLC-PRI (LAB-DC1)    mobility tunnel    WLC-SEC (LAB-DC2) ── DC2-CORE-SW1/2
        │   active, SSO HA pair       (LAB-DR-GROUP)      DR controller, SSO HA pair │
        │   AP-DC1-01/02, AP-DC2-01/02 (4x C9130AXI)        + AP-BR1-01/02, AP-BR2-01/02 (FlexConnect)
        │   primary=WLC-PRI secondary=WLC-SEC               primary=WLC-SEC secondary=WLC-PRI
        │   2 clients per AP                                 2 clients per AP
        │
  WLANs: 51 CORP_EMP · 52 Robo_IOT · 53 ClientVisit · 54 Guest
  Guest (Vlan54) ──────────────────────────────▶ edge firewall ──▶ DMZ zone

  BRANCH-01 / BRANCH-02 spoke sites  ── FlexConnect APs, local switching, fall back to WLC-SEC
  ISE-PRIMARY / ISE-SECONDARY        ── RADIUS
```

## What it checks

| Area | Check |
|---|---|
| Connectivity | Both controllers reachable over CLI |
| Software | IOS-XE versions match (APs won't cross-join incompatible versions) |
| Redundancy | Each controller's SSO HA pair is converged (standby HOT, comms up) |
| Redundancy | DR controller wireless HA (RMI+RP) healthy, gateway reachable |
| DR data path | Inter-site mobility tunnel WLC-PRI ↔ WLC-SEC is Up |
| AP failover | Every AP has a distinct, configured secondary controller **and** AP fallback enabled — DC APs run primary=WLC-PRI/secondary=WLC-SEC, branch APs legitimately run the reverse |
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

# the dashboard: readiness gauge + 2D/3D topology + failover playback
python app/web.py            # http://127.0.0.1:5000
#   - Play failover runs to a GATE and waits: you pick how to fail WLC-PRI
#       A) shut the Port-channel10 member ports (instant CAPWAP drop, ~132s RTO)
#       B) shut the Port-channel10 bundle itself (heartbeat wait, ~168s RTO)
#     either way, a simulated terminal then walks you through the real CLI:
#     login (cisco / Lab@12345) -> configure terminal -> the chosen Po10
#     interface(s) -> shutdown on DC1's core, then over to DC2's core to
#     cycle Port-channel11 (shut + no shutdown) confirming WLC-SEC's own
#     uplink is healthy before continuing
#   - the topology animates APs *and their clients* dropping off WLC-PRI and
#     re-registering on WLC-SEC once you continue
#   - toggle 2D / 3D on the topology panel, and Dark / Light in the header
#   - click any device -> Web UI (simulated login page) or CLI (copies ssh cmd)
#   - switch "Scripted demo" -> "Live SSH" on the failover panel: the
#     dashboard shows you a real SSH command (ssh cisco@<host> -p 2222,
#     password Lab@12345) to a virtual core switch it just started
#     (app/virtual_switch.py). Open that in PuTTY yourself and run
#     configure terminal / interface Port-channel10 / shutdown / no shutdown
#     -- the topology polls it every 2s and reacts to whatever you type,
#     live, no script involved

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
  healthy/              steady state: WLC-PRI carries the 4 DC APs,
                        WLC-SEC carries the 4 branch (FlexConnect) APs
  failover/             LAB-DC1 gone: the 4 DC APs + clients now on
                        WLC-SEC alongside the branch APs; mobility peer
                        Down  (WLC-PRI has no mock -> unreachable)

app/connect.py          load testbed, select scenario, open the session
                        (with an SSH-style transcript), guarantee disconnect
app/collectors.py       run the DR command set; Genie parse where solid,
                        app/parsers.py text fallback for fussy eWLC output
                        (including per-AP client association); normalise
                        into one flat `facts` dict. A read-only guard refuses
                        anything that isn't show / dir / more.
app/readiness.py        the checks above, over primary + DR facts
app/topology.py         facts -> {nodes, edges} graph: controllers, core +
                        access switches, APs, their clients (2 each, laid
                        out under their AP), AAA, and -- when a Guest SSID
                        is present -- the firewall/DMZ segment
app/icons.py            inline SVG Cisco-style device glyphs (controller,
                        switch, AP, AAA, firewall, DMZ, client)
app/scenario.py         collect healthy -> operator gate + per-method CLI
                        script + timeline -> collect failover -> diff
                        (APs moved, clients moved, RTO)
app/reports.py          JSON + HTML report writers
app/virtual_switch.py   a real SSH server (asyncssh) standing in for the DC1
                        core switch -- enough Cisco-style CLI to SSH in with
                        PuTTY and run configure terminal / interface
                        Port-channel10 / shutdown / no shutdown by hand.
                        Admin state goes to run/vswitch_state.json
app/web.py              Flask dashboard; starts the virtual switch in the
                        background and exposes /api/live_state for it
templates/dashboard.html  readiness gauge, 2D (vis-network) + 3D
                        (3d-force-graph) topology toggle, light/dark theme,
                        the simulated CLI-login failover trigger, a Live SSH
                        mode that polls /api/live_state every 2s instead,
                        before/after diff
tests/dr_readiness/     the same engine as a pyATS aetest Testcase
tests/test_readonly.py  proves only 'show' commands can be issued
```

The failover timeline timings are **modelled** on real C9800 AP N+1 fallback
(3×10 s fast heartbeat, ~30 s primary discovery, CAPWAP join, 802.1X re-auth);
the before/after state on either side of it is really collected from the mocks.
The demo CLI script also cycles Port-channel11 on DC2 as part of the drill —
it's shut and immediately brought back up, because if it stayed down WLC-SEC
would be unreachable too and there'd be nothing left to fail over to. Only
the sustained Port-channel10 (WLC-PRI) outage drives the readiness/topology
state change.

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
primary" path is exactly what you want during a real outage. The CLI script
shown in the dashboard's failover trigger stays illustrative — this tool never
sends config to a real device; you run the shutdown yourself.
