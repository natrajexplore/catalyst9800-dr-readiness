"""
Build a wireless topology graph purely from what was discovered on the
controllers -- CDP neighbours, AP summary, AP CDP, mobility peers, AAA config.

Output is a {"nodes": [...], "edges": [...]} dict ready for vis-network in the
dashboard, or for any other renderer.
"""

from __future__ import annotations

from app.icons import icon_for

NODE_TYPES = ("controller", "core_switch", "access_switch", "ap", "aaa", "client_group")


def _facts(cd):
    return getattr(cd, "facts", {}) or {}


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
            add_node(dev, dev, "core_switch",
                     platform=(n.get("platform") or "").replace("cisco ", ""), ip=ip)
            add_edge(cd.name, dev, "uplink",
                     f"{n.get('local_interface', '')} -> {n.get('remote_port', '')}")

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
                add_node(sw, sw, "access_switch")
                add_edge(sw, ap["name"], "access", cn.get("neighbor_port", ""))

    # ---- AAA / ISE ---------------------------------------------------
    for cd in (pri, sec):
        if cd is None or not cd.reachable:
            continue
        for s in _facts(cd).get("aaa", []):
            nid = f"ise:{s.get('host')}"
            add_node(nid, s.get("name") or s.get("host"), "aaa", ip=s.get("host"))
            add_edge(cd.name, nid, "radius", "RADIUS",
                     "up" if (s.get("state") or "").upper() == "UP" else "down")

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
