"""
Scripted DR failover -- operator-driven.

The demo runs to a GATE and then waits for the operator to choose HOW to fail
the primary controller, and to actually run the shutdown on the device:

  * "switchport" -- shut WLC-PRI's uplink ports on the DC1 core switches
                    (full L2 isolation; CAPWAP drops instantly)
  * "svi"        -- shut WLC-PRI's L3 VLAN interface / wireless-management SVI
                    (link stays up, management + CAPWAP subnet goes dark;
                     APs wait out the fast-heartbeat timer first)

"before" really connects to the healthy mocks, "after" to the failover mocks.
The per-method timeline in between is the narrated model of the transition, with
timings from real Catalyst 9800 AP N+1 fallback behaviour.
"""

from __future__ import annotations

from app import readiness, topology
from app.collectors import collect_all

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
        "label": "Shut WLC-PRI uplink switchports",
        "where": "DC1-CORE-SW1 / SW2  (the ports facing WLC-PRI)",
        "summary": "Full L2 isolation. CAPWAP to every AP drops immediately -- no heartbeat wait.",
        "rto_s": 55,
        "commands": [
            "DC1-CORE-SW1# configure terminal",
            "DC1-CORE-SW1(config)#  interface TenGigabitEthernet1/0/1",
            "DC1-CORE-SW1(config-if)#  shutdown",
            "DC1-CORE-SW2# configure terminal",
            "DC1-CORE-SW2(config)#  interface TenGigabitEthernet1/0/1",
            "DC1-CORE-SW2(config-if)#  shutdown",
        ],
        "restore": [
            "DC1-CORE-SW1(config)#  interface TenGigabitEthernet1/0/1",
            "DC1-CORE-SW1(config-if)#  no shutdown",
            "DC1-CORE-SW2(config)#  interface TenGigabitEthernet1/0/1",
            "DC1-CORE-SW2(config-if)#  no shutdown",
        ],
        "steps": [
            (3, "event", "before", "WLC-PRI uplink ports shut -- controller isolated",
             "Both core uplinks down. WLC-PRI unreachable; CAPWAP to all {ap_count} APs drops at once."),
            (7, "detection", "transition", "APs lose CAPWAP transport",
             "No keepalive wait -- the L2 path is gone. APs immediately start controller discovery."),
            (16, "failover", "transition", "APs discover and select secondary controller",
             "Configured secondary WLC-SEC (192.168.100.20) answers. DTLS + CAPWAP join starts."),
            (26, "failover", "after", "APs CAPWAP-joined to WLC-SEC",
             "All {ap_count} APs Registered on WLC-SEC. Radios reset, SSIDs re-broadcast."),
            (44, "failover", "after", "Clients re-associate and re-authenticate",
             "802.1X clients re-auth against ISE via WLC-SEC. ~{client_count} clients back to Run."),
            (55, "recovered", "after", "Wireless service restored on the DR controller",
             "WLC-SEC serving {ap_count} APs / {client_count} clients. Mobility peer to WLC-PRI Down (expected)."),
        ],
    },
    "svi": {
        "label": "Shut the DC core VLAN 200 SVI (blackhole WLC-PRI's subnet)",
        "where": "DC1-CORE-SW1 + DC1-CORE-SW2  interface Vlan200",
        "summary": "Link stays up but the wireless-management subnet loses its only routed "
                   "exit. APs miss 3x fast heartbeat (~30 s) before failing over.",
        "rto_s": 95,
        "commands": [
            "! On the DC1 core pair -- the only L3 path in/out of VLAN 200:",
            "DC1-CORE-SW1# configure terminal",
            "DC1-CORE-SW1(config)#  interface Vlan200",
            "DC1-CORE-SW1(config-if)#  shutdown",
            "DC1-CORE-SW2# configure terminal",
            "DC1-CORE-SW2(config)#  interface Vlan200",
            "DC1-CORE-SW2(config-if)#  shutdown",
        ],
        "restore": [
            "DC1-CORE-SW1(config)#  interface Vlan200",
            "DC1-CORE-SW1(config-if)#  no shutdown",
            "DC1-CORE-SW2(config)#  interface Vlan200",
            "DC1-CORE-SW2(config-if)#  no shutdown",
        ],
        "steps": [
            (3, "event", "before", "DC core VLAN 200 SVI shut -- WLC-PRI subnet blackholed",
             "SVI down on both DC1 cores. Link is still up but CAPWAP + management to WLC-PRI is unreachable."),
            (13, "detection", "before", "APs miss primary controller heartbeats",
             "Fast heartbeat: 3 missed echoes at 10 s. APs still on WLC-PRI CAPWAP, data plane intact."),
            (33, "detection", "transition", "APs declare primary controller DOWN",
             "Primary discovery timer expires (~30 s). APs begin controller discovery."),
            (40, "failover", "transition", "APs discover and select secondary controller",
             "Configured secondary WLC-SEC (192.168.100.20) answers discovery. CAPWAP join starts."),
            (52, "failover", "after", "APs CAPWAP-joined to WLC-SEC",
             "All {ap_count} APs Registered on WLC-SEC. Radios reset, SSIDs re-broadcast."),
            (74, "failover", "after", "Clients re-associate and re-authenticate",
             "802.1X clients re-auth against ISE via WLC-SEC. ~{client_count} clients back to Run."),
            (95, "recovered", "after", "Wireless service restored on the DR controller",
             "WLC-SEC serving {ap_count} APs / {client_count} clients. Mobility peer to WLC-PRI Down (expected)."),
        ],
    },
}


def run() -> dict:
    before_ctrls = collect_all("healthy")
    after_ctrls = collect_all("failover")

    before = _snapshot(before_ctrls, "healthy")
    after = _snapshot(after_ctrls, "failover")

    ap_count = len(before["controllers"]["WLC-PRI"]["aps"])
    client_count = before["controllers"]["WLC-PRI"]["clients"]["count"]

    def fmt(steps):
        out = []
        for off, phase, topo, headline, detail in steps:
            out.append({
                "t_plus_s": off,
                "clock": f"T+{off:02d}s",
                "phase": phase,
                "topo": topo,
                "headline": headline,
                "detail": detail.format(ap_count=ap_count, client_count=client_count),
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
        "methods": methods,
        "timeline": fmt(_PRE),   # legacy key; JS builds the rest from methods
        "diff": _diff(before, after),
        "rpo_rto": {
            "modelled_rto_seconds": max(m["rto_s"] for m in _METHODS.values()),
            "basis": "C9800 AP N+1 fallback. Switchport shut -> CAPWAP drops instantly (~55 s RTO). "
                     "SVI shut -> APs wait 3x10 s fast heartbeat + ~30 s discovery first (~95 s RTO). "
                     "No stateful client failover, so clients reconnect (brief outage).",
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
