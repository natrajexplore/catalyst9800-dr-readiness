#!/usr/bin/env python
"""
Scheduled DR-readiness report.

Runs the readiness engine, writes JSON + timestamped HTML to reports/, and
optionally emails it (SMTP_*) and/or posts a summary to a webhook
(REPORT_WEBHOOK_URL). With none set it just writes the files.

    python scripts/scheduled_report.py [--scenario healthy|failover]

Schedule it (cron, weekly Monday 07:00):
    0 7 * * 1  cd /path/to/repo && ~/.venvs/c9800dr/bin/python scripts/scheduled_report.py
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
import urllib.request
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import reports  # noqa: E402
from app.collectors import collect_all  # noqa: E402
from app.readiness import evaluate  # noqa: E402


def _email(subject: str, html_body: str) -> str:
    host = os.environ.get("SMTP_HOST")
    to = os.environ.get("SMTP_TO")
    if not (host and to):
        return "email: skipped (SMTP_HOST/SMTP_TO not set)"
    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "dr-readiness"))
    msg["To"] = to
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "25")), timeout=30) as s:
            if os.environ.get("SMTP_STARTTLS"):
                s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.sendmail(msg["From"], [x.strip() for x in to.split(",")], msg.as_string())
        return f"email: sent to {to}"
    except Exception as exc:  # noqa: BLE001
        return f"email: FAILED ({exc})"


def _webhook(text: str) -> str:
    url = os.environ.get("REPORT_WEBHOOK_URL")
    if not url:
        return "webhook: skipped (REPORT_WEBHOOK_URL not set)"
    try:
        req = urllib.request.Request(
            url, data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30)
        return "webhook: posted"
    except Exception as exc:  # noqa: BLE001
        return f"webhook: FAILED ({exc})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", default="healthy", choices=("healthy", "failover"))
    args = ap.parse_args()

    controllers = collect_all(args.scenario)
    report = evaluate(controllers)

    reports.write_readiness(report, args.scenario)
    html_path = reports.write_html_report(report, args.scenario, controllers)

    cnt = report["counts"]
    summary = (f"Catalyst 9800 DR readiness ({args.scenario}): {report['overall']} "
               f"{report['score']}% - PASS {cnt['pass']} / WARN {cnt['warn']} / FAIL {cnt['fail']}")
    fails = [c["title"] for c in report["checks"] if c["status"] == "FAIL"]
    if fails:
        summary += "\nFAIL: " + "; ".join(fails)

    print(summary)
    print(f"  HTML: {html_path}")
    print("  " + _email(summary.splitlines()[0],
                        reports.render_html_report(report, args.scenario, controllers)))
    print("  " + _webhook(summary))
    return 0 if report["overall"] != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
