"""
Crossover recommendation engine.

Suggests related cuisines based on flavor-profile similarity.
If a user likes Thai, suggest Vietnamese. If they like Italian, suggest Spanish.
"""

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)

# Flavor profile similarity mapping
# Key: cuisine, Value: list of (similar_cuisine, similarity_score)
CUISINE_SIMILARITY: dict[str, list[tuple[str, float]]] = {
    "thai": [("vietnamese", 0.8), ("malay", 0.6), ("lao", 0.7), ("indonesian", 0.5)],
    "vietnamese": [("thai", 0.8), ("chinese", 0.4), ("malay", 0.5)],
    "italian": [("spanish", 0.6), ("french", 0.5), ("greek", 0.4), ("portuguese", 0.5)],
    "spanish": [("italian", 0.6), ("portuguese", 0.7), ("mexican", 0.4)],
    "japanese": [("korean", 0.5), ("chinese", 0.3), ("fusion", 0.4)],
    "korean": [("japanese", 0.5), ("chinese", 0.4), ("bbq", 0.6)],
    "chinese": [("cantonese", 0.7), ("sichuan", 0.6), ("dim-sum", 0.5), ("vietnamese", 0.4), ("korean", 0.3)],
    "cantonese": [("chinese", 0.7), ("dim-sum", 0.7), ("seafood", 0.5)],
    "french": [("italian", 0.5), ("spanish", 0.4), ("wine-bar", 0.6), ("western", 0.3)],
    "bakery": [("dessert", 0.7), ("cafe", 0.5)],
    "dessert": [("bakery", 0.7), ("cafe", 0.4)],
    "indian": [("thai", 0.3), ("malay", 0.4), ("middle-eastern", 0.3)],
    "mexican": [("spanish", 0.4), ("western", 0.3)],
    "hotpot": [("sichuan", 0.5), ("chinese", 0.5), ("bbq", 0.4)],
    "ramen": [("japanese", 0.7), ("noodles", 0.6), ("korean", 0.3)],
    "noodles": [("ramen", 0.6), ("chinese", 0.5), ("thai", 0.4), ("vietnamese", 0.4), ("japanese", 0.3)],
    "izakaya": [("japanese", 0.8), ("korean", 0.3)],
    "seafood": [("cantonese", 0.5), ("japanese", 0.4), ("french", 0.3)],
    "cocktail-bar": [("speakeasy", 0.8), ("wine-bar", 0.6), ("lounge", 0.7), ("rooftop-bar", 0.5)],
    "speakeasy": [("cocktail-bar", 0.8), ("wine-bar", 0.5)],
    "wine-bar": [("cocktail-bar", 0.6), ("french", 0.4), ("italian", 0.4), ("lounge", 0.5)],
    "craft-beer": [("pub", 0.6), ("dive-bar", 0.5), ("western", 0.3)],
    "bbq": [("korean", 0.6), ("steakhouse", 0.5), ("hotpot", 0.4)],
    "steakhouse": [("bbq", 0.5), ("western", 0.5), ("french", 0.3)],
    "dim-sum": [("cantonese", 0.7), ("chinese", 0.6)],
    "western": [("italian", 0.4), ("french", 0.4), ("spanish", 0.3), ("steakhouse", 0.5)],
    "fusion": [("japanese", 0.4), ("thai", 0.3), ("western", 0.3)],
    "cafe": [("western", 0.3), ("fusion", 0.3)],
}


def get_similar_cuisines(cuisine: str, top_n: int = 3) -> list[tuple[str, float]]:
    """
    Get the most similar cuisines to the given one.
    Returns list of (cuisine, similarity_score) tuples.
    """
    cuisine_lower = cuisine.lower().strip()
    similar = CUISINE_SIMILARITY.get(cuisine_lower, [])
    return sorted(similar, key=lambda x: x[1], reverse=True)[:top_n]


def get_crossover_cuisine(
    preferred_cuisines: list[str],
    tried_cuisines: Optional[set[str]] = None,
) -> Optional[str]:
    """
    Suggest a crossover cuisine the user hasn't tried yet,
    based on their preferred cuisines.

    Args:
        preferred_cuisines: User's top cuisine preferences
        tried_cuisines: Set of cuisines already in the user's dataset

    Returns:
        A cuisine string to suggest, or None if no good crossover found.
    """
    if tried_cuisines is None:
        tried_cuisines = set()

    tried_lower = {c.lower() for c in tried_cuisines}

    candidates: list[tuple[str, float]] = []

    for pref in preferred_cuisines:
        for similar_cuisine, score in get_similar_cuisines(pref):
            if similar_cuisine not in tried_lower:
                candidates.append((similar_cuisine, score))

    if not candidates:
        return None

    # Weighted random selection — higher similarity = more likely
    candidates.sort(key=lambda x: x[1], reverse=True)
    top_candidates = candidates[:5]
    weights = [c[1] for c in top_candidates]
    total = sum(weights)
    if total == 0:
        return random.choice(top_candidates)[0]

    return random.choices(
        [c[0] for c in top_candidates],
        weights=weights,
        k=1
    )[0]


def get_serendipitous_cuisine(
    preferred_cuisines: list[str],
    available_cuisines: list[str],
) -> Optional[str]:
    """
    Pick a serendipitous (surprise) cuisine that the user hasn't tried
    but might enjoy based on flavor profile similarity.

    NOT random garbage — a thoughtful surprise.
    """
    preferred_lower = {c.lower() for c in preferred_cuisines}
    available_lower = {c.lower() for c in available_cuisines}

    # Find available cuisines the user hasn't tried
    untried = available_lower - preferred_lower
    if not untried:
        return random.choice(list(available_lower)) if available_lower else None

    # Score each untried cuisine by similarity to any preferred cuisine
    scores: dict[str, float] = {}
    for untried_cuisine in untried:
        max_sim = 0.0
        for pref in preferred_cuisines:
            for similar, sim_score in get_similar_cuisines(pref):
                if similar == untried_cuisine:
                    max_sim = max(max_sim, sim_score)
        scores[untried_cuisine] = max_sim

    # Prefer high-similarity untried cuisines, with some randomness
    if not scores:
        return random.choice(list(untried))

    # Sort by similarity and pick from top with weighted randomness
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_n = sorted_scores[:5]

    if top_n[0][1] > 0:
        return random.choices(
            [c[0] for c in top_n],
            weights=[s + 0.1 for _, s in top_n],
            k=1
        )[0]

    # No good similarity match — pick a random untried cuisine
    return random.choice(list(untried))
