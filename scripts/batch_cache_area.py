#!/usr/bin/env python3
"""Batch cache Google ratings for a specific area CSV.
Recycles browser every N venues to prevent memory leak crashes."""
import csv, json, gc, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

AREA_CSV = sys.argv[1] if len(sys.argv) > 1 else "data/_uncached_hk_island.csv"
CACHE_FILE = Path(os.environ.get("CACHE_FILE_OVERRIDE", "data/google_ratings_cache.json"))
RECYCLE_INTERVAL = 50  # restart browser every N venues

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

print(f"Area: {AREA_CSV} | To resolve: {len(to_resolve)} | Recycle every {RECYCLE_INTERVAL}", flush=True)

try:
    from camoufox.sync_api import Camoufox
except ImportError:
    print("ERROR: camoufox not installed")
    sys.exit(1)


def open_browser():
    """Open a fresh Camoufox browser with cookie consent handled."""
    from camoufox.sync_api import Camoufox
    browser_cm = Camoufox(headless=True)
    browser = browser_cm.__enter__()
    page = browser.new_page()
    page.goto("https://www.google.com/maps/@22.27,114.17,13z",
              wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)
    try:
        btns = page.locator("button")
        for i in range(btns.count()):
            try:
                t = btns.nth(i).inner_text().lower().strip()
                if any(kw in t for kw in ["accept", "agree", "akzeptieren", "zustimmen",
                                           "alle akzeptieren", "i agree", "consent", "ok"]):
                    btns.nth(i).click()
                    time.sleep(2)
                    break
            except Exception:
                continue
    except Exception:
        pass
    return browser_cm, browser, page


def close_browser(browser_cm, browser):
    """Safely close browser and force GC."""
    try:
        browser_cm.__exit__(None, None, None)
    except Exception:
        pass
    del browser_cm, browser
    gc.collect()
    time.sleep(1)


def save_cache():
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False)


resolved = 0
failed = 0
browser = None
page = None
browser_cm = None

for i, v in enumerate(to_resolve):
    # Recycle browser every RECYCLE_INTERVAL venues
    if i % RECYCLE_INTERVAL == 0:
        if browser is not None:
            print(f"  [recycle] Closing browser after {min(i, len(to_resolve))} venues...", flush=True)
            close_browser(browser_cm, browser)
            browser = None
            browser_cm = None
            page = None
        print(f"  [recycle] Opening fresh browser (venue {i+1}/{len(to_resolve)})...", flush=True)
        browser_cm, browser, page = open_browser()

    try:
        query = f"{v['name']} {v['address']} Hong Kong"
        url = f"https://www.google.com/maps/search/{quote_plus(query)}"
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2.5)

        text = page.inner_text("body")
        m = re.search(r"(\d(?:[.,]\d)?)\s*\((\d[\d.,]*)\)", text)
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
            # Fallback: aria-label pattern
            aria = page.inner_text("body")
            m2 = re.search(r"(\d[.,]\d)\s*(?:stars?|Stern)", aria, re.IGNORECASE)
            m3 = re.search(r"(\d[\d.,]*)\s*(?:review|Bewertung)", aria, re.IGNORECASE)
            if m2:
                rating = float(m2.group(1).replace(",", "."))
                reviews = int(m3.group(1).replace(",", "").replace(".", "")) if m3 else 0
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

        # Save every 20 venues
        if (i + 1) % 20 == 0:
            save_cache()
            print(f"  [{i+1}/{len(to_resolve)}] +{resolved} ok, {failed} fail, cache={len(cache)}", flush=True)

        time.sleep(1.5)
    except Exception as e:
        failed += 1
        if "browser has been closed" in str(e) or "Target page" in str(e):
            print(f"  [{i+1}] Browser died mid-batch, recycling...", flush=True)
            if browser_cm:
                close_browser(browser_cm, browser)
            browser = None
            browser_cm = None
            page = None
            continue
        print(f"  [{i+1}] FAIL {v['name']}: {type(e).__name__}", flush=True)

# Final cleanup
if browser is not None:
    close_browser(browser_cm, browser)

save_cache()
print(f"Done: {resolved} resolved, {failed} failed. Cache: {len(cache)} total", flush=True)
