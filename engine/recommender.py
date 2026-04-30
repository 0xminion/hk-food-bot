"""
Main recommendation orchestrator.

Combines taste scoring, crossover engine, time-aware filtering,
secret gem detection, and distance calculation into a unified pipeline.
"""

import logging
import random
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from data.loader import Place, filter_by_type, filter_by_cuisine, filter_by_any_tag, load_closed_places, load_personal_exclusions
from engine.taste import score_and_rank_places, ScoredPlace, get_top_cuisines
from engine.crossover import get_crossover_cuisine, get_serendipitous_cuisine, get_similar_cuisines
from engine.time_aware import filter_open_places, get_open_status_label
from engine.lazy_resolve import lazy_resolve_places
from engine.price import price_matches
from utils.constants import HK_AREAS
from utils.name_norm import normalize_name

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
    "North Point": ["North Point", "Tin Hau"],
    "Jordan": ["Jordan", "TST", "Yau Ma Tei"],
    "Yau Ma Tei": ["Yau Ma Tei", "Jordan", "TST", "Mong Kok", "Prince Edward"],
    "Prince Edward": ["Prince Edward", "Mong Kok", "Yau Ma Tei"],
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
_EXCLUSION_LOCK = threading.Lock()


@dataclass
class RecommendationResult:
    """Result of a recommendation query."""
    places: list[Place] = field(default_factory=list)
    crossover_suggestion: str = ""
    expanded_search: bool = False

def _filter_bottom_percentile(places: list[Place], percentile: int = 20) -> list[Place]:
    """Remove places in the bottom N percentile by rating."""
    if not places:
        return places

    # Get best available rating for each place
    ratings = []
    for p in places:
        best = max(p.google_rating or 0, p.or_rating or 0)
        ratings.append(best)

    # Only filter if we have enough rated places
    rated = [r for r in ratings if r > 0]
    if len(rated) < 10:
        return places  # Not enough data to filter

    # Calculate cutoff
    rated_sorted = sorted(rated)
    cutoff_idx = int(len(rated_sorted) * percentile / 100)
    cutoff = rated_sorted[cutoff_idx] if cutoff_idx < len(rated_sorted) else 0

    # Filter: keep places with rating above cutoff OR unrated (give unrated a chance)
    return [p for p in places if max(p.google_rating or 0, p.or_rating or 0) >= cutoff or max(p.google_rating or 0, p.or_rating or 0) == 0]


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


def _load_exclusion_sets() -> tuple[set[str], set[str]]:
    """Load closed and personal exclusion lists (cached, thread-safe)."""
    global _loaded_closed, _loaded_personal
    data_dir = Path(__file__).parent.parent / "data"
    with _EXCLUSION_LOCK:
        if _loaded_closed is None:
            _loaded_closed = load_closed_places(data_dir)
        if _loaded_personal is None:
            _loaded_personal = load_personal_exclusions(data_dir)
    return _loaded_closed, _loaded_personal


def _apply_exclusions(
    places: list[Place],
    exclude_place_names: set[str] | None,
    closed_set: set[str],
    personal_set: set[str],
    skip_personal: bool,
) -> list[Place]:
    """Apply name, closed, and personal exclusions."""
    filtered = places
    if exclude_place_names:
        excluded = {n.lower() for n in exclude_place_names}
        before = len(filtered)
        filtered = [p for p in filtered if p.name.lower() not in excluded]
        logger.info(f"Step 1b - Excluded personal list: {before - len(filtered)} places")

    filtered = [p for p in filtered if not getattr(p, "is_closed", False)]
    if closed_set:
        before = len(filtered)
        filtered = [p for p in filtered if p.name.lower() not in closed_set]
        logger.info(f"Step 1c - Closed filter: {before - len(filtered)} places removed")

    if personal_set and not skip_personal:
        before = len(filtered)
        filtered = [p for p in filtered if p.name.lower() not in personal_set]
        logger.info(f"Step 1d - Personal exclusion: {before - len(filtered)} places removed")

    return filtered


def _filter_by_cuisine_pipeline(
    nearby: list[Place],
    cuisine: str,
    place_type: str,
    num_results: int,
    allow_expansion: bool,
) -> tuple[list[Place], str, bool]:
    """Apply cuisine filter with similar/crossover fallback and optional expansion."""
    crossover = ""
    expanded = False
    matched: list[Place] = []

    if place_type == "bar":
        matched = filter_by_any_tag(nearby, [cuisine])
    else:
        matched = filter_by_cuisine(nearby, [cuisine])
    logger.info(f"Step 6 - Cuisine filter ({cuisine}): {len(matched)} places")

    if not matched:
        similar = get_similar_cuisines(cuisine, top_n=3)
        for sim_cuisine, _ in similar:
            sim_matched = filter_by_any_tag(nearby, [sim_cuisine]) if place_type == "bar" else filter_by_cuisine(nearby, [sim_cuisine])
            if sim_matched:
                matched = sim_matched
                crossover = sim_cuisine
                logger.info(f"  Similar fallback ({sim_cuisine}): {len(matched)} places")
                break

    if not matched:
        all_cuisines = list({tag for p in nearby for tag in p.cuisine_tags})
        cross = get_crossover_cuisine([cuisine], set(all_cuisines))
        if cross:
            matched = filter_by_any_tag(nearby, [cross]) if place_type == "bar" else filter_by_cuisine(nearby, [cross])
            crossover = cross
            logger.info(f"  Crossover fallback ({cross}): {len(matched)} places")

    if not matched:
        expanded = True
        matched = []

    if allow_expansion and len(matched) < num_results and matched:
        matched_names = {p.name for p in matched}
        similar = get_similar_cuisines(cuisine, top_n=5)
        for sim_cuisine, _ in similar:
            if len(matched) >= num_results:
                break
            sim_matches = [p for p in (filter_by_any_tag(nearby, [sim_cuisine]) if place_type == "bar" else filter_by_cuisine(nearby, [sim_cuisine])) if p.name not in matched_names]
            if sim_matches:
                matched.extend(sim_matches[:num_results - len(matched)])
                matched_names.update(p.name for p in sim_matches)
                if not crossover:
                    crossover = sim_cuisine
                expanded = True
                logger.info(f"  Expansion ({sim_cuisine}): +{len(sim_matches)} places")

    return matched, crossover, expanded


def _surprise_mode(nearby: list[Place], num_results: int) -> tuple[list[Place], str]:
    """Pick a serendipitous cuisine and return candidates + suggestion."""
    preferred = [c[0] for c in get_top_cuisines(10)]
    all_cuisines = list({tag for p in nearby for tag in p.cuisine_tags})
    surprise_blacklist = {"bakery", "dessert", "cafe", "brunch"}
    filtered_cuisines = [c for c in all_cuisines if c not in surprise_blacklist]
    surprise_cuisine = get_serendipitous_cuisine(preferred, filtered_cuisines)

    if surprise_cuisine:
        candidates = filter_by_cuisine(nearby, [surprise_cuisine])
        logger.info(f"Step 6 - Surprise ({surprise_cuisine}): {len(candidates)} places")
        if len(candidates) < num_results:
            candidates_names = {p.name for p in candidates}
            diverse_pool = [p for p in nearby if p.name not in candidates_names and not any(t in surprise_blacklist for t in p.cuisine_tags)]
            random.shuffle(diverse_pool)
            candidates.extend(diverse_pool[:num_results - len(candidates)])
        return candidates, surprise_cuisine

    diverse_pool = [p for p in nearby if not any(t in surprise_blacklist for t in p.cuisine_tags)]
    if diverse_pool:
        return diverse_pool, ""
    return nearby, ""


def _deduplicate_franchises(candidates: list[Place], area_lat: float, area_lng: float) -> list[Place]:
    """Deduplicate by normalized name, keeping closest to origin."""
    from utils.haversine import haversine_distance, compute_walk_distance
    seen: dict[str, Place] = {}
    for p in candidates:
        if getattr(p, "distance_walk_m", 0) == 0 and (area_lat != 0 or area_lng != 0) and (p.lat != 0 or p.lng != 0):
            d = haversine_distance(area_lat, area_lng, p.lat, p.lng)
            p.distance_walk_m = compute_walk_distance(d)
        key = normalize_name(p.name)
        if key not in seen:
            seen[key] = p
        else:
            existing = seen[key]
            if (p.distance_walk_m or 99999) < (existing.distance_walk_m or 99999):
                seen[key] = p
    return list(seen.values())


def _apply_semantic_boost(candidates: list[Place], semantic_query: str) -> list[Place]:
    """Re-rank candidates by semantic similarity to query."""
    try:
        from engine.semantic_filter import SemanticFilter
        from pathlib import Path
        sem_cfg = config.get("embedding", {})
        sem = SemanticFilter(
            data_dir=Path(__file__).parent.parent / "data",
            ollama_url=sem_cfg.get("ollama_url", "http://localhost:11434"),
            model=sem_cfg.get("model", "qwen3-embedding:0.6b"),
            dim=sem_cfg.get("dim", 1024),
        )
        candidates = sem.boost_candidates(candidates, semantic_query, boost_weight=0.25)
        logger.info(f"Step 9 - Semantic boost applied: {len(candidates)} re-ranked")
    except FileNotFoundError:
        logger.debug("Embeddings not yet built, skipping semantic boost")
    except Exception:
        logger.warning("Semantic boost failed, continuing without", exc_info=True)
    return candidates


def recommend(
    all_places: list[Place],
    place_type: str,
    area_lat: float,
    area_lng: float,
    cuisine: str | None = None,
    num_results: int = 5,
    use_time_filter: bool = True,
    use_taste_scoring: bool = True,
    use_semantic_boost: bool = False,
    semantic_query: str = "",
    area_name: str | None = None,
    max_distance_m: int = 25000,
    allow_expansion: bool = False,
    exclude_place_names: set[str] | None = None,
    skip_personal_exclusions: bool = False,
    price_filter: str | None = None,
) -> RecommendationResult:
    """
    Main recommendation pipeline."""
    result = RecommendationResult()
    num_results = max(1, min(num_results, 50))

    _loaded_closed, _loaded_personal = _load_exclusion_sets()

    # Step 1: Filter by type
    filtered = filter_by_type(all_places, place_type)
    logger.info(f"Step 1 - Type filter ({place_type}): {len(filtered)} places")

    filtered = _apply_exclusions(filtered, exclude_place_names, _loaded_closed, _loaded_personal, skip_personal_exclusions)

    # Step 2/3: Filter by proximity
    scope_radius = 1500 if area_name and area_name in AREA_SCOPE_NEIGHBORS else max_distance_m
    if place_type == "bar" and scope_radius < 5000:
        scope_radius = 5000
    nearby = _filter_nearby_places(filtered, area_name, area_lat, area_lng, scope_radius)
    logger.info(f"Step 3 - Proximity filter: {len(nearby)} places")

    if not nearby:
        nearby = filtered if area_name is None else []

    # Step 3b: Price range filtering
    if price_filter and price_filter != "any" and nearby:
        before = len(nearby)
        nearby = [p for p in nearby if price_matches(p.price_range, price_filter)]
        logger.info(f"Step 3b - Price filter ({price_filter}): {before - len(nearby)} removed")

    # Step 4: Time-aware filtering
    if use_time_filter and nearby:
        open_now = filter_open_places(nearby)
        logger.info(f"Step 4 - Time filter: {len(open_now)} open places")
        if len(open_now) >= num_results:
            nearby = open_now

    # Step 5/6: Cuisine filtering or surprise mode
    if cuisine and cuisine != "surprise":
        candidates, result.crossover_suggestion, result.expanded_search = _filter_by_cuisine_pipeline(
            nearby, cuisine, place_type, num_results, allow_expansion
        )
    elif cuisine == "surprise":
        candidates, result.crossover_suggestion = _surprise_mode(nearby, num_results)
    else:
        candidates = nearby

    # Step 7: Deduplicate franchises
    if candidates:
        candidates = _deduplicate_franchises(candidates, area_lat, area_lng)
        logger.info(f"Step 7 - Franchise dedup: {len(candidates)} unique names")

    # Step 8: Filter bottom 20% by rating
    if candidates:
        before = len(candidates)
        candidates = _filter_bottom_percentile(candidates, percentile=20)
        logger.info(f"Step 8 - Bottom 20% filter: {before - len(candidates)} removed")

    # Step 9: Semantic boost (if enabled)
    if use_semantic_boost and semantic_query and candidates:
        candidates = _apply_semantic_boost(candidates, semantic_query)

    # Step 10: Score and rank
    if not candidates:
        logger.warning("No candidates found for recommendation")
        return result

    if use_taste_scoring:
        scored = score_and_rank_places(candidates)
        top_scored = scored[:num_results * 3]
        result.places = [s.place for s in top_scored[:num_results]]
    else:
        result.places = random.sample(candidates, min(num_results, len(candidates)))

    if not use_taste_scoring:
        result.places.sort(key=lambda p: p.google_rating, reverse=True)

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
    nearby = _filter_nearby_places(filtered, area_name, area_lat, area_lng, 1500 if area_name else 25000)

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
    nearby = _filter_nearby_places(filtered, area_name, area_lat, area_lng, 1500 if area_name else 25000)

    tags = set()
    for place in nearby:
        for tag in place.cuisine_tags + place.style_tags:
            tag_l = tag.lower().strip()
            if tag_l in BAR_SPOT_TYPES and tag_l not in FOOD_ONLY_TAGS:
                tags.add(tag_l)

    ordered = [tag for tag in BAR_SPOT_TYPES if tag in tags]
    return ordered[:10]
