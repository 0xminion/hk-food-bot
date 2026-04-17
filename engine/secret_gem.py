"""
Secret gem detection module.

Applies curation rules from the PRD to identify hidden gems.
Uses source-aware thresholds since Google and OpenRice have different
rating scales and review count distributions.

Google ratings: average ~4.2, review counts 10-20x higher than OpenRice.
OpenRice ratings: average ~4.0, review counts are HK-local only.

Rules:
- Rule A: high rating + low reviews (hidden quality)
- Rule C: decent rating + very low reviews + hidden-alley style
- Rule E: low review count + good rating (ugly-delicious)

Negative signals (disqualify):
- Part of a chain (≥ 3 locations)
- Located in a major mall
- Very high reviews (already mainstream)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Source-Aware Thresholds ───────────────────────────────────────────────────
# Google ratings skew higher and have 10-20x more reviews than OpenRice.

THRESHOLDS = {
    "google": {
        "rule_a_rating": 4.3,    # Google: ≥4.3 is high quality
        "rule_a_reviews": 1000,  # Google: <1000 is still niche (vs OR's <200)
        "rule_c_rating": 4.0,
        "rule_c_reviews": 500,   # Google: <500 = very low exposure
        "rule_e_reviews": 300,   # Google: <300 = low review count
        "rule_e_rating": 4.2,
        "disqualify_reviews": 5000,  # Google: >5000 = mainstream
    },
    "openrice": {
        "rule_a_rating": 4.3,
        "rule_a_reviews": 200,   # OpenRice: <200 = niche
        "rule_c_rating": 4.0,
        "rule_c_reviews": 100,
        "rule_e_reviews": 50,
        "rule_e_rating": 4.2,
        "disqualify_reviews": 1000,  # OpenRice: >1000 = mainstream
    },
}

# ── Google Ratings Cache ──────────────────────────────────────────────────────

# Deprecated: use data.google_cache.get_google_rating() directly.
# Kept for backward compatibility with get_google_rating() below.


def get_google_rating(name: str, address: str) -> Optional[dict]:
    """Get cached Google rating for a venue."""
    from data.google_cache import get_google_rating as _get
    return _get(name, address)


# ── Major Malls ───────────────────────────────────────────────────────────────

MAJOR_MALL_KEYWORDS = [
    "ifc", "harbour city", "times square", "elements",
    "festival walk", "apm", "megabox", "citygate",
    "pacific place", "hysan place", "the one",
    "langham place", "aqua marina", "k11", "icc",
    "新鴻基中心", "太古廣場", "海港城", "時代廣場",
]


def is_mall_location(address: str) -> bool:
    """Check if the address indicates a major mall location."""
    if not address:
        return False
    address_lower = address.lower()
    return any(mall in address_lower for mall in MAJOR_MALL_KEYWORDS)


def has_style_tag(place, tags: list[str]) -> bool:
    """Check if place has any of the given style tags."""
    place_styles = {s.lower() for s in place.style_tags}
    return any(tag.lower() in place_styles for tag in tags)


# ── Rule Application ──────────────────────────────────────────────────────────

def apply_secret_gem_rules(place) -> bool:
    """
    Apply secret gem curation rules with source-aware thresholds.

    Determines whether to use Google or OpenRice thresholds based on
    available data. Falls back to OpenRice thresholds if no Google data.

    A place is a secret gem if ANY rule is met AND no negative signals apply.
    """
    # Negative signals first — disqualify immediately
    if is_mall_location(place.address):
        return False

    # Try to get Google rating from cache
    google_data = get_google_rating(place.name, place.address)

    if google_data and google_data.get("google_rating"):
        # Use Google data with Google thresholds
        rating = google_data["google_rating"]
        reviews = google_data.get("google_reviews", 0)
        source = "google"
    else:
        # Fall back to OpenRice data
        rating = place.google_rating or place.or_rating or 0
        reviews = place.review_count or 0
        source = "openrice"

    # No rating = can't evaluate
    if not rating or rating <= 0:
        return False

    t = THRESHOLDS[source]

    # Disqualify: mainstream by review count
    if reviews > t["disqualify_reviews"]:
        return False

    # Rule A: high rating + low reviews (hidden quality)
    rule_a = rating >= t["rule_a_rating"] and reviews < t["rule_a_reviews"]

    # Rule C: decent rating + very low reviews + hidden-alley style
    rule_c = (
        rating >= t["rule_c_rating"]
        and reviews < t["rule_c_reviews"]
        and has_style_tag(place, ["hidden-alley", "street-food"])
    )

    # Rule E: low reviews + good rating (ugly-delicious)
    rule_e = reviews <= t["rule_e_reviews"] and rating >= t["rule_e_rating"]

    is_gem = rule_a or rule_c or rule_e

    if is_gem:
        logger.debug(
            f"Secret gem: {place.name} ({source} ⭐{rating}, {reviews} reviews)"
        )

    return is_gem


def enrich_secret_gems(places: list) -> list:
    """
    Apply secret gem rules to all places and update their is_secret_gem flag.
    Returns the modified list.
    """
    gem_count = 0
    for place in places:
        if apply_secret_gem_rules(place):
            place.is_secret_gem = True
            gem_count += 1

    logger.info(
        f"Secret gem enrichment: {gem_count}/{len(places)} gems identified"
    )
    return places
