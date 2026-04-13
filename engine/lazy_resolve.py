"""
Lazy Google Rating Resolver

Runs in background after recommendation results are generated.
Checks which venues don't have Google data cached, then resolves them
via Camoufox for future queries.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent.parent / "data" / "google_ratings_cache.json"
_RESOLVING: set[str] = set()  # Currently being resolved (avoid duplicates)
_LOCK = threading.Lock()


def _load_cache() -> dict:
    """Load the Google ratings cache."""
    if not _CACHE_FILE.exists():
        return {}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_cache(cache: dict):
    """Save cache atomically."""
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.rename(_CACHE_FILE)


def _resolve_single(name: str, address: str) -> Optional[dict]:
    """Resolve a single venue via Camoufox."""
    try:
        from camoufox.sync_api import Camoufox
        import re
        import time

        query = f"{name} {address} Hong Kong"
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

            # Search
            url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)

            text = page.inner_text("body")
            m = re.search(r"(\d[.,]\d)\s*\((\d[\d.,]*)\)", text)
            if m:
                rating = float(m.group(1).replace(",", "."))
                reviews = int(m.group(2).replace(",", "").replace(".", ""))
                if 1.0 <= rating <= 5.0:
                    browser.close()
                    return {"google_rating": rating, "google_reviews": reviews}

            browser.close()
    except Exception as e:
        logger.debug(f"Lazy resolve failed for {name}: {e}")
    return None


def _resolve_worker(venues: list[dict]):
    """Background worker to resolve venues."""
    cache = _load_cache()
    resolved = 0

    for v in venues:
        key = f"{v['name']}|{v['address']}"
        if key in cache and cache[key].get("google_rating"):
            continue

        result = _resolve_single(v["name"], v["address"])
        if result:
            from datetime import datetime, timezone
            result["resolved"] = True
            result["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            cache[key] = result
            resolved += 1
            logger.info(f"Lazy resolved: {v['name']} → ⭐{result['google_rating']}")

    if resolved > 0:
        _save_cache(cache)
        logger.info(f"Lazy resolve complete: {resolved} venues cached")

    # Clear resolving set
    with _LOCK:
        for v in venues:
            _RESOLVING.discard(f"{v['name']}|{v['address']}")


def lazy_resolve_places(places: list):
    """
    Trigger background Google resolution for places that don't have cached data.

    Non-blocking — spawns a thread. Results are cached for future queries.
    """
    cache = _load_cache()
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
    cache = _load_cache()
    key = f"{name}|{address}"
    return key not in cache or not cache[key].get("google_rating")
