"""
Main recommendation orchestrator.

Combines taste scoring, crossover engine, time-aware filtering,
secret gem detection, and distance calculation into a unified pipeline.
"""

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

from data.loader import Place, filter_by_type, filter_by_cuisine, filter_by_any_tag, load_closed_places, load_personal_exclusions
from engine.taste import score_and_rank_places, ScoredPlace, get_top_cuisines
from engine.crossover import get_crossover_cuisine, get_serendipitous_cuisine, get_similar_cuisines
from engine.time_aware import filter_open_places, get_open_status_label
from engine.lazy_resolve import lazy_resolve_places
from handlers.common import HK_AREAS

logger = logging.getLogger(__name__)


# Area scopes: selected area + up to 2 connected suburbs within 2km of each suburb's MTR station.
# Hidden station coords are included for a couple of neighborhoods that aren't in the main UI.
EXTRA_AREA_COORDS = {
    "Jordan": (22.3064, 114.1717),
    "Yau Ma Tei": (22.3069, 114.1709),
    "North Point": (22.2910, 114.1970),
    "Prince Edward": (22.3247, 114.1686),
}

AREA_SCOPE_NEIGHBORS = {
    "Central": ["Central", "Sheung Wan", "Admiralty"],
    "Wan Chai": ["Wan Chai", "Causeway Bay", "Admiralty"],
    "Causeway Bay": ["Causeway Bay", "Wan Chai", "Tin Hau"],
    "Sheung Wan": ["Sheung Wan", "Central", "Sai Ying Pun"],
    "Sai Ying Pun": ["Sai Ying Pun", "Sheung Wan", "Kennedy Town"],
    "Admiralty": ["Admiralty", "Central", "Wan Chai"],
    "Tin Hau": ["Tin Hau", "Causeway Bay", "North Point"],
    "Kennedy Town": ["Kennedy Town", "Sai Ying Pun"],
    "TST": ["TST", "Jordan", "Yau Ma Tei"],
    "Mong Kok": ["Mong Kok", "Yau Ma Tei", "Prince Edward"],
}

BAR_SPOT_TYPES = [
    "cocktail-bar",
    "wine-bar",
    "speakeasy",
    "rooftop-bar",
    "craft-beer",
    "pub",
    "lounge",
    "dive-bar",
    "bar",
    "izakaya",
]

# Tags that should NEVER appear as drink spot options (food-only)
FOOD_ONLY_TAGS = {"cafe", "restaurant", "bakery", "dessert", "brunch"}

# Cache for loaded exclusion lists (loaded once per process)
_loaded_closed: set[str] | None = None
_loaded_personal: set[str] | None = None


@dataclass
class RecommendationResult:
    """Result of a recommendation query."""
    places: list[Place] = field(default_factory=list)
    crossover_suggestion: str = ""
    expanded_search: bool = False


def _resolve_area_coord(area_name: str) -> tuple[float, float] | None:
    if area_name in HK_AREAS:
        return HK_AREAS[area_name]
    return EXTRA_AREA_COORDS.get(area_name)


def _area_search_origins(area_name: str) -> list[tuple[str, float, float]]:
    names = AREA_SCOPE_NEIGHBORS.get(area_name)
    if not names:
        return []
    origins = []
    for name in names:
        coord = _resolve_area_coord(name)
        if coord:
            origins.append((name, coord[0], coord[1]))
    return origins


def _filter_by_origins(places: list[Place], origins: list[tuple[str, float, float]], max_distance_m: int) -> list[Place]:
    from utils.haversine import haversine_distance, compute_walk_distance, compute_drive_distance

    nearby: list[Place] = []
    for p in places:
        if (p.lat == 0.0 and p.lng == 0.0) or getattr(p, 'lat', None) is None or getattr(p, 'lng', None) is None:
            continue
        best_walk = None
        best_drive = None
        for _, lat, lng in origins:
            straight_line = haversine_distance(lat, lng, p.lat, p.lng)
            walk = compute_walk_distance(straight_line)
            if walk <= max_distance_m and (best_walk is None or walk < best_walk):
                best_walk = walk
                best_drive = compute_drive_distance(straight_line)
        if best_walk is not None:
            p.distance_walk_m = best_walk
            p.distance_drive_m = best_drive or 0
            nearby.append(p)
    return nearby


def _filter_nearby_places(
    places: list[Place],
    area_name: str | None,
    area_lat: float,
    area_lng: float,
    max_distance_m: int,
) -> list[Place]:
    if area_name:
        origins = _area_search_origins(area_name)
        if origins:
            return _filter_by_origins(places, origins, max_distance_m)
    return _filter_by_origins(places, [("origin", area_lat, area_lng)], max_distance_m)


def get_area_coordinates(area_name: str, areas: dict) -> tuple[float, float]:
    """Get coordinates for a named area."""
    return areas.get(area_name, (22.2783, 114.1747))


def recommend(
    all_places: list[Place],
    place_type: str,
    area_lat: float,
    area_lng: float,
    cuisine: str | None = None,
    num_results: int = 5,
    use_time_filter: bool = True,
    use_taste_scoring: bool = True,
    area_name: str | None = None,
    max_distance_m: int = 25000,
    allow_expansion: bool = False,
    exclude_place_names: set[str] | None = None,
) -> RecommendationResult:
    """
    Main recommendation pipeline.

    Args:
        all_places: Full dataset of places
        place_type: 'restaurant' or 'bar'
        area_lat: User's area latitude
        area_lng: User's area longitude
        cuisine: Selected cuisine tag (None for surprise me)
        num_results: Number of recommendations to return
        use_time_filter: Whether to filter by opening hours
        use_taste_scoring: Whether to apply taste profile scoring

    Returns:
        RecommendationResult with places and metadata
    """
    result = RecommendationResult()
    num_results = max(1, min(num_results, 50))  # Clamp between 1 and 50

    # Load exclusion lists (cached)
    global _loaded_closed, _loaded_personal
    data_dir = Path(__file__).parent.parent / "data"
    if _loaded_closed is None:
        _loaded_closed = load_closed_places(data_dir)
    if _loaded_personal is None:
        _loaded_personal = load_personal_exclusions(data_dir)

    # Step 1: Filter by type
    filtered = filter_by_type(all_places, place_type)
    logger.info(f"Step 1 - Type filter ({place_type}): {len(filtered)} places")

    if exclude_place_names:
        excluded = {n.lower() for n in exclude_place_names}
        before = len(filtered)
        filtered = [p for p in filtered if p.name.lower() not in excluded]
        logger.info(f"Step 1b - Excluded personal list: {before - len(filtered)} places")

    # Exclude closed places (from is_closed field + closed_places.txt)
    filtered = [p for p in filtered if not getattr(p, "is_closed", False)]
    if _loaded_closed:
        before = len(filtered)
        filtered = [p for p in filtered if p.name.lower() not in _loaded_closed]
        logger.info(f"Step 1c - Closed filter: {before - len(filtered)} places removed")

    # Exclude personal "minion abc" list
    if _loaded_personal:
        before = len(filtered)
        filtered = [p for p in filtered if p.name.lower() not in _loaded_personal]
        logger.info(f"Step 1d - Personal exclusion: {before - len(filtered)} places removed")

    # Step 2/3: Filter by proximity
    scope_radius = 2000 if area_name and area_name in AREA_SCOPE_NEIGHBORS else max_distance_m
    nearby = _filter_nearby_places(filtered, area_name, area_lat, area_lng, scope_radius)
    logger.info(f"Step 3 - Proximity filter: {len(nearby)} places")

    if not nearby:
        nearby = filtered if area_name is None else []

    # Step 4: Time-aware filtering
    if use_time_filter and nearby:
        open_now = filter_open_places(nearby)
        logger.info(f"Step 4 - Time filter: {len(open_now)} open places")
        if len(open_now) >= num_results:
            nearby = open_now

    # Step 5: Secret gem flags + cuisine filtering
    if cuisine and cuisine != "surprise":
        if place_type == "bar":
            matched = filter_by_any_tag(nearby, [cuisine])
        else:
            matched = filter_by_cuisine(nearby, [cuisine])
        logger.info(f"Step 6 - Cuisine filter ({cuisine}): {len(matched)} places")

        if not matched:
            # Smart fallback: try SIMILAR cuisines first (same family)
            similar = get_similar_cuisines(cuisine, top_n=3)
            for sim_cuisine, _ in similar:
                sim_matched = filter_by_cuisine(nearby, [sim_cuisine])
                if sim_matched:
                    matched = sim_matched
                    result.crossover_suggestion = sim_cuisine
                    logger.info(f"  Similar fallback ({sim_cuisine}): {len(matched)} places")
                    break

        if not matched:
            # Second fallback: crossover suggestion
            all_cuisines = list({tag for p in nearby for tag in p.cuisine_tags})
            crossover = get_crossover_cuisine([cuisine], set(all_cuisines))
            if crossover:
                matched = filter_by_cuisine(nearby, [crossover])
                result.crossover_suggestion = crossover
                logger.info(f"  Crossover fallback ({crossover}): {len(matched)} places")

        if not matched:
            # Last resort: show empty, don't pollute with unrelated results
            result.expanded_search = True
            matched = []

        if allow_expansion and len(matched) < num_results and matched:
            # Expansion: add similar cuisines to fill the list
            matched_names = {p.name for p in matched}
            similar = get_similar_cuisines(cuisine, top_n=5)
            for sim_cuisine, _ in similar:
                if len(matched) >= num_results:
                    break
                sim_matches = [p for p in filter_by_cuisine(nearby, [sim_cuisine]) if p.name not in matched_names]
                if sim_matches:
                    matched.extend(sim_matches[:num_results - len(matched)])
                    matched_names.update(p.name for p in sim_matches)
                    if not result.crossover_suggestion:
                        result.crossover_suggestion = sim_cuisine
                    result.expanded_search = True
                    logger.info(f"  Expansion ({sim_cuisine}): +{len(sim_matches)} places")

        candidates = matched
    elif cuisine == "surprise":
        # Serendipitous mode
        preferred = [c[0] for c in get_top_cuisines(10)]
        all_cuisines = list({tag for p in nearby for tag in p.cuisine_tags})
        surprise_cuisine = get_serendipitous_cuisine(preferred, all_cuisines)

        if surprise_cuisine:
            candidates = filter_by_cuisine(nearby, [surprise_cuisine])
            result.crossover_suggestion = surprise_cuisine
            logger.info(f"Step 6 - Surprise ({surprise_cuisine}): {len(candidates)} places")
            if len(candidates) < num_results:
                candidates = nearby
        else:
            candidates = nearby
    else:
        candidates = nearby

    # Step 7: Deduplicate franchises (same name) — keep closest to user
    if candidates:
        seen: dict[str, Place] = {}
        for p in candidates:
            key = p.name.lower()
            if key not in seen:
                seen[key] = p
            else:
                # Keep the one closer to the user
                existing = seen[key]
                if (p.distance_walk_m or 99999) < (existing.distance_walk_m or 99999):
                    seen[key] = p
        candidates = list(seen.values())
        logger.info(f"Step 6.5 - Franchise dedup: {len(candidates)} unique names")

    # Step 8: Score and rank
    if not candidates:
        logger.warning("No candidates found for recommendation")
        return result

    if use_taste_scoring:
        scored = score_and_rank_places(candidates)
        # Take top candidates, with some randomization among similarly-scored
        top_scored = scored[:num_results * 3]
        result.places = [s.place for s in top_scored[:num_results]]
    else:
        # Random selection
        result.places = random.sample(candidates, min(num_results, len(candidates)))

    # Sort by rating for display
    result.places.sort(key=lambda p: p.google_rating, reverse=True)

    # Step 9: Lazy-resolve Google ratings for surfaced venues (background)
    try:
        lazy_resolve_places(result.places)
    except Exception as e:
        logger.debug(f"Lazy resolve trigger failed (non-blocking): {e}")

    logger.info(f"Final recommendations: {len(result.places)} places")
    return result


def get_available_cuisines(
    all_places: list[Place],
    place_type: str,
    area_lat: float,
    area_lng: float,
    area_name: str | None = None,
) -> list[str]:
    """
    Get available cuisine tags for a given type and area.
    Used to populate the cuisine selection keyboard.
    """
    filtered = filter_by_type(all_places, place_type)
    nearby = _filter_nearby_places(filtered, area_name, area_lat, area_lng, 2000 if area_name else 25000)

    cuisines = set()
    for place in nearby:
        cuisines.update(place.cuisine_tags)

    return sorted(cuisines)


def get_available_spot_types(
    all_places: list[Place],
    area_lat: float,
    area_lng: float,
    area_name: str | None = None,
) -> list[str]:
    """Return curated drink spot types based on bar-only tags and nearby bar data."""
    filtered = filter_by_type(all_places, "bar")
    nearby = _filter_nearby_places(filtered, area_name, area_lat, area_lng, 2000 if area_name else 25000)

    tags = set()
    for place in nearby:
        for tag in place.cuisine_tags + place.style_tags:
            tag_l = tag.lower().strip()
            if tag_l in BAR_SPOT_TYPES and tag_l not in FOOD_ONLY_TAGS:
                tags.add(tag_l)

    ordered = [tag for tag in BAR_SPOT_TYPES if tag in tags]
    return ordered[:10]
