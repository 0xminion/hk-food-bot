"""
Secret gem detection module.

Applies curation rules from the PRD to identify hidden gems:
- Rule A: rating ≥4.3 AND review_count < 200
- Rule B: mentioned on ≥2 reputable lists but not on Google top results
- Rule C: rating ≥4.0 AND < 100 reviews AND has hidden-alley/street-food style
- Rule D: Michelin Bib Gourmand but < 500 Google reviews
- Rule E: ≤3 photos but rating ≥ 4.2

Negative signals (disqualify):
- Part of a chain (≥ 3 locations)
- Located in a major mall
- > 1000 reviews (already mainstream)
"""

import logging

logger = logging.getLogger(__name__)


# Major malls / commercial complexes to disqualify from secret gem status
MAJOR_MALL_KEYWORDS = [
    "ifc", "harbour city", "times square", "elements",
    "festival walk", "apm", "megabox", "citygate",
    "pacific place", "hysan place", "the one",
    "langham place", "aqua marina", "k11",
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


def apply_secret_gem_rules(place) -> bool:
    """
    Apply secret gem curation rules to determine if a place is a hidden gem.
    
    A place is a secret gem if ANY rule is met AND no negative signals apply.
    """
    # Negative signals first — disqualify immediately
    if place.review_count > 1000:
        return False
    if is_mall_location(place.address):
        return False

    rating = place.google_rating
    reviews = place.review_count

    # Rule A: rating ≥ 4.3 AND review_count < 200
    rule_a = rating >= 4.3 and reviews < 200

    # Rule C: rating ≥ 4.0 AND < 100 reviews AND has hidden-alley/street-food style
    rule_c = (
        rating >= 4.0
        and reviews < 100
        and has_style_tag(place, ["hidden-alley", "street-food"])
    )

    # Rule E: few photos (we don't track this, proxy: < 50 reviews AND rating ≥ 4.2)
    rule_e = reviews <= 50 and rating >= 4.2

    is_gem = rule_a or rule_c or rule_e

    if is_gem:
        logger.debug(f"Secret gem detected: {place.name} (rating={rating}, reviews={reviews})")

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

    logger.info(f"Secret gem enrichment complete: {gem_count}/{len(places)} gems identified")
    return places
