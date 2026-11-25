#!/usr/bin/env python3
"""Download / refresh all raw data. Usage: python scripts/update_data.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from btcrisk.fetch import update_all  # noqa: E402

if __name__ == "__main__":
    print("Refreshing raw data ...")
    status = update_all()
    failed = {k: v for k, v in status.items() if v != "ok"}
    if failed:
        print(f"{len(failed)} source(s) failed: {failed}")
        # Core source missing means we cannot compute anything current.
        if "coinmetrics/btc" in failed:
            sys.exit(1)
