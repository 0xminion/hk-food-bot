"""
Lazy Google Rating Resolver

Runs in background after recommendation results are generated.
Checks which venues don't have Google data cached, then resolves them
via Camoufox for future queries.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_RESOLVING: set[str] = set()  # Currently being resolved (avoid duplicates)
_LOCK = threading.Lock()


def _resolve_worker(venues: list[dict]):
    """Background worker to resolve venues using a single browser session."""
    from data.google_cache import get_cache, save_cache

    cache = get_cache()
    # Take a local copy so we don't hold the lock during browser ops
    local_cache = dict(cache)
    resolved = 0

    try:
        from camoufox.sync_api import Camoufox
        import re
        import time

        with Camoufox(headless=True) as browser:
            page = browser.new_page()

            # Consent
            page.goto("https://www.google.com/maps/@22.3,114.2,12z",
                      wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)
            try:
                btns = page.locator("button")
                for i in range(btns.count()):
                    t = btns.nth(i).inner_text().lower()
                    if "accept" in t or "akzeptieren" in t:
                        btns.nth(i).click()
                        time.sleep(2)
                        break
            except Exception:
                pass

            for v in venues:
                key = f"{v['name']}|{v['address']}"
                if key in local_cache and local_cache[key].get("google_rating"):
                    continue

                try:
                    from urllib.parse import quote_plus
                    query = f"{v['name']} {v['address']} Hong Kong"
                    url = f"https://www.google.com/maps/search/{quote_plus(query)}"
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(3)

                    text = page.inner_text("body")
                    m = re.search(r"(\d[.,]\d)\s*\((\d[\d.,]*)\)", text)
                    if m:
                        rating = float(m.group(1).replace(",", "."))
                        reviews = int(m.group(2).replace(",", "").replace(".", ""))
                        if 1.0 <= rating <= 5.0:
                            from datetime import datetime, timezone
                            local_cache[key] = {
                                "google_rating": rating,
                                "google_reviews": reviews,
                                "resolved": True,
                                "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            }
                            resolved += 1
                            logger.info(f"Resolved: {v['name']} -> {rating}")

                    time.sleep(1)  # Rate limit
                except Exception as e:
                    logger.debug(f"Resolve failed for {v['name']}: {e}")
                    continue

            browser.close()

    except Exception as e:
        logger.error(f"Batch resolve failed: {e}")

    if resolved > 0:
        from data.google_cache import merge_and_save
        merge_and_save(local_cache)
        logger.info(f"Batch resolve complete: {resolved} venues cached")

    # Clear resolving set
    with _LOCK:
        for v in venues:
            _RESOLVING.discard(f"{v['name']}|{v['address']}")


def lazy_resolve_places(places: list):
    """
    Trigger background Google resolution for places that don't have cached data.

    Non-blocking — spawns a thread. Results are cached for future queries.
    """
    from data.google_cache import get_cache

    cache = get_cache()
    to_resolve = []

    for p in places:
        key = f"{p.name}|{p.address}"
        if key not in cache or not cache[key].get("google_rating"):
            with _LOCK:
                if key not in _RESOLVING:
                    _RESOLVING.add(key)
                    to_resolve.append({"name": p.name, "address": p.address})

    if not to_resolve:
        return

    logger.info(f"Lazy resolve: spawning background thread for {len(to_resolve)} venues")
    thread = threading.Thread(target=_resolve_worker, args=(to_resolve,), daemon=True)
    thread.start()


def needs_google_resolution(name: str, address: str) -> bool:
    """Check if a venue needs Google resolution."""
    from data.google_cache import get_cache
    cache = get_cache()
    key = f"{name}|{address}"
    return key not in cache or not cache[key].get("google_rating")
