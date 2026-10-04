"""
Scripted DR failover -- operator-driven.

WLC-PRI is dual-homed to the DC1 core pair over an LACP bundle, Port-channel10
(WLC-SEC is symmetrically bundled to DC2 over Port-channel11). The demo runs to
a GATE and then waits for the operator to choose HOW to fail the primary
controller, and to actually run the shutdown on the device:

  * "switchport"  -- shut the Port-channel10 *member* interfaces on the DC1
                     core pair (full L2 isolation; CAPWAP drops almost at once)
  * "portchannel" -- shut the Port-channel10 *logical* bundle itself (upstream
                     routing/HSRP has to reconverge first, then the full
                     fast-heartbeat timer runs -- the slowest, most realistic
                     full-site-loss path)

Both scripts now walk the operator through BOTH core sites, per the demo
script: SSH into DC1's core first and shut Port-channel10 (WLC-PRI's uplink --
this is what actually drives the "before" -> "after" mock switch), then SSH
into DC2's core and also shut Port-channel11 for the drill, before explicitly
`no shutdown`-ing it again. That re-enable is deliberate, not a fudge: if Po11
stayed down too, WLC-SEC would be unreachable and there would be no fallback
controller left to demonstrate -- so the script isolates the drill to DC1
(matching `app.connect.UNREACHABLE`'s "LAB-DC1 site outage" premise) and
restores DC2's path before the AP migration phase.

Real C9800 N+1 fallback is not instant: losing a controller, having APs declare
it dead, discover the secondary, CAPWAP-join, and re-register clients routinely
takes on the order of minutes, not seconds -- both methods below model at least
a 2-minute gap before the fleet is back on WLC-SEC.

"before" really connects to the healthy mocks, "after" to the failover mocks.
The per-method timeline in between is the narrated model of the transition.
"""

from __future__ import annotations

from app import readiness, topology
from app.collectors import collect_all

# demo-only credentials for the simulated CLI login -- these are pyATS
# mock_device_cli devices, not real hardware; nothing here is a live secret.
LOGIN = {"username": "cisco", "password": "Lab@12345"}

# steps before the operator gate --  (offset_s, phase, topo, headline, detail)
_PRE = [
    (0, "steady-state", "before", "Primary site LAB-DC1 carrying production",
     "WLC-PRI active; {ap_count} APs joined; {client_count} clients; mobility tunnel to WLC-SEC Up."),
]

_GATE = {
    "headline": "Operator action required -- trigger the LAB-DC1 outage",
    "detail": "Choose how to fail WLC-PRI, run the commands on the device, then continue. "
              "This tool never sends config -- you do the shutdown.",
}

# each method: the CLI the operator runs, and the timeline that follows
_METHODS = {
    "switchport": {
        "label": "Shut the Port-channel10 + Port-channel11 member ports",
        "where": "DC1-CORE-SW1/2 -- Gi1/0/1-2 (Po10, to WLC-PRI); DC2-CORE-SW1/2 -- Gi1/0/1-2 (Po11, to WLC-SEC)",
        "summary": "Full L2 isolation on DC1's chassis -- CAPWAP to every AP drops almost at once, no "
                   "heartbeat wait. Po11's members are also shut and immediately re-enabled on DC2 as "
                   "part of the drill, to confirm WLC-SEC's own uplink is healthy before APs are sent "
                   "to it. AP discovery, CAPWAP join and client re-auth for the whole fleet still take "
                   "over two minutes.",
        "rto_s": 132,
        "commands": [
            "ssh cisco@DC1-CORE-SW1",
            "DC1-CORE-SW1# configure terminal",
            "DC1-CORE-SW1(config)#  interface range GigabitEthernet1/0/1-2",
            "DC1-CORE-SW1(config-if-range)#  shutdown",
            "DC1-CORE-SW1(config-if-range)#  end",
            "ssh cisco@DC1-CORE-SW2",
            "DC1-CORE-SW2# configure terminal",
            "DC1-CORE-SW2(config)#  interface range GigabitEthernet1/0/1-2",
            "DC1-CORE-SW2(config-if-range)#  shutdown",
            "DC1-CORE-SW2(config-if-range)#  end",
            "! Po10 (WLC-PRI) is down. Per the drill script, also cycling Po11 (WLC-SEC) on DC2:",
            "ssh cisco@DC2-CORE-SW1",
            "DC2-CORE-SW1# configure terminal",
            "DC2-CORE-SW1(config)#  interface range GigabitEthernet1/0/1-2",
            "DC2-CORE-SW1(config-if-range)#  shutdown",
            "DC2-CORE-SW1(config-if-range)#  no shutdown",
            "DC2-CORE-SW1(config-if-range)#  end",
            "! Po11 confirmed healthy and left up -- WLC-SEC stays reachable as the fallback controller.",
        ],
        "restore": [
            "DC1-CORE-SW1(config)#  interface range GigabitEthernet1/0/1-2",
            "DC1-CORE-SW1(config-if-range)#  no shutdown",
            "DC1-CORE-SW2(config)#  interface range GigabitEthernet1/0/1-2",
            "DC1-CORE-SW2(config-if-range)#  no shutdown",
        ],
        "steps": [
            (3, "event", "before", "Port-channel10 member links shut -- WLC-PRI isolated",
             "Both DC1 core uplinks down. WLC-PRI unreachable; CAPWAP to all {ap_count} APs drops at once."),
            (10, "detection", "transition", "APs lose CAPWAP transport",
             "No keepalive wait -- the L2 bundle is gone. APs immediately start controller discovery."),
            (35, "failover", "transition", "APs discover and select secondary controller",
             "Configured secondary WLC-SEC (192.168.100.20) answers. DTLS + CAPWAP join starts."),
            (90, "failover", "after", "APs CAPWAP-joined to WLC-SEC",
             "All {ap_count} migrated APs Registered on WLC-SEC (~90s to join), alongside the branch "
             "APs already there -- {ap_total} APs now served in total. Radios reset, SSIDs re-broadcast."),
            (118, "failover", "after", "Clients re-associate and re-authenticate",
             "802.1X clients re-auth against ISE via WLC-SEC. ~{client_count} migrated clients back to "
             "Run ({client_total} total now on WLC-SEC)."),
            (132, "recovered", "after", "Wireless service restored on the DR controller",
             "WLC-SEC serving {ap_total} APs / {client_total} clients in total ({ap_count} newly "
             "migrated from WLC-PRI) -- 2m12s after the shutdown. Mobility peer to WLC-PRI Down (expected)."),
        ],
    },
    "portchannel": {
        "label": "Shut the Port-channel10 + Port-channel11 bundles",
        "where": "DC1-CORE-SW1/2 interface Port-channel10 (to WLC-PRI); DC2-CORE-SW1/2 interface Port-channel11 (to WLC-SEC)",
        "summary": "The whole LACP bundle to WLC-PRI goes administratively down. Upstream "
                   "routing/HSRP has to reconverge before APs even notice, then the full 3x10s "
                   "fast-heartbeat timer runs -- the slowest, most realistic full-site-loss path. "
                   "Port-channel11 is also cycled on DC2 as part of the drill and immediately brought "
                   "back up, confirming WLC-SEC's uplink before APs are sent to it.",
        "rto_s": 168,
        "commands": [
            "! Port-channel10 is the only path in/out of WLC-PRI's wireless-management VLAN:",
            "ssh cisco@DC1-CORE-SW1",
            "DC1-CORE-SW1# configure terminal",
            "DC1-CORE-SW1(config)#  interface Port-channel10",
            "DC1-CORE-SW1(config-if)#  shutdown",
            "DC1-CORE-SW1(config-if)#  end",
            "ssh cisco@DC1-CORE-SW2",
            "DC1-CORE-SW2# configure terminal",
            "DC1-CORE-SW2(config)#  interface Port-channel10",
            "DC1-CORE-SW2(config-if)#  shutdown",
            "DC1-CORE-SW2(config-if)#  end",
            "! Po10 (WLC-PRI) is down. Per the drill script, also cycling Po11 (WLC-SEC) on DC2:",
            "ssh cisco@DC2-CORE-SW1",
            "DC2-CORE-SW1# configure terminal",
            "DC2-CORE-SW1(config)#  interface Port-channel11",
            "DC2-CORE-SW1(config-if)#  shutdown",
            "DC2-CORE-SW1(config-if)#  no shutdown",
            "DC2-CORE-SW1(config-if)#  end",
            "! Po11 confirmed healthy and left up -- WLC-SEC stays reachable as the fallback controller.",
        ],
        "restore": [
            "DC1-CORE-SW1(config)#  interface Port-channel10",
            "DC1-CORE-SW1(config-if)#  no shutdown",
            "DC1-CORE-SW2(config)#  interface Port-channel10",
            "DC1-CORE-SW2(config-if)#  no shutdown",
        ],
        "steps": [
            (3, "event", "before", "Port-channel10 shut on both DC1 cores -- WLC-PRI's uplink bundle down",
             "Po10 administratively down on DC1-CORE-SW1 + SW2. WLC-PRI's management and wireless-"
             "management VLANs have no routed path out."),
            (22, "detection", "before", "Upstream routing / HSRP reconverges",
             "DC1 core advertises the wireless-management subnet as withdrawn. APs still hold their "
             "CAPWAP state to WLC-PRI for a few more seconds."),
            (48, "detection", "transition", "APs miss primary controller heartbeats",
             "Fast heartbeat: 3 missed echoes at 10 s. APs now declare WLC-PRI DOWN."),
            (70, "failover", "transition", "APs discover and select secondary controller",
             "Configured secondary WLC-SEC (192.168.100.20) answers discovery. CAPWAP join starts."),
            (128, "failover", "after", "APs CAPWAP-joined to WLC-SEC",
             "All {ap_count} migrated APs Registered on WLC-SEC (~90s to join), alongside the branch "
             "APs already there -- {ap_total} APs now served in total. Radios reset, SSIDs re-broadcast."),
            (155, "failover", "after", "Clients re-associate and re-authenticate",
             "802.1X clients re-auth against ISE via WLC-SEC. ~{client_count} migrated clients back to "
             "Run ({client_total} total now on WLC-SEC)."),
            (168, "recovered", "after", "Wireless service restored on the DR controller",
             "WLC-SEC serving {ap_total} APs / {client_total} clients in total ({ap_count} newly "
             "migrated from WLC-PRI) -- 2m48s after the shutdown. Mobility peer to WLC-PRI Down (expected)."),
        ],
    },
}


def run() -> dict:
    before_ctrls = collect_all("healthy")
    after_ctrls = collect_all("failover")

    before = _snapshot(before_ctrls, "healthy")
    after = _snapshot(after_ctrls, "failover")

    # ap_count/client_count: WLC-PRI's OWN fleet -- the ones that actually
    # migrate. ap_total/client_total: WLC-SEC's fleet *after* absorbing them,
    # which also includes the branch APs/clients that were on WLC-SEC all
    # along. Conflating the two previously made the "after" narration claim
    # WLC-SEC was "serving {ap_count} APs" -- i.e. only the migrated 4 -- when
    # the branch sites mean it's actually serving all 8.
    ap_count = len(before["controllers"]["WLC-PRI"]["aps"])
    client_count = before["controllers"]["WLC-PRI"]["clients"]["count"]
    ap_total = len(after["controllers"]["WLC-SEC"]["aps"])
    client_total = after["controllers"]["WLC-SEC"]["clients"]["count"]

    def fmt(steps):
        out = []
        for off, phase, topo, headline, detail in steps:
            out.append({
                "t_plus_s": off,
                "clock": f"T+{off:02d}s",
                "phase": phase,
                "topo": topo,
                "headline": headline,
                "detail": detail.format(ap_count=ap_count, client_count=client_count,
                                         ap_total=ap_total, client_total=client_total),
            })
        return out

    methods = {
        key: {
            "label": m["label"], "where": m["where"], "summary": m["summary"],
            "commands": m["commands"], "restore": m["restore"],
            "rto_s": m["rto_s"], "steps": fmt(m["steps"]),
        }
        for key, m in _METHODS.items()
    }

    return {
        "mode": "failover-demo",
        "target": "healthy->failover",
        "before": before,
        "after": after,
        "pre": fmt(_PRE),
        "gate": _GATE,
        "login": LOGIN,
        "methods": methods,
        "timeline": fmt(_PRE),   # legacy key; JS builds the rest from methods
        "diff": _diff(before, after),
        "rpo_rto": {
            "modelled_rto_seconds": max(m["rto_s"] for m in _METHODS.values()),
            "basis": "C9800 AP N+1 fallback over a dual-homed Port-channel10/11 uplink. Member-port "
                     "shutdown -> CAPWAP drops almost at once but the fleet still needs ~2m12s to "
                     "discover, CAPWAP-join and re-auth on WLC-SEC. Port-channel10 bundle shutdown -> "
                     "routing/HSRP reconverges first, then 3x10s fast heartbeat + discovery, ~2m48s "
                     "RTO. Both drill scripts also cycle Port-channel11 on DC2 and bring it straight "
                     "back up, confirming WLC-SEC's own uplink before APs are sent to it -- the RTO "
                     "clock only runs against WLC-PRI's outage. No stateful client failover, so "
                     "clients reconnect (brief outage) rather than roam. Real N+1 fallbacks routinely "
                     "take minutes, not seconds -- both methods model at least a 2-minute gap before "
                     "APs are back on the DR controller.",
        },
    }


def _snapshot(ctrls: dict, scenario: str) -> dict:
    rep = readiness.evaluate(ctrls)
    topo = topology.build(ctrls, scenario)
    return {
        "scenario": scenario,
        "readiness": rep,
        "topology": topo,
        "controllers": {
            name: {
                "reachable": cd.reachable,
                "aps": [a["name"] for a in cd.facts.get("aps", [])],
                "clients": cd.facts.get("clients", {"count": 0}),
                "mobility": cd.facts.get("mobility", {}),
                "errors": cd.errors,
            }
            for name, cd in ctrls.items()
        },
    }


def _diff(before: dict, after: dict) -> dict:
    b_pri = set(before["controllers"]["WLC-PRI"]["aps"])
    b_sec = set(before["controllers"]["WLC-SEC"]["aps"])
    a_sec = set(after["controllers"]["WLC-SEC"]["aps"])

    moved = sorted(b_pri & a_sec)
    return {
        "aps_failed_over": moved,
        "aps_failed_over_count": len(moved),
        "aps_on_pri_before": sorted(b_pri),
        "aps_on_sec_before": sorted(b_sec),
        "aps_on_sec_after": sorted(a_sec),
        "clients_before_pri": before["controllers"]["WLC-PRI"]["clients"]["count"],
        "clients_after_sec": after["controllers"]["WLC-SEC"]["clients"]["count"],
        "readiness_before": before["readiness"]["overall"],
        "readiness_after": after["readiness"]["overall"],
        "primary_reachable_after": after["controllers"]["WLC-PRI"]["reachable"],
    }
