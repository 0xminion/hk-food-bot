#!/usr/bin/env python3
"""Batch cache Google ratings for a specific area CSV."""
import csv, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

AREA_CSV = sys.argv[1] if len(sys.argv) > 1 else "data/_uncached_hk_island.csv"
CACHE_FILE = Path("data/google_ratings_cache.json")

# Load existing cache
cache = {}
if CACHE_FILE.exists():
    with open(CACHE_FILE) as f:
        cache = json.load(f)

# Load uncached list
to_resolve = []
with open(AREA_CSV, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        name = row["name"].strip()
        addr = row["address"].strip()
        key = f"{name}|{addr}"
        if key not in cache:
            to_resolve.append({"name": name, "address": addr, "key": key})

print(f"Area: {AREA_CSV} | To resolve: {len(to_resolve)}", flush=True)

try:
    from camoufox.sync_api import Camoufox
except ImportError:
    print("ERROR: camoufox not installed")
    sys.exit(1)

resolved = 0
failed = 0

with Camoufox(headless=True) as browser:
    page = browser.new_page()
    page.goto("https://www.google.com/maps/@22.27,114.17,13z",
              wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)
    try:
        btns = page.locator("button")
        for i in range(btns.count()):
            t = btns.nth(i).inner_text().lower()
            if "accept" in t or "i agree" in t:
                btns.nth(i).click()
                time.sleep(2)
                break
    except Exception:
        pass

    for i, v in enumerate(to_resolve):
        try:
            query = f"{v['name']} {v['address']} Hong Kong"
            url = f"https://www.google.com/maps/search/{quote_plus(query)}"
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2.5)

            text = page.inner_text("body")
            m = re.search(r"(\d[.,]\d)\s*\((\d[\d.,]*)\)", text)
            if m:
                rating = float(m.group(1).replace(",", "."))
                reviews = int(m.group(2).replace(",", "").replace(".", ""))
                if 1.0 <= rating <= 5.0:
                    cache[v["key"]] = {
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

            if (i + 1) % 20 == 0:
                with open(CACHE_FILE, "w") as f:
                    json.dump(cache, f, ensure_ascii=False)
                print(f"  [{i+1}/{len(to_resolve)}] +{resolved} ok, {failed} fail, cache={len(cache)}", flush=True)

            time.sleep(1.5)
        except Exception as e:
            failed += 1
            if "browser has been closed" in str(e):
                print("  Browser crashed, saving and exiting", flush=True)
                break
            print(f"  [{i+1}] FAIL {v['name']}: {type(e).__name__}", flush=True)

    try:
        browser.close()
    except Exception:
        pass

with open(CACHE_FILE, "w") as f:
    json.dump(cache, f, ensure_ascii=False)
print(f"Done: {resolved} resolved, {failed} failed. Cache: {len(cache)} total", flush=True)
