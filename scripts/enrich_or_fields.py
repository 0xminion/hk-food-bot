#!/usr/bin/env python3
"""
Enrich existing CSV with new fields from OpenRice API.
Queries first 5 pages per cuisine ID — fast but partial coverage.
"""
import csv, json, time, sys
from pathlib import Path
import requests

DATA_DIR = Path("/home/linuxuser/workspaces/default/hk-food-bot/data")
OR_CSV = DATA_DIR / "openrice_places.csv"

BASE_URL = "https://www.openrice.com/api/pois"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
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

NEW_FIELDS = {"address_en", "district", "or_score", "bookmark_count", "price_range",
              "is_open_now", "popular_dishes", "award_status"}

# All cuisine IDs from the scraper
CUISINE_IDS = [
    None,  # default listing
    2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2013, 2021, 2022, 2023, 2024,
    6000, 3001, 3002, 3004, 3005, 3006, 3007, 3008, 3009, 3010, 3011, 3012, 3013, 3021,
    4000, 4001, 4002, 4003, 4004, 4005, 4006, 5001, 5004, 5005,
]

def needs_enrichment(row):
    return not any(row.get(f) for f in NEW_FIELDS)

def main():
    # Load existing
    rows = []
    lookup = {}
    with open(OR_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = f"{row['name'].strip().lower()}|{row.get('address','').strip().lower()}"
            rows.append(row)
            lookup[key] = row

    total = len(rows)
    needs = sum(1 for r in rows if needs_enrichment(r))
    print(f"Loaded {total} rows, {needs} need enrichment")

    session = requests.Session()
    session.headers.update(HEADERS)

    enriched = 0
    for cid in CUISINE_IDS:
        label = f"c={cid}" if cid else "default"
        for page in range(1, 6):  # First 5 pages per cuisine
            params = {"uiLangId": 1, "uiCityId": 1, "page": page, "sortBy": "DEFAULT"}
            if cid:
                params["cuisineId"] = cid
            try:
                resp = session.get(BASE_URL, params=params, timeout=15)
                data = resp.json()
                results = data.get("searchResult", {}).get("paginationResult", {}).get("results", [])
            except Exception as e:
                print(f"  {label} p{page}: error {e}")
                break

            if not results:
                break

            for r in results:
                name = r.get("name", "").strip()
                addr = r.get("address", "").strip()
                if not name:
                    continue
                key = f"{name.lower()}|{addr.lower()}"
                row = lookup.get(key)
                if not row or not needs_enrichment(row):
                    continue

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
                for k, v in new_data.items():
                    if v:
                        row[k] = v
                enriched += 1

            time.sleep(0.8)

        if enriched % 500 == 0 and enriched > 0:
            print(f"  {label}: enriched so far: {enriched}")

    # Write back
    with open(OR_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    remaining = sum(1 for r in rows if needs_enrichment(r))
    print(f"\nEnriched {enriched} venues. Remaining without new fields: {remaining}/{total}")
    print(f"Written to {OR_CSV}")

if __name__ == "__main__":
    main()
