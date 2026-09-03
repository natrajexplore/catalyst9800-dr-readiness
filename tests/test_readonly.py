"""
Proof that the toolkit is read-only against a controller.

    python tests/test_readonly.py        # plain, no pytest needed
    pytest tests/test_readonly.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors import COMMANDS, UnsafeCommandError, _guard


def test_every_collected_command_is_read_only():
    for cmd, _ in COMMANDS:
        assert _guard(cmd) == cmd, cmd
        assert cmd.startswith("show ")


def test_guard_blocks_writes():
    for bad in ("configure terminal", "conf t", "wr mem", "copy run start",
                "reload", "clear line", "ap name X reset", "no wlan 10"):
        try:
            _guard(bad)
        except UnsafeCommandError:
            continue
        raise AssertionError(f"guard let through: {bad!r}")


def test_guard_allows_reads():
    for ok in ("show version", "show ap summary", "dir bootflash:", "more nvram:startup-config"):
        assert _guard(ok) == ok


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
            n += 1
    print(f"\n{n} read-only tests passed")
