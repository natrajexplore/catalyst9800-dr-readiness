"""
Lightweight text parsers for the handful of ``show`` commands where the bundled
Genie parser is not a clean fit for eWLC output (or does not exist).

Each function takes raw CLI text and returns a plain dict/list. They are only
used as a fallback -- collectors.py tries the real Genie parser first.
"""

from __future__ import annotations

import re


def parse_version(text: str) -> dict:
    out: dict = {}
    m = re.search(r"Version\s+(\d+\.\d+\.\d+[A-Za-z0-9.]*)", text)
    if m:
        out["version"] = m.group(1)
    m = re.search(r"cisco\s+(\S+)\s+\((\S+)\)\s+processor", text)
    if m:
        out["platform"] = m.group(1)
    m = re.search(r"(\S+)\s+uptime is\s+(.+)", text)
    if m:
        out["hostname"] = m.group(1)
        out["uptime"] = m.group(2).strip()
    m = re.search(r"System image file is\s+\"?([^\"\n]+)", text)
    if m:
        out["image"] = m.group(1).strip()
    return out


def parse_redundancy(text: str) -> dict:
    """Minimal `show redundancy` reader (fallback for Genie ShowRedundancy)."""
    def grab(pat: str) -> str | None:
        m = re.search(pat, text, re.I)
        return m.group(1).strip() if m else None

    out = {
        "configured_mode": (grab(r"Configured Redundancy Mode\s*=\s*(\S+)") or "").lower(),
        "operational_mode": (grab(r"Operating Redundancy Mode\s*=\s*(\S+)") or "").lower(),
        "communications": grab(r"Communications\s*=\s*(\S+)"),
        "maintenance_mode": grab(r"Maintenance Mode\s*=\s*(\S+)"),
        "switchovers": grab(r"Switchovers system experienced\s*=\s*(\d+)"),
        "last_switchover_reason": grab(r"Last switchover reason\s*=\s*(.+)"),
    }
    states = re.findall(r"Current Software state\s*=\s*(.+)", text)
    out["active_state"] = states[0].strip() if len(states) > 0 else None
    out["peer_state"] = states[1].strip() if len(states) > 1 else None
    return out


def parse_wireless_redundancy(text: str) -> dict:
    def grab(pat: str) -> str | None:
        m = re.search(pat, text, re.I)
        return m.group(1).strip() if m else None

    return {
        "mode": grab(r"Wireless Redundancy Mode\s*:\s*(\S+)"),
        "gateway_reachability": grab(r"Gateway reachability\s*:\s*(\S+)"),
        "rmi_local": grab(r"\(RMI\) Local\s*:\s*\S+\s+\S+\s+state\s+(\S+)"),
        "rmi_peer": grab(r"\(RMI\) Peer\s*:\s*\S+\s+\S+\s+state\s+(\S+)"),
        "rp_local": grab(r"\(RP\) Local\s*:\s*\S+\s+state\s+(\S+)"),
        "rp_peer": grab(r"\(RP\) Peer\s*:\s*\S+\s+state\s+(\S+)"),
    }


def parse_mobility_summary(text: str) -> dict:
    def grab(pat: str) -> str | None:
        m = re.search(pat, text, re.I)
        return m.group(1).strip() if m else None

    out = {
        "group_name": grab(r"Mobility Group Name:\s*(\S+)"),
        "management_ip": grab(r"Wireless Management IP Address:\s*(\S+)"),
        "management_vlan": grab(r"Wireless Management VLAN:\s*(\S+)"),
        "domain_id": grab(r"Mobility Domain Identifier:\s*(\S+)"),
        "peers": [],
    }
    # table rows: IP  PublicIP  MAC  Group  mcastv4  mcastv6  Status  PMTU
    row = re.compile(
        r"^(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?P<public>\S+)\s+"
        r"(?P<mac>[0-9a-fA-F.]{14})\s+(?P<group>\S+)\s+\S+\s+\S+\s+"
        r"(?P<status>\S+)\s+(?P<pmtu>\S+)\s*$"
    )
    for line in text.splitlines():
        m = row.match(line.strip())
        if m:
            d = m.groupdict()
            out["peers"].append({
                "ip": d["ip"],
                "mac": d["mac"],
                "status": d["status"],       # N/A for self, Up/Down for peers
                "pmtu": d["pmtu"],
                "is_self": d["status"] == "N/A",
            })
    return out


def parse_aaa_servers(text: str) -> list[dict]:
    servers = []
    cur: dict | None = None
    for line in text.splitlines():
        m = re.match(
            r"\s*RADIUS: id (\d+), priority \d+, host (\S+),.*hostname (\S+)", line)
        if m:
            cur = {"id": m.group(1), "host": m.group(2), "name": m.group(3)}
            servers.append(cur)
            continue
        m = re.search(r"State:\s*current\s+([A-Za-z]+)", line)
        if m and cur is not None:
            cur["state"] = m.group(1)
    return servers


def parse_ap_primary_list(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        m = re.match(
            r"^(?P<ap>\S+)\s+(?P<pname>\S+)\s+(?P<pip>\d+\.\d+\.\d+\.\d+)\s+"
            r"(?P<sname>\S+)\s+(?P<sip>\d+\.\d+\.\d+\.\d+)\s*$", line.strip())
        if m and m.group("ap") != "AP":
            rows.append(m.groupdict())
    return rows


def parse_ap_join_summary(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        m = re.match(
            r"^(?P<base_mac>[0-9a-fA-F.]{14})\s+(?P<eth_mac>[0-9a-fA-F.]{14})\s+"
            r"(?P<ap>\S+)\s+(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?P<status>\S+)\s+"
            r"(?P<phase>.+?)\s{2,}(?P<reason>.+?)\s*$", line.strip())
        if m:
            rows.append(m.groupdict())
    return rows


def parse_client_summary(text: str) -> dict:
    m = re.search(r"Number of Clients:\s*(\d+)", text)
    count = int(m.group(1)) if m else 0
    m = re.search(r"Number of Excluded Clients:\s*(\d+)", text)
    excluded = int(m.group(1)) if m else 0
    per_wlan: dict[str, int] = {}
    for line in text.splitlines():
        mm = re.search(r"\bWLAN\s+(\d+)\s+\w", line)
        if mm:
            per_wlan[mm.group(1)] = per_wlan.get(mm.group(1), 0) + 1
    return {"count": count, "excluded": excluded, "per_wlan": per_wlan}
