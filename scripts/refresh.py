#!/usr/bin/env python3
"""One command for the daily refresh: download, score, backtest, export.

Runs the four steps in order and stops at the first failure:

  1. scripts/update_data.py       re-download the free public data          (~1 min)
  2. scripts/run_backtest.py      re-run the model and the full backtest    (~1 min)
  3. scripts/export_dashboard.py  write the dashboard's data files          (~15 s)
  4. scripts/pack_dashboard.py    wrap the page files for the dashboard store

Then it checks that the result looks sane (a fresh date, a reading between 0 and 1, every
file present) and prints a short summary.  Exit code 0 means out/dashboard/ is ready to upload.

Usage:  python3 -I scripts/refresh.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ["update_data.py", "run_backtest.py", "export_dashboard.py", "pack_dashboard.py"]
FILES = ["history", "today", "indicators", "turns", "zones", "blind", "early", "grades", "baselines", "strategy"]
MAX_AGE_DAYS = 3          # the newest scored day may trail the clock by this much before we call it stale


def main() -> int:
    for step in STEPS:
        t0 = time.time()
        proc = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / step)], cwd=ROOT,
                              capture_output=True, text=True)
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-12:])
        print(f"[{step}] exit {proc.returncode} in {time.time() - t0:.0f}s")
        if proc.returncode != 0:
            print(tail)
            print(f"FAILED at {step}. Nothing in out/dashboard/ should be uploaded.")
            return 1

    dest = ROOT / "out" / "dashboard"
    problems = []
    rows = {}
    for name in FILES:
        path = dest / f"{name}.json"
        try:
            rows[name] = json.loads(path.read_text())["rows"]
            if not rows[name]:
                problems.append(f"{name}.json has no rows")
        except Exception as exc:                                    # missing or unreadable file
            problems.append(f"{name}.json: {exc}")
    if not problems:
        today = rows["today"][0]
        day = datetime.strptime(today["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - day > timedelta(days=MAX_AGE_DAYS + 1):
            problems.append(f"newest scored day is {today['date']}, more than {MAX_AGE_DAYS} days old")
        if not (0.0 <= today["risk"] <= 1.0):
            problems.append(f"reading {today['risk']} is outside 0..1")
        if rows["history"][-1]["date"] != today["date"]:
            problems.append("history.json and today.json end on different days")
        if len(rows["history"]) < 5900:
            problems.append(f"history.json has only {len(rows['history'])} rows")
    if problems:
        print("FAILED the sanity check:\n  - " + "\n  - ".join(problems))
        return 1

    print(f"OK  data through {today['date']}  price ${today['price']:,.0f}  reading {today['risk']:.3f}  zone {today['zone']}")
    print("Files ready in out/dashboard/: " + ", ".join(f"{n}.json" for n in FILES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
