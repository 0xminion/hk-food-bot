"""
Main recommendation orchestrator.

Combines taste scoring, crossover engine, time-aware filtering,
secret gem detection, and distance calculation into a unified pipeline.
"""

import logging
import random
from dataclasses import dataclass, field

from data.loader import Place, filter_by_type, filter_by_cuisine, compute_distances
from engine.taste import score_and_rank_places, ScoredPlace, get_top_cuisines
from engine.crossover import get_crossover_cuisine, get_serendipitous_cuisine
from engine.time_aware import filter_open_places, get_open_status_label
from engine.secret_gem import enrich_secret_gems
from engine.lazy_resolve import lazy_resolve_places

logger = logging.getLogger(__name__)


@dataclass
class RecommendationResult:
    """Result of a recommendation query."""
    places: list[Place] = field(default_factory=list)
    crossover_suggestion: str = ""
    expanded_search: bool = False


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

    # Step 1: Filter by type
    filtered = filter_by_type(all_places, place_type)
    logger.info(f"Step 1 - Type filter ({place_type}): {len(filtered)} places")

    # Step 2: Compute distances
    compute_distances(filtered, area_lat, area_lng)

    # Step 3: Filter by proximity (~25km walk distance covers ~19km straight line)
    nearby = [p for p in filtered if p.distance_walk_m <= 25000]
    logger.info(f"Step 3 - Proximity filter: {len(nearby)} places")

    if not nearby:
        nearby = filtered  # Fallback: use all

    # Step 4: Time-aware filtering
    if use_time_filter:
        open_now = filter_open_places(nearby)
        logger.info(f"Step 4 - Time filter: {len(open_now)} open places")
        if len(open_now) >= num_results:
            nearby = open_now

    # Step 5: Enrich secret gem flags
    enrich_secret_gems(nearby)

    # Step 6: Apply cuisine filter or crossover
    if cuisine and cuisine != "surprise":
        matched = filter_by_cuisine(nearby, [cuisine])
        logger.info(f"Step 6 - Cuisine filter ({cuisine}): {len(matched)} places")

        if len(matched) < num_results:
            # Fallback: crossover suggestion
            all_cuisines = list({tag for p in nearby for tag in p.cuisine_tags})
            crossover = get_crossover_cuisine([cuisine], set(all_cuisines))
            if crossover:
                matched_names = {p.name for p in matched}
                crossover_matches = [p for p in filter_by_cuisine(nearby, [crossover]) if p.name not in matched_names]
                matched.extend(crossover_matches)
                matched_names.update(p.name for p in crossover_matches)
                result.crossover_suggestion = crossover
                result.expanded_search = True
                logger.info(f"  Crossover ({crossover}): +{len(crossover_matches)} places")

            if len(matched) < num_results:
                # Further fallback: add all nearby (avoid duplicates)
                matched_names = {p.name for p in matched}
                unique_nearby = [p for p in nearby if p.name not in matched_names]
                matched.extend(unique_nearby)
                result.expanded_search = True

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

    # Step 7: Score and rank
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
) -> list[str]:
    """
    Get available cuisine tags for a given type and area.
    Used to populate the cuisine selection keyboard.
    """
    filtered = filter_by_type(all_places, place_type)
    compute_distances(filtered, area_lat, area_lng)
    nearby = [p for p in filtered if p.distance_walk_m <= 25000]

    cuisines = set()
    for place in nearby:
        cuisines.update(place.cuisine_tags)

    return sorted(cuisines)
