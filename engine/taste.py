"""
Taste profile scorer.

Scores places based on how well they match the user's known preferences
derived from their Google Maps saved list analysis.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# User's taste profile from Google Maps "minion abc" list analysis
USER_TASTE_PROFILE: dict[str, float] = {
    "italian": 1.0,
    "chinese": 1.0,
    "cantonese": 0.85,
    "cocktail-bar": 0.95,
    "japanese": 0.8,
    "thai": 0.75,
    "spanish": 0.7,
    "western": 0.65,
    "ramen": 0.65,
    "hotpot": 0.55,
    # Crossover weights — cuisines similar to favorites
    "french": 0.6,
    "bakery": 0.45,
    "dessert": 0.4,
    "vietnamese": 0.55,
    "korean": 0.5,
    "fusion": 0.5,
    "seafood": 0.45,
    "steakhouse": 0.45,
    "noodles": 0.5,
    "dim-sum": 0.5,
    "bbq": 0.4,
    "wine-bar": 0.6,
    "craft-beer": 0.4,
    "speakeasy": 0.7,
    "lounge": 0.5,
    "pub": 0.3,
    "dive-bar": 0.35,
    "rooftop-bar": 0.55,
    "cafe": 0.3,
    "greek": 0.4,
    "indian": 0.4,
    "mexican": 0.35,
    "turkish": 0.35,
    "middle-eastern": 0.35,
    "portuguese": 0.4,
    "sichuan": 0.55,
    "malay": 0.4,
    "indonesian": 0.35,
    "filipino": 0.3,
}

# Default weight for unknown cuisines
DEFAULT_CUISINE_WEIGHT = 0.2


@dataclass
class ScoredPlace:
    """A place with its taste score attached."""
    place: object  # Will be Place type
    taste_score: float
    bonus_gem: float = 0.0
    bonus_award: float = 0.0
    bonus_rating: float = 0.0

    @property
    def total_score(self) -> float:
        return self.taste_score + self.bonus_gem + self.bonus_award + self.bonus_rating


def get_cuisine_weight(cuisine_tag: str) -> float:
    """Get the taste weight for a specific cuisine tag."""
    tag = cuisine_tag.lower().strip()
    return USER_TASTE_PROFILE.get(tag, DEFAULT_CUISINE_WEIGHT)


def score_place(place) -> float:
    """
    Score a place based on the user's taste profile.
    Returns a score between 0.0 and 1.0+.
    """
    if not place.cuisine_tags:
        return DEFAULT_CUISINE_WEIGHT

    # Take the best matching cuisine weight
    weights = [get_cuisine_weight(tag) for tag in place.cuisine_tags]
    max_weight = max(weights)

    # Small bonus for multiple matching cuisines
    avg_weight = sum(weights) / len(weights)
    return max_weight * 0.7 + avg_weight * 0.3


def score_and_rank_places(places: list, data_dir=None) -> list[ScoredPlace]:
    """
    Score all places and return them sorted by total score descending.
    Includes taste, secret gem, award, and rating bonuses.
    """
    from pathlib import Path
    from engine.awards import get_award_boost

    if data_dir is None:
        data_dir = Path(__file__).parent.parent / "data"

    scored = []
    for place in places:
        taste = score_place(place)
        gem_bonus = 0.15 if place.is_secret_gem else 0.0

        # Award bonus: 0-1.0 normalized range
        award_raw, award_badges = get_award_boost(place.name, data_dir)
        award_bonus = min(1.0, award_raw / 100.0)  # Normalize to 0-1

        # Rating bonus: boost places with high ratings
        rating_bonus = 0.0
        best_rating = max(place.google_rating or 0, place.or_rating or 0)
        if best_rating >= 4.5:
            rating_bonus = 0.20
        elif best_rating >= 4.0:
            rating_bonus = 0.10
        elif best_rating >= 3.5:
            rating_bonus = 0.05

        scored.append(ScoredPlace(
            place=place,
            taste_score=taste,
            bonus_gem=gem_bonus,
            bonus_award=award_bonus,
            bonus_rating=rating_bonus,
        ))

    scored.sort(key=lambda s: s.total_score, reverse=True)
    return scored


def get_top_cuisines(limit: int = 10) -> list[tuple[str, float]]:
    """Return the top N cuisines from the user's taste profile, sorted by weight."""
    sorted_cuisines = sorted(USER_TASTE_PROFILE.items(), key=lambda x: x[1], reverse=True)
    return sorted_cuisines[:limit]
