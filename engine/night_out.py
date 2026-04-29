"""
Hybrid Night Out — multi-venue sequential itinerary planner.

Scores dinner + bar tuples by:
  - Taste scores (weighted 0.6 dinner / 0.4 bar)
  - Proximity (walk distance ≤ 800m)
  - Vibe coherence (static compatibility map)
  - Time compatibility (bar opens before dinner closes + 30min)
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from data.loader import Place
from engine.recommender import recommend, RecommendationResult
from engine.taste import score_and_rank_places, ScoredPlace, get_cuisine_weight
from engine.time_aware import parse_opening_hours

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Static vibe coherence map
# -----------------------------------------------------------------------
DINNER_BAR_VIBES: dict[str, list[str]] = {
    "italian": ["wine-bar", "cocktail-bar", "speakeasy"],
    "japanese": ["izakaya", "cocktail-bar", "speakeasy"],
    "french": ["wine-bar", "cocktail-bar", "lounge"],
    "chinese": ["cocktail-bar", "lounge", "pub"],
    "thai": ["cocktail-bar", "craft-beer", "pub"],
    "cantonese": ["cocktail-bar", "lounge", "pub"],
    "vietnamese": ["cocktail-bar", "craft-beer", "pub"],
    "korean": ["cocktail-bar", "soju-bar", "pub"],
    "spanish": ["wine-bar", "cocktail-bar", "rooftop-bar"],
    "indian": ["cocktail-bar", "lounge"],
    "mexican": ["cocktail-bar", "craft-beer", "pub"],
    "american": ["cocktail-bar", "craft-beer", "pub"],
    "steakhouse": ["wine-bar", "cocktail-bar", "speakeasy"],
    "seafood": ["cocktail-bar", "wine-bar", "rooftop-bar"],
    "hotpot": ["cocktail-bar", "pub", "lounge"],
    "bbq": ["craft-beer", "pub", "cocktail-bar"],
    "ramen": ["izakaya", "craft-beer", "pub"],
    "fusion": ["cocktail-bar", "speakeasy", "lounge"],
    "western": ["wine-bar", "cocktail-bar", "lounge"],
}

FALLBACK_BAR_VIBES = ["cocktail-bar", "wine-bar", "speakeasy", "lounge", "craft-beer"]


# -----------------------------------------------------------------------
# Itinerary data model
# -----------------------------------------------------------------------
@dataclass
class Itinerary:
    dinner: Place
    bar: Place
    walk_m: int
    rationale: str = ""


@dataclass
class NightOutPlan:
    itineraries: list[Itinerary]
    area_name: str
    query_cuisine: str


# -----------------------------------------------------------------------
# Time compatibility
# -----------------------------------------------------------------------
def _extract_closing_time(hours_str: str) -> float | None:
    """Extract the latest closing time as decimal hours (e.g., 22.5 = 22:30)."""
    parsed = parse_opening_hours(hours_str)
    if not parsed:
        return None
    # Find the latest end time across all periods
    max_end = 0.0
    for day, periods in parsed.items():
        for start_h, start_m, end_h, end_m in periods:
            end_dec = end_h + end_m / 60.0
            if end_h == 24 and end_m == 0:
                end_dec = 24.0
            max_end = max(max_end, end_dec)
    return max_end if max_end > 0 else None


def _extract_opening_time(hours_str: str) -> float | None:
    """Extract the earliest opening time as decimal hours."""
    parsed = parse_opening_hours(hours_str)
    if not parsed:
        return None
    min_start = 24.0
    for day, periods in parsed.items():
        for start_h, start_m, end_h, end_m in periods:
            start_dec = start_h + start_m / 60.0
            min_start = min(min_start, start_dec)
    return min_start if min_start < 24 else None


def is_time_compatible(dinner: Place, bar: Place, buffer_hours: float = 0.5) -> bool:
    """Bar should open before or shortly after dinner closes."""
    dinner_close = _extract_closing_time(dinner.opening_hours or "")
    bar_open = _extract_opening_time(bar.opening_hours or "")
    if not dinner_close or not bar_open:
        return True  # Unknown = assume compatible
    return bar_open <= dinner_close + buffer_hours


# -----------------------------------------------------------------------
# Vibe coherence
# -----------------------------------------------------------------------
def _vibe_coherence(dinner: Place) -> list[str]:
    """Return compatible bar tags for a given dinner venue."""
    # Match on cuisine tags
    for tag in dinner.cuisine_tags:
        if tag.lower() in DINNER_BAR_VIBES:
            return DINNER_BAR_VIBES[tag.lower()]
    # Match on style tags
    for tag in dinner.style_tags:
        if tag.lower() in DINNER_BAR_VIBES:
            return DINNER_BAR_VIBES[tag.lower()]
    return FALLBACK_BAR_VIBES


def _coherence_score(dinner: Place, bar: Place) -> float:
    """0-1 score for how well the bar matches the dinner's vibe."""
    compatible = _vibe_coherence(dinner)
    # Check if bar has any matching compatible tag
    bar_tags = {t.lower() for t in bar.cuisine_tags + bar.style_tags}
    if any(c in bar_tags for c in compatible):
        return 1.0
    # Partial: any cocktail or bar tag at all
    if any(t in {"cocktail-bar", "bar", "wine-bar", "speakeasy", "lounge"} for t in bar_tags):
        return 0.3
    return 0.0


# -----------------------------------------------------------------------
# Proximity
# -----------------------------------------------------------------------
def _compute_walk_distance_m(dinner: Place, bar: Place) -> int:
    """Compute straight-line distance between two places."""
    from utils.haversine import haversine_distance
    if dinner.lat == 0 or dinner.lng == 0 or bar.lat == 0 or bar.lng == 0:
        return 99999
    d = haversine_distance(dinner.lat, dinner.lng, bar.lat, bar.lng)
    return int(d)


# -----------------------------------------------------------------------
# Scoring
# -----------------------------------------------------------------------
def _score_itinerary(dinner: Place, bar: Place, max_walk_m: int = 800) -> float:
    """
    Score a dinner+bar pair. Higher is better.
    """
    taste_w = get_cuisine_weight

    # Taste component
    dinner_taste = dinner.taste_score if hasattr(dinner, "taste_score") else 0.2
    bar_taste = bar.taste_score if hasattr(bar, "taste_score") else 0.2
    taste_score = dinner_taste * 0.6 + bar_taste * 0.4

    # Proximity component: 1.0 at 0m, 0.0 at max_walk_m
    walk = _compute_walk_distance_m(dinner, bar)
    if walk > max_walk_m:
        return -1.0  # Disqualify
    proximity_score = max(0.0, 1.0 - walk / max_walk_m)

    # Vibe coherence
    vibe_score = _coherence_score(dinner, bar)

    # Time compatibility
    time_score = 1.0 if is_time_compatible(dinner, bar) else 0.3

    # Combine
    total = (
        taste_score * 0.4 +
        proximity_score * 0.3 +
        vibe_score * 0.2 +
        time_score * 0.1
    )
    return total


# -----------------------------------------------------------------------
# Main planner
# -----------------------------------------------------------------------
def plan_night_out(
    all_places: list[Place],
    area_lat: float,
    area_lng: float,
    cuisine: str | None = None,
    area_name: str | None = None,
    budget: str | None = None,
    num_itineraries: int = 3,
    max_walk_m: int = 800,
    dinner_cuisine: str | None = None,
) -> NightOutPlan:
    """
    Plan a multi-venue night out: dinner + bar.

    Args:
        all_places: full dataset
        area_lat/lng: user's area coordinates
        cuisine: dinner cuisine tag
        area_name: human-readable area label
        budget: price filter
        num_itineraries: number of plans to return
        max_walk_m: max dinner-to-bar walk distance
    """
    # Step 1: Get dinner candidates
    dinner_cuisine_actual: str | None = dinner_cuisine if dinner_cuisine is not None else cuisine
    dinner_result: RecommendationResult = recommend(
        all_places=all_places,
        place_type="restaurant",
        area_lat=area_lat,
        area_lng=area_lng,
        cuisine=dinner_cuisine_actual,
        num_results=20,
        area_name=area_name,
        max_distance_m=1500,
        price_filter=budget,
        use_semantic_boost=bool(dinner_cuisine_actual),
        semantic_query=dinner_cuisine_actual or "",
    )
    dinners = dinner_result.places
    if not dinners:
        return NightOutPlan(itineraries=[], area_name=area_name or "", query_cuisine=cuisine or "")

    # Step 2: Find bars near each dinner candidate
    all_scores: list[tuple[float, Place, Place]] = []  # (score, dinner, bar)

    for dinner in dinners:
        # Find bars within max_walk_m of this dinner
        # Use dinner's location as the center for bar search
        bar_result: RecommendationResult = recommend(
            all_places=all_places,
            place_type="bar",
            area_lat=dinner.lat,
            area_lng=dinner.lng,
            cuisine=None,  # Any bar type
            num_results=15,
            area_name=None,
            max_distance_m=max_walk_m,
            use_taste_scoring=True,
        )
        bars = bar_result.places

        for bar in bars:
            if _compute_walk_distance_m(dinner, bar) > max_walk_m:
                continue
            score = _score_itinerary(dinner, bar, max_walk_m)
            if score < 0:
                continue
            all_scores.append((score, dinner, bar))

    # Step 3: Deduplicate by (dinner_name, bar_name) and take top N
    seen_pairs: set[str] = set()
    unique_scores: list[tuple[float, Place, Place]] = []
    for score, d, b in sorted(all_scores, key=lambda x: x[0], reverse=True):
        key = f"{d.name}|{b.name}"
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        unique_scores.append((score, d, b))

    # Step 4: Build itineraries
    itineraries = []
    for score, d, b in unique_scores[:num_itineraries]:
        walk = _compute_walk_distance_m(d, b)
        compatible = _vibe_coherence(d)
        match_tag = next((t for t in (b.cuisine_tags + b.style_tags) if t.lower() in compatible), "")
        rationale = (
            f"Dinner at <b>{d.name}</b> then <b>{b.name}</b> — "
            f"<i>{walk}m walk</i>. "
            f"{'Perfect ' + match_tag + ' match' if match_tag else 'Great spot nearby'}."
        )
        itineraries.append(Itinerary(
            dinner=d,
            bar=b,
            walk_m=walk,
            rationale=rationale,
        ))

    plan = NightOutPlan(
        itineraries=itineraries,
        area_name=area_name or "",
        query_cuisine=cuisine or "",
    )
    logger.info(f"Night Out: {len(plan.itineraries)} itineraries found ({len(dinners)} dinners → {len(bars)} bars)")
    return plan
