#!/usr/bin/env python3
"""
Check OpenRice URLs for permanently closed places using Camoufox (bypasses WAF).
Updates data/closed_places.txt with any newly detected closed venues.

Usage:
    python3 scripts/check_closed_places.py [--dry-run] [--limit 50]
"""

import argparse
import csv
import re
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "merged_places.csv"
CLOSED_PATH = PROJECT_ROOT / "data" / "closed_places.txt"

# Markers in OpenRice page HTML that indicate closure
CLOSED_MARKERS = [
    "已結業",           # "Already closed" in Traditional Chinese
    "永久停業",
    "暫停營業",         # Temporarily closed
    "permanently closed",
    "temporarily closed",
    "closed permanently",
    "restaurant is closed",
]


def load_existing_closed() -> set[str]:
    """Load already-known closed places."""
    if not CLOSED_PATH.exists():
        return set()
    names = set()
    for line in CLOSED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line)
    return names


def check_with_camoufox(urls: list[tuple[str, str]]) -> list[str]:
    """Check URLs using Camoufox browser. Returns list of closed place names."""
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        print("ERROR: camoufox not installed. Run: pip install camoufox")
        return []

    closed = []
    total = len(urls)

    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        for i, (name, url) in enumerate(urls):
            try:
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(1)  # Let page render
                content = page.content()

                # Check for closure markers
                content_lower = content.lower()
                is_closed = False
                for marker in CLOSED_MARKERS:
                    if marker in content_lower:
                        is_closed = True
                        break

                # Also check: very small page (< 20KB) often means "not found" or "closed"
                if len(content) < 20000 and not is_closed:
                    # Look for any text indicating closure
                    text = page.inner_text("body") if page.query_selector("body") else ""
                    if any(m in text for m in ["結業", "closed", "停業"]):
                        is_closed = True

                if is_closed:
                    closed.append(name)
                    print(f"  CLOSED: {name}")

                if (i + 1) % 10 == 0:
                    print(f"  Progress: {i + 1}/{total} ({len(closed)} closed)")

            except Exception as e:
                print(f"  ERROR checking {name}: {e}")
                continue

    return closed


def main():
    parser = argparse.ArgumentParser(description="Check OpenRice for closed places via Camoufox")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to closed_places.txt")
    parser.add_argument("--limit", type=int, default=0, help="Only check first N URLs")
    args = parser.parse_args()

    # Load places
    places = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            url = (row.get("source_url") or "").strip()
            place_type = (row.get("type") or "").strip()
            if name and "openrice.com" in url:
                places.append((name, url, place_type))

    print(f"Found {len(places)} places with OpenRice URLs")
    existing_closed = load_existing_closed()
    print(f"Already tracking {len(existing_closed)} closed places")

    to_check = [(n, u) for n, u, t in places if n not in existing_closed]
    if args.limit:
        to_check = to_check[:args.limit]
    print(f"Checking {len(to_check)} URLs via Camoufox")

    newly_closed = check_with_camoufox(to_check)

    print(f"\nDone: {len(newly_closed)} newly closed places")

    if newly_closed and not args.dry_run:
        with open(CLOSED_PATH, "a", encoding="utf-8") as f:
            for name in sorted(newly_closed):
                f.write(name + "\n")
        print(f"Wrote {len(newly_closed)} names to {CLOSED_PATH}")
    elif newly_closed and args.dry_run:
        print(f"DRY RUN — would write {len(newly_closed)} names")
        for name in sorted(newly_closed)[:30]:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
