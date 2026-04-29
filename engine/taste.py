"""
Taste profile scorer.

Scores places based on how well they match the user's taste profile.
Weights are loaded from config.yaml so they can be customized without editing code.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load taste profile from config.yaml (so users can customize without editing code)
# ---------------------------------------------------------------------------

def _load_taste_profile() -> tuple[dict[str, float], float]:
    """Load taste profile weights from config.yaml.

    Returns (profile dict, default weight). Falls back to an empty profile
    if config.yaml is missing or the taste_profile section is absent.
    """
    config_path = Path(__file__).parent.parent / "config.yaml"
    if not config_path.exists():
        logger.warning("config.yaml not found; using empty taste profile")
        return {}, 0.2

    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Failed to parse config.yaml: %s; using empty taste profile", exc)
        return {}, 0.2

    taste_cfg = cfg.get("taste_profile", {})
    if not isinstance(taste_cfg, dict):
        return {}, 0.2
    # Copy so we don't mutate the original config dict
    taste_cfg = dict(taste_cfg)
    default_weight = float(taste_cfg.pop("default_weight", 0.2))

    # Filter out only numeric weights (ignore comments or nested structures)
    profile: dict[str, float] = {}
    for key, value in taste_cfg.items():
        if isinstance(value, (int, float)):
            profile[key.lower().strip()] = float(value)

    return profile, default_weight


# Module-level cache: loaded once at import time
_USER_TASTE_PROFILE, _DEFAULT_CUISINE_WEIGHT = _load_taste_profile()


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
    return _USER_TASTE_PROFILE.get(tag, _DEFAULT_CUISINE_WEIGHT)


def score_place(place) -> float:
    """
    Score a place based on how well its cuisine tags match the user's taste profile.

    Takes the max weight across all cuisine tags (a Thai-Italian fusion place
    gets the max of Thai=0.75 and Italian=1.0 → 1.0). Falls back to the
    configured default weight for unknown cuisines.
    """
    if not place.cuisine_tags:
        return _DEFAULT_CUISINE_WEIGHT

    weights = [get_cuisine_weight(tag) for tag in place.cuisine_tags]
    # Use max — if any tag matches a favorite cuisine, the place scores high
    best = max(weights)

    # Small bonus for multiple matching tags (breadth of match)
    matching = sum(1 for w in weights if w >= 0.5)
    if matching > 1:
        best = min(1.0, best + 0.05 * (matching - 1))

    # Style tag bonus — certain styles signal quality/experience the user likes
    preferred_styles = {"speakeasy", "rooftop-bar", "fine-dining", "hidden-alley", "izakaya", "lounge"}
    if place.style_tags:
        style_matches = sum(1 for s in place.style_tags if s in preferred_styles)
        if style_matches > 0:
            best = min(1.0, best + 0.05 * style_matches)

    return best


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
        place.taste_score = taste  # Persist for downstream consumers
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
    sorted_cuisines = sorted(_USER_TASTE_PROFILE.items(), key=lambda x: x[1], reverse=True)
    return sorted_cuisines[:limit]
