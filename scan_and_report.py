#!/usr/bin/env python
"""
Opportunity Scanner — runs opportunities.py --all on GitHub Actions,
saves structured results to latest_scan.json for local cron delivery.

Free tier only: GitHub Actions (2000 min/month free), no keys, no accounts.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "opportunities_state.json")
SCAN_FILE = os.path.join(HERE, "latest_scan.json")
OPPORTUNITIES_SCRIPT = os.path.join(HERE, "opportunities.py")


def run_scan():
    """Rulează opportunities.py --all și returnează output-ul parsat."""
    result = subprocess.run(
        [sys.executable, OPPORTUNITIES_SCRIPT, "--all"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode, result.stdout, result.stderr


def load_previous_scan():
    if os.path.exists(SCAN_FILE):
        try:
            with open(SCAN_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_scan(scan):
    tmp = SCAN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(scan, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SCAN_FILE)


def main():
    rc, stdout, stderr = run_scan()

    scan = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "returncode": rc,
        "stdout": stdout,
        "stderr": stderr,
    }

    save_scan(scan)

    # Print summary for GitHub Actions log
    print(f"Scan completed at {scan['ran_at']} (rc={rc})")
    if stdout:
        print("=== SCAN OUTPUT ===")
        print(stdout[:5000])
    if stderr:
        print("=== SCAN STDERR ===")
        print(stderr[:2000])

    return 0


if __name__ == "__main__":
    sys.exit(main())
