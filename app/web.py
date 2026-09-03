"""
Flask dashboard for the Catalyst 9800 wireless DR demo.

    python app/web.py            # http://127.0.0.1:5000

Routes:
    /                  the dashboard (readiness + topology + failover playback)
    /mock/webui        a simulated C9800 login page (opened by the device popup)
    /api/failover      the scripted-failover result as JSON
    /api/readiness     readiness for ?scenario=healthy|failover
    /api/topology      topology for ?scenario=healthy|failover
    /healthz           liveness probe
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, jsonify, render_template, request

from app import readiness as readiness_mod
from app import scenario as scenario_mod
from app import topology as topology_mod
from app.collectors import collect_all

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
SSH_USER = os.environ.get("C9800_USERNAME", "admin")

# collect_all is slow (~1 min); cache per process. ?refresh=1 busts it.
_CACHE: dict[str, object] = {}


def _cached(key, producer):
    if request.args.get("refresh"):
        _CACHE.pop(key, None)
    if key not in _CACHE:
        _CACHE[key] = producer()
    return _CACHE[key]


@app.route("/")
def dashboard():
    return render_template("dashboard.html",
                           result=_cached("failover", scenario_mod.run),
                           ssh_user=SSH_USER)


@app.route("/api/failover")
def api_failover():
    return jsonify(_cached("failover", scenario_mod.run))


@app.route("/api/readiness")
def api_readiness():
    scen = request.args.get("scenario", "healthy")
    return jsonify(readiness_mod.evaluate(_cached(f"ctrls:{scen}", lambda: collect_all(scen))))


@app.route("/api/topology")
def api_topology():
    scen = request.args.get("scenario", "healthy")
    ctrls = _cached(f"ctrls:{scen}", lambda: collect_all(scen))
    return jsonify(topology_mod.build(ctrls, scen))


@app.route("/healthz")
def healthz():
    return {"ok": True}


_MOCK_WEBUI = """<!doctype html><meta charset=utf-8><title>{dev} - Login</title>
<style>body{{font:14px -apple-system,Segoe UI,Arial;background:#0b0f14;color:#e8eef5;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}
.card{{background:#12202e;border:1px solid #24384c;border-radius:12px;padding:30px 34px;width:340px}}
h1{{font-size:16px;margin:0 0 2px}} .s{{color:#8fa3b6;font-size:12px;margin-bottom:18px}}
label{{display:block;font-size:12px;color:#8fa3b6;margin:12px 0 4px}}
input{{width:100%;padding:9px;border-radius:7px;border:1px solid #2b3f52;background:#0b141d;color:#e8eef5}}
button{{width:100%;margin-top:18px;padding:10px;border:0;border-radius:7px;background:#1f6feb;color:#fff;font-weight:700}}
.warn{{margin-top:16px;padding:8px;border-radius:7px;background:#3a2e0c;color:#e3b341;font-size:11.5px;text-align:center}}</style>
<div class=card>
<h1>Cisco Catalyst 9800</h1><div class=s>{dev} &nbsp;&middot;&nbsp; https://{ip}/webui/</div>
<label>Username</label><input value="{user}">
<label>Password</label><input type=password value="">
<button onclick="alert('Simulated login page - no real controller here.')">Log In</button>
<div class=warn>SIMULATED &mdash; demo mode.</div>
</div>"""


@app.route("/mock/webui")
def mock_webui():
    esc = lambda s: (s or "").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return _MOCK_WEBUI.format(dev=esc(request.args.get("dev", "WLC")),
                             ip=esc(request.args.get("ip", "0.0.0.0")), user=SSH_USER)


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "5000")), debug=True)
