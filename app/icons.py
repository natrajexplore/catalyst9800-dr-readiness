"""
Simple Cisco-style network device icons as inline SVG data URIs, so the topology
diagram shows a WLC / AP / switch / ISE glyph instead of a generic shape.

These are original simplified glyphs (not Cisco's trademarked icon set); tweak
the SVG here if you want them closer to your own diagram conventions.
"""

from __future__ import annotations

import base64

_COL = {
    "controller": "#1f6feb",
    "core_switch": "#8957e5",
    "access_switch": "#6e7681",
    "ap": "#2ea043",
    "aaa": "#bb8009",
    "firewall": "#f85149",
    "dmz": "#d29922",
    "client": "#58a6ff",
}


def _svg(body: str, stroke: str) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<g fill="none" stroke="{stroke}" stroke-width="3" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</g></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# WLC: stacked appliance with wireless waves
_CONTROLLER = _svg(
    '<rect x="10" y="30" width="44" height="12" rx="2" fill="#132a45"/>'
    '<rect x="10" y="44" width="44" height="12" rx="2" fill="#132a45"/>'
    '<circle cx="18" cy="36" r="1.6" fill="#1f6feb" stroke="none"/>'
    '<circle cx="18" cy="50" r="1.6" fill="#1f6feb" stroke="none"/>'
    '<path d="M24 20a14 14 0 0 1 20 0"/><path d="M29 25a7 7 0 0 1 10 0"/>'
    '<circle cx="34" cy="30" r="1.6" fill="#1f6feb" stroke="none"/>',
    _COL["controller"])

# AP: dome with waves
_AP = _svg(
    '<path d="M14 40a20 20 0 0 1 36 0z" fill="#123020"/>'
    '<path d="M22 22a16 16 0 0 1 20 0"/><path d="M27 28a8 8 0 0 1 10 0"/>'
    '<line x1="32" y1="40" x2="32" y2="50"/>',
    _COL["ap"])

# Core switch: diamond router-ish with cross arrows
_CORE = _svg(
    '<path d="M32 10 54 32 32 54 10 32z" fill="#241a3d"/>'
    '<path d="M22 32h20M32 22v20"/>'
    '<path d="M40 24l4 4-4 4M24 40l-4-4 4-4"/>',
    _COL["core_switch"])

# Access switch: flat box with ports
_ACCESS = _svg(
    '<rect x="8" y="26" width="48" height="16" rx="2" fill="#20262e"/>'
    '<line x1="15" y1="42" x2="15" y2="47"/><line x1="23" y1="42" x2="23" y2="47"/>'
    '<line x1="31" y1="42" x2="31" y2="47"/><line x1="39" y1="42" x2="39" y2="47"/>'
    '<line x1="47" y1="42" x2="47" y2="47"/>',
    _COL["access_switch"])

# AAA / ISE: shield with tick
_AAA = _svg(
    '<path d="M32 10l18 6v12c0 12-8 20-18 26-10-6-18-14-18-26V16z" fill="#3a2e0c"/>'
    '<path d="M24 32l6 6 12-14"/>',
    _COL["aaa"])

# Firewall: brick wall
_FIREWALL = _svg(
    '<rect x="8" y="14" width="48" height="36" rx="2" fill="#3a1414"/>'
    '<path d="M8 23h48M8 32h48M8 41h48"/>'
    '<path d="M20 14v9M44 14v9M8 23v9M32 23v9M56 23v9M20 32v9M44 32v9M8 41v9M32 41v9M56 41v9"/>',
    _COL["firewall"])

# DMZ zone: fenced/segmented compound
_DMZ = _svg(
    '<rect x="10" y="16" width="44" height="32" rx="2" stroke-dasharray="4 3" fill="#3a2e0c"/>'
    '<rect x="22" y="26" width="20" height="14" rx="1.5"/>'
    '<line x1="27" y1="26" x2="27" y2="40"/><line x1="37" y1="26" x2="37" y2="40"/>',
    _COL["dmz"])

# client device: small laptop glyph
_CLIENT = _svg(
    '<rect x="14" y="18" width="36" height="24" rx="2" fill="#0d2238"/>'
    '<line x1="10" y1="48" x2="54" y2="48"/>',
    _COL["client"])

ICONS: dict[str, str] = {
    "controller": _CONTROLLER,
    "core_switch": _CORE,
    "access_switch": _ACCESS,
    "ap": _AP,
    "aaa": _AAA,
    "firewall": _FIREWALL,
    "dmz": _DMZ,
    "client": _CLIENT,
}


def icon_for(node_type: str) -> str | None:
    return ICONS.get(node_type)
