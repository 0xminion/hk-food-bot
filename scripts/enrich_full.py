#!/usr/bin/env python3
"""
Enrich remaining venues by querying ALL pages of every cuisine ID.
Respects API limits with 1.2s delay. Saves incrementally after each cuisine.
"""
import csv, json, time, sys, os
from pathlib import Path

import requests

DATA_DIR = Path("/home/linuxuser/workspaces/default/hk-food-bot/data")
OR_CSV = DATA_DIR / "openrice_places.csv"

BASE_URL = "https://www.openrice.com/api/pois"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Accept": "application/json",
    "Accept-Language": "en,zh;q=0.9",
    "Referer": "https://www.openrice.com/en/hongkong/restaurants",
}

COLUMNS = [
    "name", "type", "cuisine_tags", "style_tags", "address", "address_en",
    "lat", "lng", "district", "google_rating", "or_rating", "or_score",
    "review_count", "bookmark_count", "price_range", "google_place_id",
    "booking_url", "booking_platform", "opening_hours", "is_open_now",
    "popular_dishes", "award_status", "source_url", "is_secret_gem",
    "last_updated",
]

NEW_FIELDS = {"address_en", "district", "or_score", "bookmark_count",
              "price_range", "is_open_now", "popular_dishes", "award_status"}

CUISINE_IDS = [
    None,  # default listing (broadest)
    2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2013, 2021, 2022, 2023, 2024,
    6000, 3001, 3002, 3004, 3005, 3006, 3007, 3008, 3009, 3010, 3011, 3012, 3013, 3021,
    4000, 4001, 4002, 4003, 4004, 4005, 4006, 5001, 5004, 5005,
]

MAX_PAGES = 200
DELAY = 1.2  # seconds between requests


def needs_enrichment(row: dict) -> bool:
    return not any(row.get(f) for f in NEW_FIELDS)


def save_csv(rows: list[dict]):
    with open(OR_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    # Load existing
    rows = []
    lookup = {}
    with open(OR_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for col in COLUMNS:
                if col not in row:
                    row[col] = ""
            key = f"{row['name'].strip().lower()}|{row.get('address','').strip().lower()}"
            rows.append(row)
            lookup[key] = row

    total = len(rows)
    needs = sum(1 for r in rows if needs_enrichment(r))
    already = total - needs
    print(f"Loaded {total} venues: {already} enriched, {needs} need enrichment")
    print(f"Will query {len(CUISINE_IDS)} cuisine IDs × up to {MAX_PAGES} pages")
    print(f"Delay: {DELAY}s between requests")
    print()

    session = requests.Session()
    session.headers.update(HEADERS)

    total_enriched = 0
    total_new = 0
    api_calls = 0

    for cid_idx, cid in enumerate(CUISINE_IDS):
        label = f"cuisine={cid}" if cid else "default"
        cid_enriched = 0
        cid_new = 0
        empty_streak = 0

        for page in range(1, MAX_PAGES + 1):
            params = {"uiLangId": 1, "uiCityId": 1, "page": page, "sortBy": "DEFAULT"}
            if cid is not None:
                params["cuisineId"] = cid

            try:
                resp = session.get(BASE_URL, params=params, timeout=15)
                data = resp.json()
                results = data.get("searchResult", {}).get("paginationResult", {}).get("results", [])
                api_calls += 1
            except Exception as e:
                print(f"  [{label}] p{page}: API error: {e}")
                time.sleep(DELAY * 3)
                continue

            if not results:
                empty_streak += 1
                if empty_streak >= 3:
                    break
                time.sleep(DELAY)
                continue

            empty_streak = 0
            page_enriched = 0
            page_new = 0

            for r in results:
                name = r.get("name", "").strip()
                addr = r.get("address", "").strip()
                if not name:
                    continue
                key = f"{name.lower()}|{addr.lower()}"

                new_data = {
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

                if key in lookup:
                    row = lookup[key]
                    if needs_enrichment(row):
                        for k, v in new_data.items():
                            if v and not row.get(k):
                                row[k] = v
                        page_enriched += 1
                else:
                    # New venue not in CSV — add it
                    from scrapers.openrice import parse_venue
                    venue = parse_venue(r)
                    if venue:
                        for col in COLUMNS:
                            if col not in venue:
                                venue[col] = ""
                        rows.append(venue)
                        lookup[key] = venue
                        page_new += 1

            cid_enriched += page_enriched
            cid_new += page_new
            total_enriched += page_enriched
            total_new += page_new

            time.sleep(DELAY)

        # Save after each cuisine
        save_csv(rows)
        remaining = sum(1 for r in rows if needs_enrichment(r))
        print(f"[{cid_idx+1}/{len(CUISINE_IDS)}] {label}: {cid_enriched} enriched, {cid_new} new | "
              f"Total: {total_enriched} enriched, {total_new} new | "
              f"Remaining: {remaining}/{len(rows)} | API calls: {api_calls}")

    # Final save
    save_csv(rows)
    remaining = sum(1 for r in rows if needs_enrichment(r))
    pct = (len(rows) - remaining) * 100 // len(rows)
    print(f"\n{'='*60}")
    print(f"Done: {total_enriched} enriched, {total_new} new venues")
    print(f"Final: {len(rows)} venues, {pct}% enriched ({remaining} remaining)")
    print(f"API calls: {api_calls}")
    print(f"Saved to {OR_CSV}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path("/home/linuxuser/workspaces/default/hk-food-bot")))
    main()
