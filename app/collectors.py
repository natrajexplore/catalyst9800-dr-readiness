"""
Fact collection: run the DR-relevant ``show`` commands on a controller and
normalise the output into a single ``facts`` dict the readiness engine and the
topology builder both consume.

Strategy per command:
  1. ``device.execute(cmd)``           -- always, keeps the raw transcript
  2. ``device.parse(cmd)`` (Genie)     -- when a reliable parser exists
  3. app/parsers.py fallback           -- for eWLC output Genie can't take

The normalised ``facts`` schema is intentionally small and flat so the rest of
the toolkit never has to know which of the three paths produced a value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app import parsers
from app.connect import ConnectResult, connect_device, load_testbed

# Read-only guard: this toolkit must never do anything to a production controller
# except read from it. Every command it issues has to match this.
READ_ONLY_PREFIXES = ("show ", "dir ", "more ")


class UnsafeCommandError(RuntimeError):
    """Raised if anything tries to run a non-read-only command on a controller."""


def _guard(cmd: str) -> str:
    if not cmd.strip().lower().startswith(READ_ONLY_PREFIXES):
        raise UnsafeCommandError(
            f"refused non-read-only command: {cmd!r} "
            f"(allowed prefixes: {', '.join(READ_ONLY_PREFIXES)})")
    return cmd


# Commands we pull on every controller. ``genie`` = trust device.parse().
COMMANDS: list[tuple[str, bool]] = [
    ("show version", False),
    ("show redundancy", True),
    ("show wireless redundancy summary", False),
    ("show ip interface brief", True),
    ("show wlan summary", True),
    ("show ap summary", True),
    ("show ap config general", False),
    ("show ap primary list", False),
    ("show wireless client summary", False),
    ("show wireless mobility summary", False),
    ("show wireless stats ap join summary", True),
    ("show ap cdp neighbor", True),
    ("show cdp neighbors detail", True),
    ("show aaa servers", False),
]


@dataclass
class ControllerData:
    name: str
    site: str
    mgmt_ip: str
    scenario: str
    reachable: bool
    transcript: list[str] = field(default_factory=list)
    raw: dict[str, str] = field(default_factory=dict)
    genie: dict[str, object] = field(default_factory=dict)
    facts: dict[str, object] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def collect_all(scenario: str = "healthy",
                devices: tuple[str, ...] = ("WLC-PRI", "WLC-SEC")) -> dict:
    """Connect to every controller for *scenario* and return {name: ControllerData}."""
    testbed = load_testbed(scenario)
    out: dict[str, ControllerData] = {}
    for name in devices:
        with connect_device(testbed, name, scenario) as conn:
            out[name] = collect(conn)
    return out


def collect(conn: ConnectResult) -> ControllerData:
    """Collect and normalise everything from one (already connected) controller."""
    data = ControllerData(
        name=conn.name, site=conn.site, mgmt_ip=conn.mgmt_ip,
        scenario=conn.scenario, reachable=conn.reachable,
        transcript=list(conn.transcript),
    )
    if not conn.reachable:
        data.errors.append(conn.error or "unreachable")
        data.facts = _empty_facts()
        return data

    dev = conn.device
    for cmd, use_genie in COMMANDS:
        try:
            data.raw[cmd] = dev.execute(_guard(cmd))
        except Exception as exc:  # noqa: BLE001
            data.errors.append(f"{cmd}: execute failed ({exc})")
            continue
        if use_genie:
            try:
                data.genie[cmd] = dev.parse(_guard(cmd))
            except Exception as exc:  # noqa: BLE001
                data.notes.append(f"{cmd}: used text fallback ({type(exc).__name__})")

    data.facts = _normalise(data)
    return data


# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #
def _empty_facts() -> dict:
    return {
        "version": {}, "redundancy": {}, "wireless_redundancy": {},
        "interfaces": {}, "wlans": [], "aps": [], "ap_primary": [],
        "ap_join": [], "clients": {"count": 0, "excluded": 0, "per_wlan": {}},
        "mobility": {"peers": []}, "ap_cdp": [], "cdp": [], "aaa": [],
    }


def _normalise(data: ControllerData) -> dict:
    raw = data.raw
    genie = data.genie
    f = _empty_facts()

    f["version"] = parsers.parse_version(raw.get("show version", ""))
    f["redundancy"] = _redundancy(genie.get("show redundancy"),
                                  raw.get("show redundancy", ""))
    f["wireless_redundancy"] = parsers.parse_wireless_redundancy(
        raw.get("show wireless redundancy summary", ""))
    f["interfaces"] = _interfaces(genie.get("show ip interface brief"))
    f["wlans"] = _wlans(genie.get("show wlan summary"))
    f["aps"] = _aps(genie.get("show ap summary"))
    f["ap_primary"] = parsers.parse_ap_primary_list(raw.get("show ap primary list", ""))
    f["ap_join"] = parsers.parse_ap_join_summary(
        raw.get("show wireless stats ap join summary", ""))
    f["clients"] = parsers.parse_client_summary(
        raw.get("show wireless client summary", ""))
    f["mobility"] = parsers.parse_mobility_summary(
        raw.get("show wireless mobility summary", ""))
    f["ap_cdp"] = _ap_cdp(genie.get("show ap cdp neighbor"),
                          raw.get("show ap cdp neighbor", ""))
    f["cdp"] = _cdp(genie.get("show cdp neighbors detail"))
    f["aaa"] = parsers.parse_aaa_servers(raw.get("show aaa servers", ""))
    return f


def _redundancy(g, raw_text: str) -> dict:
    base = parsers.parse_redundancy(raw_text)
    if isinstance(g, dict) and g.get("red_sys_info"):
        info = g["red_sys_info"]
        base["configured_mode"] = (info.get("conf_red_mode") or base["configured_mode"]).lower()
        base["operational_mode"] = (info.get("oper_red_mode") or base["operational_mode"]).lower()
        base["communications"] = info.get("communications") or base["communications"]
        base["switchovers"] = info.get("switchovers_system_experienced", base["switchovers"])
        slots = g.get("slot", {})
        st = [v.get("curr_sw_state") for v in slots.values() if isinstance(v, dict)]
        if st:
            base["active_state"] = st[0]
        if len(st) > 1:
            base["peer_state"] = st[1]
    return base


def _interfaces(g) -> dict:
    out: dict[str, dict] = {}
    if isinstance(g, dict):
        for name, d in g.get("interface", {}).items():
            out[name] = {
                "ip": d.get("ip_address"),
                "status": d.get("status"),
                "protocol": d.get("protocol"),
            }
    return out


def _wlans(g) -> list[dict]:
    out = []
    if isinstance(g, dict):
        for wid, d in g.get("wlan_summary", {}).get("wlan_id", {}).items():
            out.append({
                "id": wid,
                "profile": d.get("profile_name"),
                "ssid": d.get("ssid"),
                "status": d.get("status"),
                "security": d.get("security"),
            })
    return sorted(out, key=lambda w: int(w["id"]))


def _aps(g) -> list[dict]:
    out = []
    if isinstance(g, dict):
        for name, d in g.get("ap_name", {}).items():
            out.append({
                "name": name,
                "model": d.get("ap_model"),
                "ip": d.get("ap_ip_address") or d.get("ip_address"),
                "state": d.get("state"),
                "ethernet_mac": d.get("ethernet_mac"),
                "radio_mac": d.get("radio_mac"),
                "location": d.get("location"),
            })
    return sorted(out, key=lambda a: a["name"])


def _ap_cdp(g, raw_text: str) -> list[dict]:
    out = []
    if isinstance(g, dict):
        for name, d in g.get("ap_name", {}).items():
            out.append({
                "ap": name,
                "ap_ip": d.get("ap_ip"),
                "neighbor": d.get("neighbor_name"),
                "neighbor_port": d.get("neighbor_port"),
            })
    return sorted(out, key=lambda x: x["ap"])


def _cdp(g) -> list[dict]:
    out = []
    if isinstance(g, dict):
        for idx, d in g.get("index", {}).items():
            out.append({
                "device_id": d.get("device_id"),
                "ip": (d.get("management_addresses") or d.get("entry_addresses") or {}),
                "platform": d.get("platform"),
                "local_interface": d.get("local_interface"),
                "remote_port": d.get("port_id"),
            })
    return out
