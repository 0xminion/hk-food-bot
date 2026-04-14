#!/usr/bin/env python3
"""Quick test: resolve 3 venues to verify the pipeline works."""
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

CACHE_FILE = Path(__file__).parent.parent / "data" / "google_ratings_cache.json"

def load_cache() -> dict:
    with open(CACHE_FILE) as f:
        return json.load(f)

def save_cache(cache: dict):
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.rename(CACHE_FILE)

def accept_consent(page):
    try:
        selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Alle akzeptieren')",
            "button:has-text('Tout accepter')",
            "button:has-text('Aceptar todo')",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "form[action*='consent'] button",
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel)
                if btn.count() > 0:
                    btn.first.click(timeout=3000)
                    time.sleep(1.5)
                    return
            except Exception:
                continue
    except Exception:
        pass

def main():
    from camoufox.sync_api import Camoufox

    cache = load_cache()
    print(f"Cache: {len(cache)} entries")

    test_venues = [
        {"name": "Foxglove", "address": "2/F, 6 Duddell St, Central, Hong Kong"},
        {"name": "Gutshot", "address": "TOWER 2, LL, 23/F, 4 Shelley St, Central, Hong Kong"},
        {"name": "Inoshishi", "address": "9/f, Macau Yat Yuen Center, 525 Hennessy Rd, Causeway Bay, Hong Kong"},
    ]

    resolved = 0
    failed = 0

    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        page.goto("https://www.google.com/maps/@22.27,114.17,13z",
                  wait_until="domcontentloaded", timeout=20000)
        time.sleep(4)
        accept_consent(page)
        print("Browser ready")

        for i, v in enumerate(test_venues):
            name = v["name"]
            address = v["address"]
            key = f"{name}|{address}"
            print(f"[{i+1}/3] Processing: {name}")

            try:
                query = f"{name} {address} Hong Kong"
                url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
                page.goto(url, wait_until="domcontentloaded", timeout=12000)
                time.sleep(2.5)

                text = page.inner_text("body")

                if "consent" in page.url:
                    accept_consent(page)
                    time.sleep(2)
                    text = page.inner_text("body")

                m = re.search(r"(\d[.,]\d)\s*\((\d[\d.,]*)\)", text)
                if m:
                    rating = float(m.group(1).replace(",", "."))
                    reviews = int(m.group(2).replace(",", "").replace(".", ""))
                    if 1.0 <= rating <= 5.0:
                        cache[key] = {
                            "google_rating": rating,
                            "google_reviews": reviews,
                            "resolved": True,
                            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        }
                        resolved += 1
                        print(f"  ✅ {rating} ({reviews} reviews)")
                    else:
                        failed += 1
                        print(f"  ❌ Invalid rating: {rating}")
                else:
                    failed += 1
                    print(f"  ❌ No rating found")

                time.sleep(1.5)

            except Exception as e:
                failed += 1
                print(f"  ❌ Error: {type(e).__name__}: {e}")

    save_cache(cache)
    print(f"\nDone: {resolved} resolved, {failed} failed")

if __name__ == "__main__":
    main()
