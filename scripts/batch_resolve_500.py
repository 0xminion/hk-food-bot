#!/usr/bin/env python3
"""Batch resolve 500 HK Island venues to Google ratings via Camoufox."""
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

CACHE_FILE = Path(__file__).parent.parent / "data" / "google_ratings_cache.json"
SELECTION_FILE = Path("/tmp/hk_island_500.csv")


def main():
    with open(CACHE_FILE) as f:
        cache = json.load(f)
    print(f"Cache loaded: {len(cache)} entries")

    with open(SELECTION_FILE) as f:
        venues = list(csv.DictReader(f))
    print(f"Venues to resolve: {len(venues)}")

    # Skip already cached
    to_resolve = []
    for v in venues:
        key = f"{v['name']}|{v['address']}"
        if key not in cache or not cache[key].get("google_rating"):
            to_resolve.append(v)
    print(f"Need to resolve: {len(to_resolve)} (skipping {len(venues) - len(to_resolve)} cached)")

    from camoufox.sync_api import Camoufox

    with Camoufox(headless=True) as browser:
        page = browser.new_page()

        # Accept consent once
        page.goto("https://www.google.com/maps/@22.27,114.17,13z",
                  wait_until="domcontentloaded", timeout=20000)
        time.sleep(4)
        _accept_consent(page)
        print("Browser ready")

        resolved = 0
        failed = 0

        for i, v in enumerate(to_resolve):
            name = v["name"]
            address = v["address"]
            key = f"{name}|{address}"

            try:
                query = f"{name} {address} Hong Kong"
                url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
                page.goto(url, wait_until="domcontentloaded", timeout=12000)
                time.sleep(2.5)

                text = page.inner_text("body")

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
                    else:
                        failed += 1
                else:
                    failed += 1

                # Progress + checkpoint every 25
                done = i + 1
                if done % 25 == 0:
                    _save_cache(cache)
                    rate = done / (time.time() - start_time)
                    eta = (len(to_resolve) - done) / rate / 60
                    print(f"  [{done}/{len(to_resolve)}] ✅{resolved} ❌{failed} | {rate:.1f}/s | ETA: {eta:.0f}min")

                time.sleep(1.5)

            except Exception as e:
                failed += 1
                if failed % 20 == 0:
                    print(f"  [{i+1}] {failed} failures so far: {type(e).__name__}")

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


start_time = time.time()

if __name__ == "__main__":
    main()
