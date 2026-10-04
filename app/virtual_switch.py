"""
A tiny, real SSH server that behaves like a Cisco IOS core switch -- just
enough CLI to SSH into from PuTTY and run `configure terminal`, select
Port-channel10 or its member GigabitEthernet ports, and `shutdown` /
`no shutdown` them. There is no real/virtual Cisco device behind it; this
*is* the device, standing in for one so the DR drill can be driven by hand
over a genuine SSH session instead of a script.

Interface admin state is written to a small JSON file (`run/vswitch_state.json`)
that the Flask dashboard polls, so the 2D topology updates live while you type
in your own PuTTY window -- no SSH link between this module and the dashboard,
just a shared state file.

Not a general CLI emulator: it understands exactly the commands this drill
needs and answers anything else with a Cisco-style "% Unknown command".
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path

import asyncssh

from app.scenario import LOGIN

HOSTNAME = "DC1-CORE-SW1"
RUN_DIR = Path(__file__).resolve().parent.parent / "run"
STATE_FILE = RUN_DIR / "vswitch_state.json"
HOST_KEY_FILE = RUN_DIR / "vswitch_host_key"

BUNDLE = "Port-channel10"
MEMBERS = ("GigabitEthernet1/0/1", "GigabitEthernet1/0/2")
IFACES = (BUNDLE,) + MEMBERS

_lock = threading.Lock()


# ---------------------------------------------------------------- state ----
def _default_state() -> dict:
    return {name: "up" for name in IFACES}


def read_state() -> dict:
    with _lock:
        try:
            data = json.loads(STATE_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {**_default_state(), "updated": None}
    return data


def is_po10_down(state: dict | None = None) -> bool:
    state = state or read_state()
    return state.get(BUNDLE) == "down" or all(state.get(m) == "down" for m in MEMBERS)


def _write_state(state: dict) -> None:
    RUN_DIR.mkdir(exist_ok=True)
    state = {**state, "updated": time.time()}
    tmp = STATE_FILE.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(state))
        os.replace(tmp, STATE_FILE)


def reset_state() -> None:
    _write_state(_default_state())


def _set_ifaces(names: list[str], admin_up: bool) -> None:
    state = {k: v for k, v in read_state().items() if k != "updated"}
    for n in names:
        state[n] = "up" if admin_up else "down"
    _write_state(state)


# ------------------------------------------------------------ CLI parsing ----
def _match_interface(rest: str) -> list[str] | None:
    """`rest` is whatever follows 'interface'/'int', lowercased, e.g.
    'port-channel10' or 'range gigabitethernet1/0/1-2' or 'range gi1/0/1-2'."""
    rest = rest.strip()
    if rest.startswith("range "):
        rest = rest[len("range "):].strip()
    rest = rest.replace("gigabitethernet", "gi").replace("port-channel", "po")

    m = re.match(r"gi(\d+/\d+/)(\d+)-(\d+)$", rest)
    if m:
        base, start, end = m.group(1), int(m.group(2)), int(m.group(3))
        return [f"GigabitEthernet{base}{i}" for i in range(start, end + 1)]
    m = re.match(r"gi(\d+/\d+/\d+)$", rest)
    if m:
        return [f"GigabitEthernet{m.group(1)}"]
    m = re.match(r"po(\d+)$", rest)
    if m:
        return [f"Port-channel{m.group(1)}"]
    return None


_SYSLOG = ("\r\n%LINK-3-UPDOWN: Interface {0}, changed state to {1}\r\n"
           "%LINEPROTO-5-UPDOWN: Line protocol on Interface {0}, changed state to {2}\r\n")


class _Session:
    def __init__(self) -> None:
        self.mode = "exec"  # exec -> enable -> config -> config-if
        self.selected: list[str] = []

    @property
    def prompt(self) -> str:
        if self.mode == "config-if":
            tag = "config-if-range" if len(self.selected) > 1 else "config-if"
            return f"{HOSTNAME}({tag})#"
        return {"exec": f"{HOSTNAME}>", "enable": f"{HOSTNAME}#",
                "config": f"{HOSTNAME}(config)#"}[self.mode]


def _show(process, low: str) -> None:
    if any(s in low for s in ("int brief", "interface brief", "interfaces status", "int status")):
        state = read_state()
        process.stdout.write("\r\nInterface              Status      Protocol\r\n")
        for name in IFACES:
            up = state.get(name, "up") == "up"
            process.stdout.write(f"{name:22} {'up' if up else 'admin down':11} {'up' if up else 'down'}\r\n")
        process.stdout.write("\r\n")
    else:
        process.stdout.write("% Unknown command\r\n")


async def _dispatch(sess: _Session, process, line: str) -> bool:
    """Returns True if the session should close."""
    out = process.stdout
    low = line.strip().lower()

    if low in ("exit", "quit", "logout"):
        if sess.mode == "config-if":
            sess.mode, sess.selected = "config", []
        elif sess.mode == "config":
            sess.mode = "enable"
        elif sess.mode == "enable":
            sess.mode = "exec"
        else:
            return True
        return False

    if low == "end" and sess.mode in ("config", "config-if"):
        sess.mode, sess.selected = "enable", []
        return False

    if sess.mode == "exec":
        if low == "enable":
            sess.mode = "enable"  # SSH login already authenticated this session
        else:
            out.write(f"% Unknown command: {line}\r\n")
        return False

    if sess.mode == "enable":
        if low in ("configure terminal", "conf t", "config t", "configure"):
            sess.mode = "config"
        elif low.startswith("show "):
            _show(process, low)
        else:
            out.write(f"% Unknown command: {line}\r\n")
        return False

    if sess.mode == "config":
        for kw in ("interface ", "int "):
            if low.startswith(kw):
                iface = _match_interface(low[len(kw):])
                if iface is None:
                    out.write(f"% Invalid interface: {line}\r\n")
                else:
                    sess.selected, sess.mode = iface, "config-if"
                return False
        out.write(f"% Unknown command: {line}\r\n")
        return False

    if sess.mode == "config-if":
        if low == "shutdown":
            _set_ifaces(sess.selected, admin_up=False)
            for name in sess.selected:
                out.write(_SYSLOG.format(name, "administratively down", "down"))
        elif low == "no shutdown":
            _set_ifaces(sess.selected, admin_up=True)
            for name in sess.selected:
                out.write(_SYSLOG.format(name, "up", "up"))
        else:
            out.write(f"% Unknown command: {line}\r\n")
        return False

    return False


async def _handle_client(process: "asyncssh.SSHServerProcess") -> None:
    sess = _Session()
    process.stdout.write(
        f"\r\n{HOSTNAME} uptime is 3 days, 2 hours, 14 minutes\r\n"
        "Demo virtual core switch for the Catalyst 9800 DR drill.\r\n"
        "Try: enable -> configure terminal -> interface Port-channel10 -> shutdown\r\n\r\n")
    try:
        while True:
            process.stdout.write(sess.prompt + " ")
            line = await process.stdin.readline()
            if line == "":
                break
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            if await _dispatch(sess, process, line):
                break
    finally:
        process.exit(0)


class _AuthServer(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == LOGIN["username"] and password == LOGIN["password"]


def _ensure_host_key() -> str:
    RUN_DIR.mkdir(exist_ok=True)
    if not HOST_KEY_FILE.exists():
        key = asyncssh.generate_private_key("ssh-rsa")
        key.write_private_key(str(HOST_KEY_FILE))
    return str(HOST_KEY_FILE)


async def _serve(port: int) -> None:
    reset_state()
    await asyncssh.create_server(
        _AuthServer, "", port,
        server_host_keys=[_ensure_host_key()],
        process_factory=_handle_client,
    )
    await asyncio.Future()


def start_background(port: int = 2222) -> None:
    """Runs the SSH server in its own thread + event loop so Flask's dev
    server (sync, single-threaded request handling) can keep running."""
    threading.Thread(target=lambda: asyncio.run(_serve(port)),
                      daemon=True, name="vswitch-ssh").start()


if __name__ == "__main__":
    asyncio.run(_serve(int(os.environ.get("VSWITCH_PORT", "2222"))))
