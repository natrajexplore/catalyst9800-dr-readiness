#!/usr/bin/env bash
# One-time WSL setup for the Catalyst 9800 DR readiness toolkit.
#
#   wsl                     # from the repo folder on the Windows side, or:
#   wsl bash setup_wsl.sh
#
# pyATS/Genie do not run on native Windows, and unicon's mock CLI cannot handle
# spaces in paths, so we (a) install into a venv on the Linux filesystem and
# (b) expose the repo at a space-free path via a symlink.
set -euo pipefail

VENV="${C9800DR_VENV:-$HOME/.venvs/c9800dr}"
LINK="${C9800DR_LINK:-$HOME/c9800dr}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ">> repo (this dir) : $SRC"
echo ">> space-free link : $LINK  ->  $SRC"
ln -sfn "$SRC" "$LINK"

if [ ! -x "$VENV/bin/python" ]; then
  PY="$(command -v python3.12 || command -v python3)"
  echo ">> creating venv with $PY"
  "$PY" -m venv "$VENV"
fi

echo ">> installing requirements (this takes a few minutes the first time)"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q "pyats[library]>=25.1" "flask>=3.0"

cat <<EOF

Done. From now on:

  source $VENV/bin/activate
  export PATH="$VENV/bin:\$PATH"        # unicon needs mock_device_cli on PATH
  cd $LINK

  python scripts/run_readiness.py
  python scripts/discover_topology.py
  python scripts/run_failover.py
  python app/web.py                      # dashboard on http://127.0.0.1:5000
  pyats run job tests/dr_readiness/job.py
EOF
