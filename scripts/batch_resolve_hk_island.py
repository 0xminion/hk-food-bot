#!/usr/bin/env python3
"""Batch resolve 100 HK Island venues to Google ratings via Camoufox."""
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

CACHE_FILE = Path(__file__).parent.parent / "data" / "google_ratings_cache.json"
SELECTION_FILE = Path("/tmp/hk_island_100.csv")

def main():
    # Load cache
    with open(CACHE_FILE) as f:
        cache = json.load(f)
    print(f"Cache loaded: {len(cache)} entries")

    # Load venues
    with open(SELECTION_FILE) as f:
        venues = list(csv.DictReader(f))
    print(f"Venues to resolve: {len(venues)}")

    from camoufox.sync_api import Camoufox

    with Camoufox(headless=True) as browser:
        page = browser.new_page()

        # Accept consent
        print("Accepting consent...")
        page.goto("https://www.google.com/maps/@22.27,114.17,13z",
                  wait_until="domcontentloaded", timeout=20000)
        time.sleep(4)
        _accept_consent(page)
        print("Consent handled")

        resolved = 0
        failed = 0

        for i, v in enumerate(venues):
            name = v["name"]
            address = v["address"]
            key = f"{name}|{address}"

            if key in cache and cache[key].get("google_rating"):
                continue

            try:
                query = f"{name} {address} Hong Kong"
                url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(3)

                text = page.inner_text("body")

                # Re-handle consent if needed
                if "consent" in page.url:
                    _accept_consent(page)
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
                        print(f"  [{i+1}/{len(venues)}] ✅ {name}: ⭐{rating} ({reviews})")
                    else:
                        failed += 1
                        print(f"  [{i+1}/{len(venues)}] ⚠️ {name}: invalid rating {rating}")
                else:
                    failed += 1
                    print(f"  [{i+1}/{len(venues)}] ❌ {name}: no rating")

                # Save every 10
                if (i + 1) % 10 == 0:
                    _save_cache(cache)
                    print(f"  Cache saved ({len(cache)} entries)")

                time.sleep(2)

            except Exception as e:
                failed += 1
                print(f"  [{i+1}/{len(venues)}] ❌ {name}: {type(e).__name__}: {str(e)[:60]}")

        browser.close()

    _save_cache(cache)
    print(f"\nDone: {resolved} resolved, {failed} failed. Cache: {len(cache)} total")


def _accept_consent(page):
    try:
        btns = page.locator("button")
        for i in range(btns.count()):
            t = btns.nth(i).inner_text().lower()
            if "accept" in t or "akzeptieren" in t:
                btns.nth(i).click()
                time.sleep(2)
                return True
    except Exception:
        pass
    return False


def _save_cache(cache):
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.rename(CACHE_FILE)


if __name__ == "__main__":
    main()
