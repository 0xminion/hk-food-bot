#!/usr/bin/env python3
"""
Migrate openrice_places.csv to new schema with enriched fields.

For venues missing new fields (district, price_range, bookmark_count, etc.),
queries the OpenRice API to backfill.
"""

import csv
import json
import time
import sys
from pathlib import Path
from datetime import datetime, timezone

import requests

DATA_DIR = Path("/home/linuxuser/workspaces/default/hk-food-bot/data")
OR_CSV = DATA_DIR / "openrice_places.csv"

BASE_URL = "https://www.openrice.com/api/pois"
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "application/json",
    "Accept-Language": "en,zh;q=0.9",
    "Referer": "https://www.openrice.com/en/hongkong/restaurants",
}

NEW_COLUMNS = [
    "name", "type", "cuisine_tags", "style_tags", "address", "address_en",
    "lat", "lng", "district", "google_rating", "or_rating", "or_score",
    "review_count", "bookmark_count", "price_range", "google_place_id",
    "booking_url", "booking_platform", "opening_hours", "is_open_now",
    "popular_dishes", "award_status", "source_url", "is_secret_gem",
    "last_updated",
]


def has_new_fields(row: dict) -> bool:
    """Check if a row already has new fields populated."""
    return bool(row.get("district") or row.get("price_range") or row.get("bookmark_count"))


def enrich_from_page(page_results: list[dict]) -> dict[str, dict]:
    """Build a lookup dict from API results: name|address -> enriched fields."""
    enriched = {}
    for r in page_results:
        name = r.get("name", "").strip()
        address = r.get("address", "").strip()
        if not name:
            continue
        key = f"{name.lower()}|{address.lower()}"
        enriched[key] = {
            "address_en": r.get("addressOtherLang", ""),
            "district": (r.get("district") or {}).get("name", ""),
            "or_score": str(r.get("orScore", "")),
            "bookmark_count": str(r.get("bookmarkedUserCount", 0)),
            "price_range": (r.get("priceUI") or "").strip(),
            "is_open_now": str(r.get("openNow", False)),
            "popular_dishes": json.dumps(
                [t.get("name", "") for t in r.get("tags", []) if t.get("name")],
                ensure_ascii=False,
            ),
            "award_status": str(r.get("awardStatus", 0)),
        }
    return enriched


def scrape_and_enrich(max_pages: int = 200):
    """Re-scrape all cuisine IDs, enriching existing venues + adding new ones."""

    # Load existing data
    existing_rows = []
    existing_keys = set()
    if OR_CSV.exists():
        with open(OR_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = f"{row.get('name','').strip().lower()}|{row.get('address','').strip().lower()}"
                existing_keys.add(key)
                existing_rows.append(row)

    print(f"Existing: {len(existing_rows)} venues, {sum(1 for r in existing_rows if has_new_fields(r))} already enriched")

    session = requests.Session()
    session.headers.update(HEADERS)

    # Cuisine IDs to scrape
    sys.path.insert(0, str(Path("/home/linuxuser/workspaces/default/hk-food-bot")))
    from scrapers.openrice import DEFAULT_CUISINE_IDS, classify_venue, parse_venue
    cuisine_ids = [None] + DEFAULT_CUISINE_IDS

    enriched_count = 0
    new_count = 0
    # key -> new fields
    all_enriched: dict[str, dict] = {}
    new_venues: list[dict] = []

    for cuisine_id in cuisine_ids:
        label = f"cuisine={cuisine_id}" if cuisine_id else "default"
        print(f"Scraping: {label}")

        page = 1
        empty_streak = 0
        while page <= max_pages:
            params = {
                "uiLangId": 1, "uiCityId": 1, "page": page, "sortBy": "DEFAULT",
            }
            if cuisine_id is not None:
                params["cuisineId"] = cuisine_id

            try:
                resp = session.get(BASE_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  Error page {page}: {e}")
                break

            results = data.get("searchResult", {}).get("paginationResult", {}).get("results", [])
            if not results:
                empty_streak += 1
                if empty_streak >= 3:
                    break
                page += 1
                time.sleep(1.0)
                continue

            empty_streak = 0
            page_enriched = enrich_from_page(results)
            all_enriched.update(page_enriched)

            # Check for new venues
            for r in results:
                venue = parse_venue(r)
                if not venue:
                    continue
                key = f"{venue['name'].strip().lower()}|{venue['address'].strip().lower()}"
                if key not in existing_keys:
                    existing_keys.add(key)
                    new_venues.append(venue)
                    new_count += 1

            page += 1
            time.sleep(1.0)

        print(f"  Done: {len(all_enriched)} enriched, {new_count} new")

    # Apply enrichment to existing rows
    for row in existing_rows:
        key = f"{row.get('name','').strip().lower()}|{row.get('address','').strip().lower()}"
        enrichment = all_enriched.get(key, {})
        if enrichment and not has_new_fields(row):
            for field, value in enrichment.items():
                if not row.get(field):
                    row[field] = value
                    enriched_count += 1
            # Normalize row to new columns
            for col in NEW_COLUMNS:
                if col not in row:
                    row[col] = ""

    # Write output
    all_rows = existing_rows + new_venues
    # Normalize all rows to new columns
    for row in all_rows:
        for col in NEW_COLUMNS:
            if col not in row:
                row[col] = ""

    with open(OR_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NEW_COLUMNS)
        writer.writeheader()
        for row in all_rows:
            writer.writerow({col: row.get(col, "") for col in NEW_COLUMNS})

    print(f"\nDone: {enriched_count} fields enriched, {new_count} new venues, {len(all_rows)} total")
    print(f"Written to {OR_CSV}")


if __name__ == "__main__":
    scrape_and_enrich()
