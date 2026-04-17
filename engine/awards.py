"""
Awards and ranking data loader for HK Food Bot.
Matches award records to places by name and provides scoring boosts.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Award tier scores — flat line for Michelin, prestige differentiates via source multiplier
AWARD_SCORES = {
    # Michelin — flat score for any star/gourmand recognition
    "3-star": 50,
    "2-star": 50,
    "1-star": 50,
    "bib-gourmand": 50,
    "green-star": 50,
    "selected": 30,
    # 50 Best
    "world-50-best": 50,
    "asia-50-best": 50,
    "asia-50-best-bars": 50,
    # Time Out / Black Pearl
    "best-restaurants": 30,
    "best-bars": 30,
    "black-pearl-diamond": 50,
    "black-pearl-pearl": 50,
    # OpenTable
    "opentable-diners-choice": 20,
    "opentable-best": 20,
}

# Source prestige multipliers — flat, all sources equal
SOURCE_MULTIPLIERS = {
    "michelin": 1.0,
    "50best": 1.0,
    "blackpearl": 1.0,
    "timeout": 1.0,
    "opentable": 1.0,
}

_loaded_awards: dict[str, list[dict]] | None = None


def _normalize_name(name: str) -> str:
    """Normalize name for fuzzy matching."""
    n = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip().lower()
    n = re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '', n)
    return n


def load_awards(data_dir: str | Path) -> dict[str, list[dict]]:
    """
    Load awards data and build a lookup by normalized name.
    Returns dict: normalized_name -> list of award dicts.
    """
    global _loaded_awards
    if _loaded_awards is not None:
        return _loaded_awards

    path = Path(data_dir) / "awards.json"
    if not path.exists():
        logger.warning(f"Awards file not found: {path}")
        _loaded_awards = {}
        return _loaded_awards

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    lookup: dict[str, list[dict]] = {}
    for award in data.get("awards", []):
        key = _normalize_name(award.get("name", ""))
        if key:
            lookup.setdefault(key, []).append(award)

    _loaded_awards = lookup
    logger.info(f"Loaded {len(_loaded_awards)} unique awarded restaurants")
    return _loaded_awards


def get_award_boost(place_name: str, data_dir: str | Path) -> tuple[float, list[str]]:
    """
    Calculate award boost score for a place.
    Returns (boost_score, list_of_badge_strings).
    """
    awards_lookup = load_awards(data_dir)
    key = _normalize_name(place_name)
    awards = awards_lookup.get(key, [])

    if not awards:
        return 0.0, []

    total_score = 0.0
    badges = []
    for a in awards:
        level = a.get("level", "")
        source = a.get("source", "")
        year = a.get("year", 0)
        base_score = AWARD_SCORES.get(level, 10)
        multiplier = SOURCE_MULTIPLIERS.get(source, 1.0)

        # Recency bonus: within 5 years gets 1.5x, within 10 years gets 1.0x
        current_year = datetime.now().year
        age = current_year - year if year else 10
        recency = 1.5 if age <= 5 else (1.0 if age <= 10 else 0.5)

        total_score += base_score * multiplier * recency

        # Build badge
        badge_map = {
            "3-star": "⭐⭐⭐ Michelin",
            "2-star": "⭐⭐ Michelin",
            "1-star": "⭐ Michelin",
            "bib-gourmand": "🍽 Bib Gourmand",
            "green-star": "🌿 Green Star",
            "asia-50-best": "🏆 Asia's 50 Best",
            "asia-50-best-bars": "🍸 Asia's 50 Best Bars",
            "world-50-best": "🏆 World's 50 Best",
            "best-restaurants": "📰 Time Out Best",
            "best-bars": "📰 Time Out Best Bar",
        }
        badge = badge_map.get(level, f"🏅 {source.title()} {level}")
        if badge not in badges:
            badges.append(badge)

    return total_score, badges
