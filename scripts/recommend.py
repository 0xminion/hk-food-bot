#!/usr/bin/env python3
"""
CLI adapter for HK Food Bot recommendation engine.
Parses structured arguments, runs the engine, outputs JSON for the agent to narrate.

Usage:
    python recommend.py --area "Wan Chai" --type eat --cuisine japanese --count 5
    python recommend.py --area "Central" --type drink --spot cocktail-bar --count 3
    python recommend.py --lat 22.279 --lng 114.175 --type eat --surprise --count 5
    python recommend.py --area "Causeway Bay" --type eat --query "spicy noodles" --count 5
"""
import argparse
import json
import logging
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.loader import load_places
from engine.recommender import recommend, RecommendationResult, AREA_SCOPE_NEIGHBORS, _resolve_area_coord
from engine.cuisine_groups import CUISINE_GROUPS, ABBREVIATIONS
from handlers.common import HK_AREAS
from engine.time_aware import get_open_status_label

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# All known areas
ALL_AREAS = {**HK_AREAS}
ALL_AREAS.update({
    "Jordan": (22.3064, 114.1717),
    "Yau Ma Tei": (22.3069, 114.1709),
    "North Point": (22.2910, 114.1970),
    "Prince Edward": (22.3247, 114.1686),
    "Kennedy Town": (22.2810, 114.1300),
})

# Natural language → cuisine mapping
NL_CUISINE_MAP = {
    # Sentiment/vibe → cuisines
    "spicy": ["thai", "sichuan", "indian", "korean", "mexican"],
    "comfort": ["cantonese", "japanese", "hong kong", "chinese"],
    "fancy": ["french", "italian", "japanese"],
    "cheap": [],  # handled by scoring
    "quick": ["japanese", "hong kong", "korean"],
    "healthy": ["japanese", "vegetarian", "salad"],
    "hearty": ["korean", "chinese", "american"],
    "light": ["japanese", "salad", "mediterranean"],
    "sharing": ["chinese", "korean", "spanish"],
    "romantic": ["french", "italian", "japanese"],
    "casual": ["hong kong", "thai", "vietnamese"],
    # Dish → cuisine
    "ramen": ["ramen"],
    "sushi": ["japanese"],
    "pizza": ["italian"],
    "steak": ["steakhouse", "american"],
    "dim sum": ["cantonese", "chinese"],
    "hotpot": ["hotpot"],
    "noodles": ["japanese", "chinese", "thai", "vietnamese", "malaysian", "ramen"],
    "bbq": ["korean", "japanese"],
    "seafood": ["seafood"],
    "tacos": ["mexican"],
    "curry": ["indian", "thai", "japanese"],
    "pho": ["vietnamese"],
    "pad thai": ["thai"],
    "dumplings": ["chinese", "korean"],
    "wings": ["american", "korean"],
    "brunch": ["western", "cafe"],
    "coffee": ["cafe"],
    "dessert": ["dessert", "bakery"],
    # Drink types
    "cocktail": ["cocktail-bar", "speakeasy", "rooftop-bar"],
    "cocktails": ["cocktail-bar", "speakeasy", "rooftop-bar"],
    "wine": ["wine-bar"],
    "beer": ["craft-beer", "pub"],
    "drinks": ["cocktail-bar", "wine-bar", "speakeasy", "rooftop-bar"],
    "bar": ["cocktail-bar", "wine-bar", "pub", "lounge"],
}


def resolve_cuisine(query: str | None) -> str | None:
    """Resolve a natural language query to a cuisine tag or group."""
    if not query:
        return None
    q = query.lower().strip()

    # Check if it's "surprise"
    if q in ("surprise", "surprise me", "random", "anything"):
        return "surprise"

    # Check abbreviation first
    if q in ABBREVIATIONS:
        return ABBREVIATIONS[q]

    # Check cuisine groups — expand to first tag for bar types, keep group name for food
    if q in CUISINE_GROUPS:
        tags = CUISINE_GROUPS[q]
        # For bar-type groups, return first concrete tag (engine filter needs exact tags)
        if all(t in ("cocktail-bar", "wine-bar", "speakeasy", "rooftop-bar", "craft-beer", "pub", "lounge", "bar", "izakaya") for t in tags):
            return tags[0]  # Use primary tag
        return q  # Return group name for food groups

    # Check NL map
    if q in NL_CUISINE_MAP:
        cuisines = NL_CUISINE_MAP[q]
        return cuisines[0] if cuisines else None

    # Direct match - return as-is, engine will fuzzy match
    return q


def resolve_area(area_name: str) -> tuple[float, float] | None:
    """Resolve area name to coordinates (case-insensitive)."""
    if not area_name:
        return None
    an = area_name.strip()
    # Exact match
    if an in ALL_AREAS:
        return ALL_AREAS[an]
    # Case-insensitive
    for name, coords in ALL_AREAS.items():
        if name.lower() == an.lower():
            return coords
    return None


def format_place(p, index: int) -> dict:
    """Format a Place into a structured dict for the agent."""
    ratings = {}
    if p.google_rating:
        ratings["google"] = {"rating": p.google_rating, "reviews": p.review_count or None}
    if p.or_rating:
        ratings["openrice"] = {"rating": round(p.or_rating, 2)}

    result = {
        "rank": index + 1,
        "name": p.name,
        "type": p.type,
        "cuisine_tags": p.cuisine_tags,
        "address": p.address,
        "ratings": ratings,
        "is_secret_gem": p.is_secret_gem,
    }

    if p.address_en:
        result["address_en"] = p.address_en
    if p.district:
        result["district"] = p.district
    if p.price_range:
        result["price_range"] = p.price_range
    if p.popular_dishes:
        result["popular_dishes"] = p.popular_dishes
    if p.bookmark_count:
        result["bookmark_count"] = p.bookmark_count
    if p.award_status:
        result["award_status"] = p.award_status
    if p.distance_walk_m:
        result["distance_m"] = p.distance_walk_m
    if p.distance_drive_m:
        result["drive_distance_m"] = p.distance_drive_m

    status = get_open_status_label(p.opening_hours)
    if status:
        result["open_status"] = status

    if p.source_url:
        result["source_url"] = p.source_url

    return result


def main():
    parser = argparse.ArgumentParser(description="HK Food Bot CLI recommender")
    parser.add_argument("--area", type=str, help="HK area name (e.g. 'Wan Chai', 'Central', 'TST')")
    parser.add_argument("--lat", type=float, help="Latitude (overrides area)")
    parser.add_argument("--lng", type=float, help="Longitude (overrides area)")
    parser.add_argument("--type", choices=["eat", "drink"], default="eat", help="eat or drink")
    parser.add_argument("--cuisine", type=str, help="Cuisine type or natural language (e.g. 'japanese', 'spicy', 'cocktails')")
    parser.add_argument("--surprise", action="store_true", help="Surprise me mode")
    parser.add_argument("--count", type=int, default=5, help="Number of recommendations")
    parser.add_argument("--no-time-filter", action="store_true", help="Skip open-now filtering")
    parser.add_argument("--include-personal", action="store_true", help="Include personal exclusion list (minion abc)")
    parser.add_argument("--query", type=str, help="Freeform query for cuisine resolution (e.g. 'spicy ramen near Causeway Bay')")
    parser.add_argument("--data-dir", type=str, help="Override data directory path")
    parser.add_argument("--all-areas", action="store_true", help="Search all areas (no distance filter)")

    args = parser.parse_args()

    # Resolve coordinates
    lat, lng = None, None
    area_name = args.area

    if args.lat and args.lng:
        lat, lng = args.lat, args.lng
    elif args.area:
        coords = resolve_area(args.area)
        if coords:
            lat, lng = coords
        else:
            print(json.dumps({"error": f"Unknown area: {args.area}. Known areas: {', '.join(sorted(ALL_AREAS.keys()))}"}))
            sys.exit(1)
    else:
        # Default: Central
        lat, lng = ALL_AREAS["Central"]
        area_name = "Central"

    # Resolve cuisine
    cuisine = None
    if args.surprise:
        cuisine = "surprise"
    elif args.cuisine:
        cuisine = resolve_cuisine(args.cuisine)
    elif args.query:
        cuisine = resolve_cuisine(args.query)

    # Map type
    place_type = "bar" if args.type == "drink" else "restaurant"

    # Load data
    data_dir = Path(args.data_dir) if args.data_dir else Path(__file__).parent.parent / "data"
    csv_path = data_dir / "merged_places.csv"
    if not csv_path.exists():
        print(json.dumps({"error": f"Data file not found: {csv_path}"}))
        sys.exit(1)

    all_places = load_places(csv_path)
    if not all_places:
        print(json.dumps({"error": "No places loaded from data file"}))
        sys.exit(1)

    # Run recommendation
    max_distance = 25000 if args.all_areas else 1500
    result: RecommendationResult = recommend(
        all_places=all_places,
        place_type=place_type,
        area_lat=lat,
        area_lng=lng,
        cuisine=cuisine,
        num_results=args.count,
        use_time_filter=not args.no_time_filter,
        area_name=area_name if not args.all_areas else None,
        max_distance_m=max_distance,
        skip_personal_exclusions=args.include_personal,
    )

    # Format output
    output = {
        "query": {
            "area": area_name,
            "type": args.type,
            "cuisine": cuisine,
            "coordinates": {"lat": lat, "lng": lng},
        },
        "results": [format_place(p, i) for i, p in enumerate(result.places)],
        "total_found": len(result.places),
        "crossover_suggestion": result.crossover_suggestion or None,
        "expanded_search": result.expanded_search,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
