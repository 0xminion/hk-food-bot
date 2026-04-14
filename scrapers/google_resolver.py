#!/usr/bin/env python3
"""
Google Maps Rating Resolver
============================
Resolves OpenRice venues to Google Maps ratings using Camoufox (anti-detect browser).
Results are cached in a JSON file to avoid re-scraping.

Usage:
    # Resolve a single venue
    python scrapers/google_resolver.py --venue "Yardbird" --address "Sheung Wan"

    # Batch resolve from CSV (skips already-cached)
    python scrapers/google_resolver.py --batch --max 50

    # Resolve venues the recommendation engine surfaces (lazy)
    python scrapers/google_resolver.py --lazy data/merged_places.csv
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Cache file location
CACHE_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = CACHE_DIR / "google_ratings_cache.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("google_resolver")


# ── Cache Management ──────────────────────────────────────────────────────────

def load_cache() -> dict:
    """Load cached Google ratings. Key: 'name|address' → {rating, reviews, ...}"""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        log.info(f"Loaded {len(cache)} cached venues from {CACHE_FILE}")
        return cache
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f"Cache corrupt, starting fresh: {e}")
        return {}


def save_cache(cache: dict):
    """Save cache atomically."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.rename(CACHE_FILE)


def cache_key(name: str, address: str) -> str:
    """Generate cache key from venue name + address."""
    return f"{name.strip()}|{address.strip()}"


def get_cached(cache: dict, name: str, address: str) -> Optional[dict]:
    """Get cached rating for a venue, or None."""
    key = cache_key(name, address)
    entry = cache.get(key)
    if entry and entry.get("google_rating"):
        # Check staleness (>90 days)
        updated = entry.get("last_updated", "")
        if updated:
            try:
                dt = datetime.fromisoformat(updated)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - dt).days
                if age_days > 90:
                    log.debug(f"Cache stale ({age_days}d): {name}")
                    return None
            except ValueError:
                pass
        return entry
    return None


# ── Google Maps Scraper ───────────────────────────────────────────────────────

def resolve_venue(name: str, address: str) -> Optional[dict]:
    """
    Resolve a venue to its Google Maps rating using Camoufox.

    Returns dict with:
        google_rating: float (1.0-5.0)
        google_reviews: int
        google_name: str (name as shown on Google Maps)
        resolved: bool
    """
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        log.error("camoufox not installed. Run: pip install camoufox")
        return None

    query = f"{name} {address} Hong Kong"
    result = None

    try:
        with Camoufox(headless=True) as browser:
            page = browser.new_page()

            # Accept consent on first load
            page.goto(
                "https://www.google.com/maps/@22.3,114.2,12z",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            time.sleep(3)
            _accept_consent(page)

            # Search for venue
            url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)

            text = page.inner_text("body")

            # Handle consent if it reappears
            if "consent" in page.url or "Bevor Sie" in text[:300]:
                _accept_consent(page)
                time.sleep(2)
                text = page.inner_text("body")

            # Extract rating: "4.5 (1,234)" pattern
            m = re.search(r"(\d[.,]\d)\s*\((\d[\d.,]*)\)", text)
            if m:
                rating = float(m.group(1).replace(",", "."))
                reviews = int(m.group(2).replace(",", "").replace(".", ""))

                # Validate
                if 1.0 <= rating <= 5.0 and reviews >= 0:
                    # Try to get the actual Google Maps name
                    google_name = _extract_name(page) or name

                    result = {
                        "google_rating": rating,
                        "google_reviews": reviews,
                        "google_name": google_name,
                        "resolved": True,
                        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    }
                    log.info(f"✅ {name}: ⭐{rating} ({reviews} reviews)")
                else:
                    log.warning(f"⚠️ {name}: invalid data rating={rating} reviews={reviews}")
            else:
                log.warning(f"❌ {name}: no rating found in page text")

            browser.close()

    except Exception as e:
        log.error(f"❌ {name}: {type(e).__name__}: {e}")

    return result


def _accept_consent(page):
    """Click the Google consent accept button if present (multi-language)."""
    try:
        buttons = page.locator("button")
        for i in range(buttons.count()):
            try:
                btn_text = buttons.nth(i).inner_text().lower()
            except Exception:
                continue
            if any(kw in btn_text for kw in ["accept", "akzeptieren", "tout accepter", "aceptar", "i agree"]):
                buttons.nth(i).click()
                time.sleep(2)
                return True
        # Fallback: any button in a consent form
        form_btns = page.locator("form[action*='consent'] button")
        if form_btns.count() > 0:
            form_btns.first.click()
            time.sleep(2)
            return True
    except Exception:
        pass
    return False


def _extract_name(page) -> Optional[str]:
    """Extract the venue name from the Google Maps place page."""
    try:
        # Google Maps shows the place name in an h1
        h1 = page.locator("h1")
        if h1.count() > 0:
            return h1.first.inner_text().strip()
    except Exception:
        pass
    return None


# ── Batch Operations ──────────────────────────────────────────────────────────

def batch_resolve(csv_path: str, max_venues: int = 50, delay: float = 2.0):
    """
    Batch resolve venues from a CSV file. Skips already-cached.
    Resolves up to max_venues new venues.
    """
    import csv

    cache = load_cache()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Find venues needing resolution
    to_resolve = []
    for row in rows:
        name = row.get("name", "").strip()
        address = row.get("address", "").strip()
        if not name:
            continue
        key = cache_key(name, address)
        if key not in cache or not cache[key].get("google_rating"):
            to_resolve.append({"name": name, "address": address, "key": key})

    log.info(f"Need to resolve: {len(to_resolve)} venues (have {len(cache)} cached)")
    to_resolve = to_resolve[:max_venues]
    log.info(f"Resolving: {len(to_resolve)} venues this run")

    if not to_resolve:
        log.info("Nothing to resolve — all cached!")
        return

    resolved = 0
    failed = 0

    # Open one browser session for all venues
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        log.error("camoufox not installed")
        return

    with Camoufox(headless=True) as browser:
        page = browser.new_page()

        # Accept consent
        page.goto("https://www.google.com/maps/@22.3,114.2,12z",
                  wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)
        _accept_consent(page)

        for i, v in enumerate(to_resolve):
            try:
                query = f"{v['name']} {v['address']} Hong Kong"
                url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(3)

                text = page.inner_text("body")

                # Handle consent re-appearance
                if "consent" in page.url:
                    _accept_consent(page)
                    time.sleep(2)
                    text = page.inner_text("body")

                m = re.search(r"(\d[.,]\d)\s*\((\d[\d.,]*)\)", text)
                if m:
                    rating = float(m.group(1).replace(",", "."))
                    reviews = int(m.group(2).replace(",", "").replace(".", ""))

                    if 1.0 <= rating <= 5.0:
                        cache[v["key"]] = {
                            "google_rating": rating,
                            "google_reviews": reviews,
                            "google_name": _extract_name(page) or v["name"],
                            "resolved": True,
                            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        }
                        resolved += 1
                        log.info(f"  [{i+1}/{len(to_resolve)}] ✅ {v['name']}: ⭐{rating} ({reviews})")
                    else:
                        failed += 1
                        log.warning(f"  [{i+1}/{len(to_resolve)}] ⚠️ {v['name']}: invalid data")
                else:
                    failed += 1
                    log.warning(f"  [{i+1}/{len(to_resolve)}] ❌ {v['name']}: no rating found")

                # Save cache every 10 venues
                if (i + 1) % 10 == 0:
                    save_cache(cache)
                    log.info(f"  Cache saved ({len(cache)} entries)")

                time.sleep(delay)

            except Exception as e:
                failed += 1
                log.error(f"  [{i+1}/{len(to_resolve)}] ❌ {v['name']}: {e}")

        browser.close()

    # Final save
    save_cache(cache)
    log.info(f"\nDone: {resolved} resolved, {failed} failed. Cache: {len(cache)} total")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Google Maps Rating Resolver")
    parser.add_argument("--venue", type=str, help="Single venue name to resolve")
    parser.add_argument("--address", type=str, default="", help="Venue address")
    parser.add_argument("--batch", action="store_true", help="Batch resolve from CSV")
    parser.add_argument("--csv", type=str, default="data/merged_places.csv", help="CSV path")
    parser.add_argument("--max", type=int, default=50, help="Max venues to resolve per run")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between requests (seconds)")
    parser.add_argument("--stats", action="store_true", help="Show cache stats")

    args = parser.parse_args()

    if args.stats:
        cache = load_cache()
        resolved = sum(1 for v in cache.values() if v.get("google_rating"))
        print(f"Cache: {len(cache)} entries, {resolved} with Google ratings")
        if cache:
            # Show a few examples
            for key, val in list(cache.items())[:5]:
                name = key.split("|")[0]
                print(f"  {name}: ⭐{val.get('google_rating', 'N/A')} ({val.get('google_reviews', 'N/A')} reviews)")
        return

    if args.venue:
        cache = load_cache()
        result = resolve_venue(args.venue, args.address)
        if result:
            key = cache_key(args.venue, args.address)
            cache[key] = result
            save_cache(cache)
            print(f"Resolved: ⭐{result['google_rating']} ({result['google_reviews']} reviews)")
        else:
            print("Failed to resolve")
        return

    if args.batch:
        batch_resolve(args.csv, max_venues=args.max, delay=args.delay)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
