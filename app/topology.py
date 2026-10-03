"""
Build a wireless topology graph purely from what was discovered on the
controllers -- CDP neighbours, AP summary, AP CDP, mobility peers, AAA config.

Output is a {"nodes": [...], "edges": [...]} dict ready for vis-network in the
dashboard, or for any other renderer.
"""

from __future__ import annotations

from app.icons import icon_for

NODE_TYPES = ("controller", "core_switch", "access_switch", "ap", "aaa", "client_group")

# Cisco CLI interface-name abbreviations, for CML-style short edge labels.
_IF_ABBR = [
    ("TenGigabitEthernet", "Te"), ("GigabitEthernet", "Gi"),
    ("FortyGigabitEthernet", "Fo"), ("HundredGigE", "Hu"),
    ("TwentyFiveGigE", "Twe"), ("Port-channel", "Po"),
]

# deterministic, CML-style grid layout: column = site, row = device tier
_SITE_X = {"LAB-DC1": -280, "LAB-DC2": 280, "BRANCH-01": -520, "BRANCH-02": 520}
_ROW_Y = {"aaa": -320, "controller": -170, "core_switch": -40,
          "access_switch": 90, "ap": 220, "firewall": 320, "dmz": 400}
_LANE_GAP = 110

# the Guest WLAN's traffic path is a fixed, known design (every site anchors
# guest wireless to the edge firewall / DMZ) -- it isn't something any `show`
# command on the WLC reports, so it's added here as a labelled, illustrative
# segment, drawn only when a Guest SSID is actually present in the collected
# facts rather than unconditionally.
_GUEST_SSID = "Guest"


def _facts(cd):
    return getattr(cd, "facts", {}) or {}


def _short_if(name: str | None) -> str:
    name = name or ""
    for full, abbr in _IF_ABBR:
        if name.startswith(full):
            return abbr + name[len(full):]
    return name


def _uplink_label(local_if: str | None, remote_if: str | None) -> str:
    local_s, remote_s = _short_if(local_if), _short_if(remote_if)
    return local_s if local_s == remote_s else f"{local_s} ↔ {remote_s}"


def _layout(nodes: dict) -> None:
    """Assign fixed (x, y) per node -- site column x device-tier row, like a
    hand-drawn Cisco topology diagram, instead of letting force physics settle."""
    buckets: dict[tuple[str, str], list[str]] = {}
    for nid, n in nodes.items():
        site = n.get("site") or n.get("ap_site") or "SHARED"
        buckets.setdefault((site, n["type"]), []).append(nid)
    for (site, ntype), ids in buckets.items():
        base_x = _SITE_X.get(site, 0)
        y = _ROW_Y.get(ntype, 0)
        start = -(len(ids) - 1) * _LANE_GAP / 2
        for i, nid in enumerate(sorted(ids)):
            nodes[nid]["x"] = base_x + start + i * _LANE_GAP
            nodes[nid]["y"] = y


def build(controllers: dict, scenario: str) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(nid, label, ntype, **meta):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "type": ntype,
                          "icon": icon_for(ntype), **meta}
        else:
            nodes[nid].update({k: v for k, v in meta.items() if v is not None})
        return nid

    def add_edge(src, dst, etype, label="", status="up"):
        edges.append({"source": src, "target": dst, "type": etype,
                      "label": label, "status": status})

    pri = controllers.get("WLC-PRI")
    sec = controllers.get("WLC-SEC")

    # ---- controllers -----------------------------------------------------
    for cd, role in ((pri, "primary"), (sec, "DR / fallback")):
        if cd is None:
            continue
        status = "up" if cd.reachable else "down"
        ver = _facts(cd).get("version", {})
        add_node(cd.name, cd.name, "controller", site=cd.site, role=role,
                 ip=cd.mgmt_ip, mgmt_ip=cd.mgmt_ip, status=status,
                 platform=ver.get("platform") or "C9800",
                 sw_version=ver.get("version"), reachable=cd.reachable)

    # ---- inter-site mobility tunnel ------------------------------------
    anchor = pri if (pri and pri.reachable) else sec
    if anchor and anchor.reachable:
        mob = _facts(anchor).get("mobility", {})
        for p in mob.get("peers", []):
            if p.get("is_self"):
                continue
            peer_name = _controller_by_ip(controllers, p["ip"]) or p["ip"]
            add_node(peer_name, peer_name, "controller")
            add_edge(anchor.name, peer_name, "mobility",
                     f"mobility ({mob.get('group_name', '')})",
                     "up" if p["status"].lower() == "up" else "down")

    # ---- core switches from controller CDP -----------------------------
    for cd in (pri, sec):
        if cd is None or not cd.reachable:
            continue
        for n in _facts(cd).get("cdp", []):
            dev = (n.get("device_id") or "").split(".")[0]
            if not dev:
                continue
            ip = next(iter(n.get("ip", {})), None) if isinstance(n.get("ip"), dict) else None
            add_node(dev, dev, "core_switch", site=cd.site,
                     platform=(n.get("platform") or "").replace("cisco ", ""), ip=ip)
            add_edge(cd.name, dev, "uplink",
                     _uplink_label(n.get("local_interface"), n.get("remote_port")))

    # ---- APs + access switches ----------------------------------------
    # Which controller each AP is currently joined to.
    for cd in (pri, sec):
        if cd is None or not cd.reachable:
            continue
        aps = _facts(cd).get("aps", [])
        cdp_by_ap = {r["ap"]: r for r in _facts(cd).get("ap_cdp", [])}
        prim_by_ap = {r["ap"]: r for r in _facts(cd).get("ap_primary", [])}
        for ap in aps:
            add_node(ap["name"], ap["name"], "ap", model=ap.get("model"),
                     platform=ap.get("model"), ip=ap.get("ip"),
                     ap_site=ap.get("location"), state=ap.get("state"))
            add_edge(cd.name, ap["name"], "capwap", "CAPWAP",
                     "up" if str(ap.get("state", "")).lower() in ("registered", "joined") else "down")
            # configured secondary -> dashed standby edge
            pr = prim_by_ap.get(ap["name"])
            if pr and pr["sname"] and pr["sname"] != cd.name:
                add_node(pr["sname"], pr["sname"], "controller")
                add_edge(pr["sname"], ap["name"], "capwap_standby", "secondary", "standby")
            # access switch
            cn = cdp_by_ap.get(ap["name"])
            if cn and cn.get("neighbor"):
                sw = cn["neighbor"].split(".")[0]
                add_node(sw, sw, "access_switch", site=ap.get("location"))
                add_edge(sw, ap["name"], "access", _short_if(cn.get("neighbor_port", "")))

    # ---- AAA / ISE ---------------------------------------------------
    for cd in (pri, sec):
        if cd is None or not cd.reachable:
            continue
        for s in _facts(cd).get("aaa", []):
            nid = f"ise:{s.get('host')}"
            add_node(nid, s.get("name") or s.get("host"), "aaa", ip=s.get("host"))
            add_edge(cd.name, nid, "radius", "RADIUS",
                     "up" if (s.get("state") or "").upper() == "UP" else "down")

    # ---- Guest WLAN -> firewall -> DMZ (illustrative; drawn only when a
    # Guest SSID is actually present on a reachable controller) -----------
    guest_sources = [cd for cd in (pri, sec)
                     if cd is not None and cd.reachable
                     and any(w.get("ssid") == _GUEST_SSID for w in _facts(cd).get("wlans", []))]
    if guest_sources:
        add_node("FW-EDGE", "EDGE-FW01", "firewall")
        add_node("DMZ-ZONE", "DMZ Zone", "dmz")
        add_edge("FW-EDGE", "DMZ-ZONE", "guest_dmz", "Guest (Vlan54)")
        for cd in guest_sources:
            add_edge(cd.name, "FW-EDGE", "guest_dmz", "Guest WLAN")

    _layout(nodes)

    return {
        "scenario": scenario,
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "controllers": sum(n["type"] == "controller" for n in nodes.values()),
            "aps": sum(n["type"] == "ap" for n in nodes.values()),
            "switches": sum(n["type"] in ("core_switch", "access_switch") for n in nodes.values()),
        },
    }


def _controller_by_ip(controllers: dict, ip: str) -> str | None:
    for cd in controllers.values():
        if cd is not None and cd.mgmt_ip == ip:
            return cd.name
    return None
