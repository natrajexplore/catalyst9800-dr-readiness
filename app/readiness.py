"""
DR readiness engine.

Given the collected facts for the primary and the DR controller, decide whether
the wireless estate could actually survive the loss of the primary site. Each
check returns a verdict plus the evidence it was based on and, on failure, what
to do about it.

A check is PASS / WARN / FAIL. Overall readiness is the worst verdict, and a
percentage score (PASS=1, WARN=0.5, FAIL=0) for the dashboard gauge.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_RANK = {PASS: 0, WARN: 1, FAIL: 2}
_SCORE = {PASS: 1.0, WARN: 0.5, FAIL: 0.0}

PRIMARY = "WLC-PRI"
SECONDARY = "WLC-SEC"


@dataclass
class Check:
    id: str
    title: str
    category: str
    status: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    remediation: str = ""


def _mk(cid, title, cat, status, detail, evidence=None, remediation=""):
    return Check(cid, title, cat, status, detail, list(evidence or []), remediation)


# --------------------------------------------------------------------------- #
def evaluate(controllers: dict) -> dict:
    """controllers: {name: ControllerData}. Returns a plain-dict report."""
    pri = controllers.get(PRIMARY)
    sec = controllers.get(SECONDARY)
    checks: list[Check] = []

    checks.append(_chk_reachability(pri, sec))
    checks.append(_chk_software_parity(pri, sec))
    checks.append(_chk_sso(pri))
    checks.append(_chk_sso(sec))
    checks.append(_chk_wireless_ha(sec))
    checks.append(_chk_mobility(pri, sec))
    checks.append(_chk_ap_fallback(pri, sec))
    checks.append(_chk_wlan_parity(pri, sec))
    checks.append(_chk_aaa(pri, sec))
    checks.append(_chk_mgmt_interfaces(pri, sec))
    checks.append(_chk_dr_headroom(pri, sec))

    checks = [c for c in checks if c is not None]
    overall = max((c.status for c in checks), key=lambda s: _RANK[s])
    score = round(100 * sum(_SCORE[c.status] for c in checks) / len(checks), 1)

    return {
        "overall": overall,
        "score": score,
        "counts": {
            "pass": sum(c.status == PASS for c in checks),
            "warn": sum(c.status == WARN for c in checks),
            "fail": sum(c.status == FAIL for c in checks),
            "total": len(checks),
        },
        "checks": [asdict(c) for c in checks],
    }


# --------------------------------------------------------------------------- #
def _facts(cd):
    return getattr(cd, "facts", {}) or {}


def _chk_reachability(pri, sec):
    ev, bad = [], []
    for cd, label in ((pri, PRIMARY), (sec, SECONDARY)):
        if cd is None:
            bad.append(f"{label} not in testbed")
            continue
        state = "reachable" if cd.reachable else f"UNREACHABLE ({'; '.join(cd.errors) or 'no session'})"
        ev.append(f"{label} @ {cd.mgmt_ip} ({cd.site}): {state}")
        if not cd.reachable:
            bad.append(label)
    if not bad:
        return _mk("reachability", "Both controllers reachable over CLI", "Connectivity",
                   PASS, "SSH/CLI session established to WLC-PRI and WLC-SEC.", ev)
    return _mk("reachability", "Controller reachability", "Connectivity", FAIL,
               f"Cannot manage: {', '.join(bad)}.", ev,
               "Restore management-plane reachability before relying on DR; a controller "
               "you cannot see is a controller you cannot fail over to.")


def _chk_software_parity(pri, sec):
    if not (pri and sec and pri.reachable and sec.reachable):
        return None
    vp = _facts(pri).get("version", {}).get("version")
    vs = _facts(sec).get("version", {}).get("version")
    ev = [f"{PRIMARY}: IOS-XE {vp}", f"{SECONDARY}: IOS-XE {vs}"]
    if vp and vs and vp == vs:
        return _mk("software_parity", "Controller software versions match", "Software",
                   PASS, f"Both controllers run IOS-XE {vp}.", ev)
    return _mk("software_parity", "Controller software versions match", "Software", FAIL,
               f"Version mismatch: {vp} vs {vs}.", ev,
               "Align both controllers on the same IOS-XE train. APs will not join a "
               "controller whose version is incompatible with their running image.")


def _chk_sso(cd):
    if cd is None or not cd.reachable:
        return None
    r = _facts(cd).get("redundancy", {})
    ev = [
        f"{cd.name}: configured={r.get('configured_mode')} operational={r.get('operational_mode')}",
        f"{cd.name}: active={r.get('active_state')} peer={r.get('peer_state')} comms={r.get('communications')}",
        f"{cd.name}: switchovers experienced={r.get('switchovers')}",
    ]
    ok = (
        r.get("configured_mode") == "sso"
        and r.get("operational_mode") == "sso"
        and (r.get("active_state") or "").upper() == "ACTIVE"
        and "STANDBY HOT" in (r.get("peer_state") or "").upper()
        and (r.get("communications") or "").lower() == "up"
    )
    if ok:
        return _mk(f"sso_{cd.name.lower()}", f"{cd.name} SSO HA pair healthy", "Redundancy",
                   PASS, f"{cd.name} chassis pair in SSO, standby HOT, RP link up.", ev)
    return _mk(f"sso_{cd.name.lower()}", f"{cd.name} SSO HA pair healthy", "Redundancy", FAIL,
               f"{cd.name} redundancy not fully converged.", ev,
               "Investigate the HA pair (show redundancy / show chassis) before a DR event; "
               "a degraded pair can drop config or fail the switchover.")


def _chk_wireless_ha(sec):
    if sec is None or not sec.reachable:
        return None
    w = _facts(sec).get("wireless_redundancy", {})
    ev = [
        f"{SECONDARY}: mode={w.get('mode')} gateway={w.get('gateway_reachability')}",
        f"{SECONDARY}: RMI local/peer={w.get('rmi_local')}/{w.get('rmi_peer')} "
        f"RP local/peer={w.get('rp_local')}/{w.get('rp_peer')}",
    ]
    up = lambda v: (v or "").upper() == "UP"  # noqa: E731
    if (w.get("gateway_reachability") or "").upper() == "REACHABLE" and up(w.get("rmi_local")) and up(w.get("rp_local")):
        return _mk("wireless_ha_sec", "DR controller wireless HA (RMI+RP) healthy",
                   "Redundancy", PASS,
                   "WLC-SEC RMI+RP links up and gateway reachable.", ev)
    return _mk("wireless_ha_sec", "DR controller wireless HA (RMI+RP) healthy",
               "Redundancy", WARN,
               "WLC-SEC RMI/RP not fully healthy.", ev,
               "Check 'show wireless redundancy summary' on WLC-SEC; RMI gateway loss "
               "can trigger an unnecessary standby takeover during the DR window.")


def _chk_mobility(pri, sec):
    if not (pri and pri.reachable):
        # judge from whichever controller we can see
        anchor = sec
    else:
        anchor = pri
    if anchor is None or not anchor.reachable:
        return None
    mob = _facts(anchor).get("mobility", {})
    peers = mob.get("peers", [])
    real_peers = [p for p in peers if not p.get("is_self")]
    ev = [f"{anchor.name}: mobility group '{mob.get('group_name')}'"]
    for p in peers:
        ev.append(f"  {p['ip']}  status={p['status']}  pmtu={p['pmtu']}"
                  + ("  (self)" if p.get("is_self") else ""))
    up_peers = [p for p in real_peers if p["status"].lower() == "up"]
    if real_peers and len(up_peers) == len(real_peers):
        return _mk("mobility_tunnel", "Inter-site mobility tunnel established", "DR data path",
                   PASS, f"{anchor.name} mobility peering to the DR controller is Up.", ev)
    if not real_peers:
        return _mk("mobility_tunnel", "Inter-site mobility tunnel established", "DR data path",
                   FAIL, "No mobility peer configured toward the DR controller.", ev,
                   "Add the DR controller to the mobility group on both sides. Without it, "
                   "client roaming and guest anchoring break the moment you fail over.")
    return _mk("mobility_tunnel", "Inter-site mobility tunnel established", "DR data path",
               WARN, f"{anchor.name}: {len(up_peers)}/{len(real_peers)} mobility peers Up.", ev,
               "Bring the mobility tunnel up before the DR event (UDP 16666/16667 between "
               "wireless management IPs).")


def _chk_ap_fallback(pri, sec):
    """
    Every AP needs a distinct, configured secondary controller -- DC-local APs
    fail over WLC-PRI -> WLC-SEC; branch/spoke FlexConnect APs legitimately run
    the other way round (primary WLC-SEC, secondary WLC-PRI). Either direction
    is fine as long as it's set and isn't a no-op (secondary == primary).
    """
    src = pri if (pri and pri.reachable) else sec
    if src is None or not src.reachable:
        return None
    import re
    rows = _facts(src).get("ap_primary", [])
    ap_cfg_raw = src.raw.get("show ap config general", "")
    fallback_enabled = bool(re.search(r"AP Fallback\s*:\s*Enabled", ap_cfg_raw, re.I))
    ev = [f"{src.name}: 'show ap primary list' has {len(rows)} AP(s)"]
    misconfigured = []
    for r in rows:
        ev.append(f"  {r['ap']:<12} primary={r['pname']}({r['pip']})  secondary={r['sname']}({r['sip']})")
        if not r["sname"] or r["sname"] == r["pname"]:
            misconfigured.append(r["ap"])
    ev.append(f"{src.name}: AP Fallback = {'Enabled' if fallback_enabled else 'NOT Enabled'}")
    if rows and not misconfigured and fallback_enabled:
        return _mk("ap_fallback", "Every AP has a configured N+1 fallback controller", "AP failover",
                   PASS, f"All {len(rows)} APs have a distinct secondary controller configured, "
                   "AP fallback enabled.", ev)
    if not rows:
        return _mk("ap_fallback", "Every AP has a configured N+1 fallback controller", "AP failover", FAIL,
                   "No AP primary/secondary controller assignments found.", ev,
                   "Configure a secondary controller on every AP -- directly, or via the AP "
                   "join profile's 'capwap backup secondary' -- so APs know where to go when "
                   "the primary drops.")
    status = FAIL if misconfigured else WARN
    return _mk("ap_fallback", "Every AP has a configured N+1 fallback controller", "AP failover", status,
               (f"{len(misconfigured)} AP(s) missing a distinct secondary controller: "
                f"{', '.join(misconfigured)}. " if misconfigured else "")
               + ("AP fallback disabled." if not fallback_enabled else ""),
               ev,
               "Set a distinct secondary controller on every AP and enable AP fallback; otherwise "
               "those APs will not return automatically and may not fail over at all.")


def _chk_wlan_parity(pri, sec):
    if not (pri and sec and pri.reachable and sec.reachable):
        return None
    def sig(cd):
        return {(w["id"], w["ssid"], w["security"], w["status"]) for w in _facts(cd).get("wlans", [])}
    sp, ss = sig(pri), sig(sec)
    ev = [f"{PRIMARY}: {len(sp)} WLAN(s) " + ", ".join(sorted(w[1] for w in sp)),
          f"{SECONDARY}: {len(ss)} WLAN(s) " + ", ".join(sorted(w[1] for w in ss))]
    if sp and sp == ss:
        return _mk("wlan_parity", "WLAN / SSID config in sync across controllers", "Config parity",
                   PASS, f"Identical {len(sp)}-WLAN policy on both controllers.", ev)
    diff = sp ^ ss
    return _mk("wlan_parity", "WLAN / SSID config in sync across controllers", "Config parity",
               FAIL, f"{len(diff)} WLAN attribute(s) differ between controllers.", ev,
               "Re-sync WLAN/policy config (ideally from a config template / NCC). Clients "
               "will not authenticate on the DR controller if the SSID or security differs.")


def _chk_aaa(pri, sec):
    checks_ok, ev = True, []
    seen = False
    for cd, label in ((pri, PRIMARY), (sec, SECONDARY)):
        if cd is None or not cd.reachable:
            continue
        seen = True
        servers = _facts(cd).get("aaa", [])
        for s in servers:
            ev.append(f"{label}: {s.get('name')} {s.get('host')} -> {s.get('state')}")
            if (s.get("state") or "").upper() != "UP":
                checks_ok = False
        if not servers:
            checks_ok = False
            ev.append(f"{label}: no RADIUS servers configured")
    if not seen:
        return None
    if checks_ok:
        return _mk("aaa", "RADIUS (ISE) reachable from both controllers", "AAA", PASS,
                   "All configured RADIUS servers are UP on every reachable controller.", ev)
    return _mk("aaa", "RADIUS (ISE) reachable from both controllers", "AAA", FAIL,
               "One or more RADIUS servers are not UP.", ev,
               "The DR controller needs its own working path to ISE. Confirm NAD entries for "
               "WLC-SEC's source IP and that ISE is reachable from LAB-DC2.")


def _chk_mgmt_interfaces(pri, sec):
    if not (pri and sec and pri.reachable and sec.reachable):
        return None
    def mgmt(cd):
        intf = _facts(cd).get("interfaces", {})
        return {n: d for n, d in intf.items() if n.startswith("Vlan") and d.get("status") == "up"}
    mp, ms = mgmt(pri), mgmt(sec)
    ev = [f"{PRIMARY}: " + ", ".join(f"{n} {d['ip']} {d['status']}" for n, d in mp.items()),
          f"{SECONDARY}: " + ", ".join(f"{n} {d['ip']} {d['status']}" for n, d in ms.items())]
    if mp and ms and set(mp) == set(ms):
        return _mk("mgmt_interfaces", "Management & wireless-management interfaces up", "Interfaces",
                   PASS, "Same management VLANs up on both controllers.", ev)
    return _mk("mgmt_interfaces", "Management & wireless-management interfaces up", "Interfaces",
               WARN, "Management VLAN set differs or an interface is down.", ev,
               "Keep the management/wireless-management VLAN design symmetric so AP CAPWAP and "
               "mobility keep working after failover.")


def _chk_dr_headroom(pri, sec):
    if not (sec and sec.reachable):
        return None
    src = pri if (pri and pri.reachable) else sec
    ap_load = len(_facts(src).get("aps", [])) if src else 0
    cli_load = _facts(src).get("clients", {}).get("count", 0) if src else 0
    # C9800-CL small deployment reference limits
    ap_limit, client_limit = 1000, 10000
    ev = [
        f"Load to absorb (from {src.name if src else '?'}): {ap_load} APs, {cli_load} clients",
        f"WLC-SEC platform reference limit: {ap_limit} APs / {client_limit} clients",
        f"WLC-SEC currently carrying: {len(_facts(sec).get('aps', []))} APs, "
        f"{_facts(sec).get('clients', {}).get('count', 0)} clients",
    ]
    projected_ap = ap_load + len(_facts(sec).get("aps", []))
    if projected_ap <= ap_limit * 0.8:
        return _mk("dr_headroom", "DR controller has capacity for the failed-over load",
                   "Capacity", PASS,
                   f"Post-failover ~{projected_ap} APs is within WLC-SEC capacity.", ev)
    return _mk("dr_headroom", "DR controller has capacity for the failed-over load", "Capacity",
               WARN, f"Post-failover AP count (~{projected_ap}) is close to platform limits.", ev,
               "Confirm the DR controller's licensing (AP count) and platform sizing cover the "
               "full primary-site load, not just steady state.")
