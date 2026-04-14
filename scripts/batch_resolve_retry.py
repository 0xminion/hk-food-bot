#!/usr/bin/env python3
"""Retry failed Google resolutions with periodic browser restarts to avoid crashes."""
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
BATCH_SIZE = 200  # Restart browser after this many venues


def load_cache() -> dict:
    with open(CACHE_FILE) as f:
        return json.load(f)


def save_cache(cache: dict):
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.rename(CACHE_FILE)


def accept_consent(page):
    """Accept Google consent in multiple languages (English, German, French, etc.)."""
    try:
        # Try common button texts across languages
        selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Alle akzeptieren')",
            "button:has-text('Tout accepter')",
            "button:has-text('Aceptar todo')",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "form[action*='consent'] button",  # Any button in consent form
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


def resolve_batch(to_resolve: list, cache: dict) -> tuple:
    """Resolve a batch of venues. Returns (resolved, failed)."""
    from camoufox.sync_api import Camoufox

    resolved = 0
    failed = 0
    start_time = time.time()

    with Camoufox(headless=True) as browser:
        page = browser.new_page()

        # Accept consent once
        page.goto("https://www.google.com/maps/@22.27,114.17,13z",
                  wait_until="domcontentloaded", timeout=20000)
        time.sleep(4)
        accept_consent(page)
        print("  Browser ready")

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
                    else:
                        failed += 1
                else:
                    failed += 1

                # Progress every 25
                done = i + 1
                if done % 25 == 0:
                    save_cache(cache)
                    elapsed = time.time() - start_time
                    rate = done / elapsed
                    eta = (len(to_resolve) - done) / rate / 60
                    print(f"  [{done}/{len(to_resolve)}] ✅{resolved} ❌{failed} | {rate:.1f}/s | ETA: {eta:.0f}min")

                time.sleep(1.5)

            except Exception as e:
                failed += 1
                if failed % 20 == 0:
                    print(f"  [{i+1}] {failed} failures so far: {type(e).__name__}")

    return resolved, failed


def main():
    cache = load_cache()
    print(f"Cache loaded: {len(cache)} entries")

    with open(SELECTION_FILE) as f:
        venues = list(csv.DictReader(f))

    # Find venues not yet cached
    to_resolve = []
    for v in venues:
        key = f"{v['name']}|{v['address']}"
        if key not in cache or not cache[key].get("google_rating"):
            to_resolve.append(v)
    print(f"Need to resolve: {len(to_resolve)} (skipping {len(venues) - len(to_resolve)} cached)")

    if not to_resolve:
        print("All venues already cached!")
        return

    total_resolved = 0
    total_failed = 0

    # Process in batches with browser restarts
    for batch_start in range(0, len(to_resolve), BATCH_SIZE):
        batch = to_resolve[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(to_resolve) + BATCH_SIZE - 1) // BATCH_SIZE

        print(f"\n--- Batch {batch_num}/{total_batches} ({len(batch)} venues) ---")
        res, fail = resolve_batch(batch, cache)
        save_cache(cache)
        total_resolved += res
        total_failed += fail
        print(f"  Batch done: ✅{res} ❌{fail} | Total: ✅{total_resolved} ❌{total_failed}")

    print(f"\nDone: {total_resolved} resolved, {total_failed} failed. Cache: {len(load_cache())} total")


if __name__ == "__main__":
    main()
