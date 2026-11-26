"""Wrap the dashboard's page files (dashboard/*) as the JSON documents its store expects.

The dashboard is a Claude artifact whose page is kept as three documents, each {"text": "..."}:
files/index.html, files/style.css and files/app.js.  This writes them to out/dashboard/store/ so
they can be sent as they are.  The data files next to them (out/dashboard/*.json) are uploaded
separately; see README.md, "Daily refresh".

Usage:  python3 scripts/pack_dashboard.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "dashboard"
DEST = ROOT / "out" / "dashboard" / "store"


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "style.css", "app.js"):
        text = (SRC / name).read_text()
        (DEST / f"{name}.json").write_text(json.dumps({"text": text}))
        print(f"  {name}: {len(text.encode()) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
