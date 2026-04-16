#!/usr/bin/env python3
"""
Quick schema migration: add empty new columns to existing CSV.
Full enrichment will happen on next scraper run.
"""
import csv
from pathlib import Path

DATA_DIR = Path("/home/linuxuser/workspaces/default/hk-food-bot/data")
OR_CSV = DATA_DIR / "openrice_places.csv"

NEW_COLUMNS = [
    "name", "type", "cuisine_tags", "style_tags", "address", "address_en",
    "lat", "lng", "district", "google_rating", "or_rating", "or_score",
    "review_count", "bookmark_count", "price_range", "google_place_id",
    "booking_url", "booking_platform", "opening_hours", "is_open_now",
    "popular_dishes", "award_status", "source_url", "is_secret_gem",
    "last_updated",
]

rows = []
with open(OR_CSV, "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        for col in NEW_COLUMNS:
            if col not in row:
                row[col] = ""
        rows.append(row)

with open(OR_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=NEW_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in NEW_COLUMNS})

print(f"Migrated {len(rows)} rows to new schema")
