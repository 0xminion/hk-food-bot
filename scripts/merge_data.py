#!/usr/bin/env python3
"""
Rebuild merged_places.csv from OpenRice + Google Maps sources.

Fixes:
- Preserves ALL bars (650 were previously lost due to aggressive name dedup)
- Deduplicates by exact name+address (not name-only)
- Enriches with Google ratings cache
- Adds 'source' column
"""

import csv
import json
import os
import re
import sys
from pathlib import Path
from collections import Counter

# Ensure project root is on sys.path for utils imports
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.name_norm import normalize_name, build_name_index

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OR_CSV = DATA_DIR / "openrice_places.csv"
GM_CSV = DATA_DIR / "sample_places.csv"
CACHE_FILE = DATA_DIR / "google_ratings_cache.json"
OUTPUT = DATA_DIR / "merged_places.csv"

OUTPUT_COLUMNS = [
    "name", "type", "cuisine_tags", "style_tags", "address", "address_en",
    "lat", "lng", "district", "google_rating", "or_rating", "or_score",
    "review_count", "bookmark_count", "price_range", "google_place_id",
    "booking_url", "booking_platform", "opening_hours", "is_open_now",
    "popular_dishes", "award_status", "source_url", "is_secret_gem",
    "last_updated", "source",
]


def load_google_cache() -> dict:
    """Load Google ratings cache."""
    if not CACHE_FILE.exists():
        return {}
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def make_key(name: str, address: str) -> str:
    """Create dedup key from name + address (case-insensitive)."""
    return f"{name.strip().lower()}|{address.strip().lower()}"


def _sanitize_bool_field(value: str) -> str:
    """Sanitize boolean field — reject URLs and non-boolean values."""
    if not value:
        return "false"
    v = str(value).strip().lower()
    if v in ("1", "true"):
        return "true"
    if v in ("0", "false", ""):
        return "false"
    # Reject anything that looks like a URL or other garbage
    if v.startswith("http") or "/" in v or "." in v:
        return "false"
    return "false"


def enrich_google_rating(row: dict, cache: dict, name_index: dict | None = None) -> dict:
    """Enrich row with Google ratings from cache if not already present.
    Tries exact name|addr match first, falls back to name-index lookup."""
    cache_key = f"{row['name'].strip()}|{row.get('address', '').strip()}"
    cached = cache.get(cache_key)
    if not cached and name_index is not None:
        # O(1) fallback: pre-built name index
        norm = normalize_name(row['name'].strip())
        matches = name_index.get(norm, [])
        if matches:
            cached = matches[0][1]  # Most reviewed entry
    elif not cached:
        # Legacy fallback: linear scan (shouldn't happen if name_index is passed)
        name_lower = row['name'].strip().lower()
        for ck, cv in cache.items():
            if ck.split("|")[0].strip().lower() == name_lower:
                cached = cv
                break
    if cached and cached.get("google_rating") and not row.get("google_rating"):
        row["google_rating"] = cached["google_rating"]
        row["review_count"] = max(
            int(row.get("review_count", 0) or 0),
            int(cached.get("google_reviews", 0) or 0),
        )
    return row


def normalize_tags(raw: str) -> str:
    """Normalize tag format to JSON list string."""
    if not raw:
        return "[]"
    raw = raw.strip()
    # Already JSON — parse and re-serialize to fix any format issues
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                # Clean: strip backslash-escaped quotes, lowercase, deduplicate
                clean = []
                seen = set()
                for t in parsed:
                    if not isinstance(t, str):
                        continue
                    t = t.strip().strip("\\\"").strip("\"").strip("'").lower()
                    if t and t not in seen:
                        seen.add(t)
                        clean.append(t)
                return json.dumps(clean, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
    # Comma-separated
    tags = []
    seen = set()
    for t in raw.split(","):
        t = t.strip().strip("\\\"").strip("\"").strip("'").lower()
        if t and t not in seen:
            seen.add(t)
            tags.append(t)
    return json.dumps(tags, ensure_ascii=False)


def _load_openrice_data(path: Path, venues: dict, name_index: dict | None, cache: dict) -> tuple[int, int, int]:
    """Load OpenRice CSV into venues dict. Returns (row_count, bar_count, dupe_count)."""
    or_count = or_bars = or_dupes = 0
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row.get("name", "").strip()
            if not name:
                continue
            address = row.get("address", "").strip()
            key = make_key(name, address)
            or_count += 1

            venue = {
                "name": name,
                "type": row.get("type", "restaurant").strip().lower(),
                "cuisine_tags": normalize_tags(row.get("cuisine_tags", "")),
                "style_tags": normalize_tags(row.get("style_tags", "")),
                "address": address,
                "address_en": row.get("address_en", ""),
                "lat": row.get("lat", ""),
                "lng": row.get("lng", ""),
                "district": row.get("district", ""),
                "google_rating": row.get("google_rating", ""),
                "or_rating": row.get("or_rating", ""),
                "or_score": row.get("or_score", ""),
                "review_count": row.get("review_count", "0"),
                "bookmark_count": row.get("bookmark_count", "0"),
                "price_range": row.get("price_range", ""),
                "google_place_id": row.get("google_place_id", ""),
                "booking_url": row.get("booking_url", ""),
                "booking_platform": row.get("booking_platform", ""),
                "opening_hours": row.get("opening_hours", ""),
                "is_open_now": row.get("is_open_now", "False"),
                "popular_dishes": row.get("popular_dishes", "[]"),
                "award_status": row.get("award_status", "0"),
                "source_url": row.get("source_url", ""),
                "is_secret_gem": _sanitize_bool_field(row.get("is_secret_gem", "false")),
                "last_updated": row.get("last_updated", ""),
                "source": "openrice",
            }

            if key in venues:
                or_dupes += 1
                existing = venues[key]
                if not existing.get("or_rating") and venue.get("or_rating"):
                    venues[key] = venue
            else:
                venues[key] = venue
                if venue["type"] == "bar":
                    or_bars += 1
    return or_count, or_bars, or_dupes


def _load_google_maps_data(path: Path, venues: dict) -> tuple[int, int, int]:
    """Load Google Maps CSV into venues dict. Returns (row_count, new_count, bar_count)."""
    gm_count = gm_new = gm_bars = 0
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row.get("name", "").strip()
            if not name:
                continue
            address = row.get("address", "").strip()
            key = make_key(name, address)
            gm_count += 1

            venue = {
                "name": name,
                "type": row.get("type", "restaurant").strip().lower(),
                "cuisine_tags": normalize_tags(row.get("cuisine_tags", "")),
                "style_tags": normalize_tags(row.get("style_tags", "")),
                "address": address,
                "address_en": row.get("address_en", ""),
                "lat": row.get("lat", ""),
                "lng": row.get("lng", ""),
                "district": row.get("district", ""),
                "google_rating": row.get("google_rating", ""),
                "or_rating": row.get("or_rating", ""),
                "or_score": row.get("or_score", ""),
                "review_count": row.get("review_count", "0"),
                "bookmark_count": row.get("bookmark_count", "0"),
                "price_range": row.get("price_range", ""),
                "google_place_id": row.get("google_place_id", ""),
                "booking_url": row.get("booking_url", ""),
                "booking_platform": row.get("booking_platform", ""),
                "opening_hours": row.get("opening_hours", ""),
                "is_open_now": row.get("is_open_now", "False"),
                "popular_dishes": row.get("popular_dishes", "[]"),
                "award_status": row.get("award_status", "0"),
                "source_url": row.get("source_url", ""),
                "is_secret_gem": _sanitize_bool_field(row.get("is_secret_gem", "false")),
                "last_updated": row.get("last_updated", ""),
                "source": "google_maps",
            }

            if key not in venues:
                gm_new += 1
                if venue["type"] == "bar":
                    gm_bars += 1
            venues[key] = venue  # GM data takes priority
    return gm_count, gm_new, gm_bars


def _enrich_venues(venues: dict, cache: dict, name_index: dict | None) -> int:
    """Enrich all venues with Google cache ratings. Returns enriched count."""
    enriched = 0
    for key, venue in venues.items():
        before = venue.get("google_rating")
        venue = enrich_google_rating(venue, cache, name_index)
        venues[key] = venue
        if venue.get("google_rating") and not before:
            enriched += 1
    return enriched


def _safe_lat(val) -> str:
    try:
        f = float(val)
        if -90 <= f <= 90 and f != 0:
            return str(f)
    except (ValueError, TypeError):
        pass
    return ""


def _safe_lng(val) -> str:
    try:
        f = float(val)
        if -180 <= f <= 180 and f != 0:
            return str(f)
    except (ValueError, TypeError):
        pass
    return ""


def _normalize_bar_tags(venue: dict) -> None:
    """Merge style tags into cuisine tags for bars and detect cocktail bars by name."""
    if venue["type"] != "bar":
        return
    try:
        cuisine = json.loads(venue.get("cuisine_tags", "[]"))
        styles = json.loads(venue.get("style_tags", "[]"))
        drink_styles = {"speakeasy", "lounge", "rooftop-bar", "dive-bar", "pub", "izakaya", "chill-bar", "cocktail-bar"}
        for s in styles:
            if s in drink_styles and s not in cuisine:
                cuisine.append(s)

        name_lower = venue["name"].lower()
        strong_cocktail = ["cocktail", "speakeasy", "mixology"]
        spirit_bars = ["gin parlour", "whisky bar", "rum bar", "tequila bar", "mezcal bar"]
        is_lounge = "lounge" in name_lower and not any(r in name_lower for r in ["restaurant", "grill house", "steak"])

        is_cocktail = False
        if any(kw in name_lower for kw in strong_cocktail):
            is_cocktail = True
        elif any(kw in name_lower for kw in spirit_bars):
            is_cocktail = True
        elif is_lounge:
            is_cocktail = True
        elif (name_lower.endswith(" bar") and len(venue["name"].split()) <= 3
              and not any(r in name_lower for r in ["restaurant", "grill", "kitchen", "steak", "pizza", "oyster", "tapas", "sports"])):
            is_cocktail = True

        if is_cocktail and "cocktail-bar" not in cuisine:
            cuisine.append("cocktail-bar")

        venue["cuisine_tags"] = json.dumps(cuisine, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass


def _write_output(venues: dict, output_path: Path, columns: list) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for venue in venues.values():
            row = {col: venue.get(col, "") for col in columns}
            writer.writerow(row)


def main():
    cache = load_google_cache()
    print(f"Google cache: {len(cache)} entries")

    _name_index = build_name_index(cache)
    print(f"Name index: {len(_name_index)} unique franchise names")

    venues: dict[str, dict] = {}

    or_count, or_bars, or_dupes = _load_openrice_data(OR_CSV, venues, _name_index, cache)
    print(f"OpenRice: {or_count} rows -> {len(venues)} unique, {or_dupes} exact dupes, {or_bars} bars")

    gm_count, gm_new, gm_bars = _load_google_maps_data(GM_CSV, venues)
    print(f"Google Maps: {gm_count} rows, {gm_new} new, {gm_bars} new bars")

    enriched = _enrich_venues(venues, cache, _name_index)
    print(f"Enriched {enriched} venues with Google cache ratings")

    valid = 0
    for v in venues.values():
        try:
            lat = float(v.get("lat", 0) or 0)
            lng = float(v.get("lng", 0) or 0)
            if lat != 0 and lng != 0:
                valid += 1
        except (ValueError, TypeError):
            pass

        v["lat"] = _safe_lat(v.get("lat", ""))
        v["lng"] = _safe_lng(v.get("lng", ""))
        _normalize_bar_tags(v)

    print(f"Valid coordinates: {valid}/{len(venues)}")

    total_bars = sum(1 for v in venues.values() if v["type"] == "bar")
    total_restaurants = sum(1 for v in venues.values() if v["type"] == "restaurant")
    print(f"\nFinal: {len(venues)} venues ({total_restaurants} restaurants, {total_bars} bars)")

    cocktail_bars = [v for v in venues.values() if "cocktail-bar" in v.get("cuisine_tags", "")]
    print(f"Cocktail bars: {len(cocktail_bars)}")
    for cb in cocktail_bars:
        print(f"  {cb['name']} | {cb['source']}")

    _write_output(venues, OUTPUT, OUTPUT_COLUMNS)
    print(f"\nWritten to {OUTPUT}")


if __name__ == "__main__":
    main()
