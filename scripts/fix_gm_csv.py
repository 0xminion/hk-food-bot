#!/usr/bin/env python3
"""Fix sample_places.csv: properly quote fields with commas."""
import csv
from pathlib import Path

DATA_DIR = Path("/home/linuxuser/workspaces/default/hk-food-bot/data")
SRC = DATA_DIR / "sample_places.csv"

COLUMNS = [
    "name", "type", "cuisine_tags", "style_tags", "address", "lat", "lng",
    "google_rating", "review_count", "google_place_id", "booking_url",
    "booking_platform", "opening_hours", "source_url", "is_secret_gem",
    "last_updated", "distance_walk_m", "distance_drive_m",
]

# Read raw and fix
with open(SRC, "r", encoding="utf-8") as f:
    lines = f.read().strip().split("\n")

header = lines[0].split(",")
fixed_rows = []

for line in lines[1:]:
    parts = line.split(",")
    # Known field positions (0-indexed): lat=5, lng=6, google_rating=7
    # Find lat/lng by looking for float patterns
    import re
    float_pattern = re.compile(r'^-?\d+\.\d+$')
    
    # Find positions of lat and lng (first two floats after address)
    lat_idx = None
    for i, p in enumerate(parts):
        if float_pattern.match(p.strip()) and i > 3:
            lat_idx = i
            break
    
    if lat_idx is None:
        continue
    
    # Reconstruct: everything before lat is address (possibly with commas)
    name = parts[0]
    venue_type = parts[1]
    cuisine_tags = parts[2]  # May be quoted
    style_tags = parts[3]    # May be quoted
    address = ",".join(parts[4:lat_idx])
    rest = parts[lat_idx:]
    
    row = [name, venue_type, cuisine_tags, style_tags, address] + rest[:13]
    fixed_rows.append(row)

# Write properly
with open(SRC, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
    writer.writerow(COLUMNS)
    writer.writerows(fixed_rows)

print(f"Fixed {len(fixed_rows)} rows in {SRC}")
