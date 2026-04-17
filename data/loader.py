"""CSV data loader and filtering utilities for HK Food Bot."""

import csv
import json
import math
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Place:
    """Represents a restaurant or bar."""
    name: str
    type: str  # "restaurant" or "bar"
    cuisine_tags: list[str] = field(default_factory=list)
    style_tags: list[str] = field(default_factory=list)
    address: str = ""
    address_en: str = ""
    lat: float = 0.0
    lng: float = 0.0
    district: str = ""
    google_rating: float = 0.0
    or_rating: float = 0.0
    or_score: float = 0.0
    review_count: int = 0
    bookmark_count: int = 0
    price_range: str = ""
    google_place_id: str = ""
    booking_url: str = ""
    booking_platform: str = ""
    opening_hours: str = ""
    is_open_now: bool = False
    popular_dishes: list[str] = field(default_factory=list)
    award_status: int = 0
    source_url: str = ""
    is_secret_gem: bool = False
    is_closed: bool = False
    last_updated: str = ""
    source: str = ""
    distance_walk_m: int = 0
    distance_drive_m: int = 0


def _parse_tags(raw: str) -> list[str]:
    """Parse comma-separated tag string into a clean list."""
    if not raw:
        return []
    # Remove brackets, quotes, and split
    cleaned = raw.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    return [t.strip().lower() for t in cleaned.replace('"', "").replace("'", "").split(",") if t.strip()]


def _safe_float(value: str, default: float = 0.0) -> float:
    """Safely parse a float from string."""
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        return default


def _safe_int(value: str, default: int = 0) -> int:
    """Safely parse an int from string."""
    try:
        return int(float(value)) if value else default
    except (ValueError, TypeError):
        return default


def _parse_closed_status(*values: str) -> bool:
    text = " ".join(v for v in values if v).lower()
    closed_tokens = (
        "temporarily closed", "permanently closed", "closed down",
        "已結業", "永久停業", "暫停營業", "歇業",
    )
    return any(token in text for token in closed_tokens)


def load_closed_places(data_dir: str | Path) -> set[str]:
    """Load manually verified closed place names from closed_places.txt."""
    path = Path(data_dir) / "closed_places.txt"
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line.lower())
    logger.info(f"Loaded {len(names)} closed places from {path}")
    return names


def load_personal_exclusions(data_dir: str | Path) -> set[str]:
    """Load personal exclusion list (e.g. minion abc) from exclude_personal.txt."""
    path = Path(data_dir) / "exclude_personal.txt"
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line.lower())
    logger.info(f"Loaded {len(names)} personal exclusions from {path}")
    return names


def _load_google_cache(data_dir: str | Path) -> dict:
    """Load Google ratings cache from shared singleton."""
    from data.google_cache import get_cache
    return get_cache()


def load_places(csv_path: str | Path) -> list[Place]:
    """Load places from CSV file, enriched with cached Google ratings."""
    path = Path(csv_path)
    if not path.exists():
        logger.error(f"CSV file not found: {path}")
        return []

    google_cache = _load_google_cache(path.parent)
    places: list[Place] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                name = (row.get("name") or "").strip()
                if not name:
                    continue  # Skip rows with no name

                raw_type = (row.get("type") or "restaurant").strip().lower()
                if raw_type not in ("restaurant", "bar"):
                    raw_type = "restaurant"

                lat = _safe_float(row.get("lat"))
                lng = _safe_float(row.get("lng"))

                # Validate coordinate ranges
                if not (-90.0 <= lat <= 90.0):
                    lat = 0.0
                if not (-180.0 <= lng <= 180.0):
                    lng = 0.0

                # Clamp rating to valid range
                google_rating = max(0.0, min(5.0, _safe_float(row.get("google_rating"))))
                or_rating = max(0.0, min(5.0, _safe_float(row.get("or_rating"))))

                review_count = max(0, _safe_int(row.get("review_count")))

                # Enrich with Google ratings from cache
                address = (row.get("address") or "").strip()
                cache_key = f"{name}|{address}"
                cached = google_cache.get(cache_key)
                if not cached:
                    # Fallback: name-only match
                    name_lower = name.lower()
                    for ck, cv in google_cache.items():
                        if ck.split("|")[0].strip().lower() == name_lower:
                            cached = cv
                            break
                if cached and cached.get("google_rating") and not google_rating:
                    google_rating = max(0.0, min(5.0, float(cached["google_rating"])))
                    review_count = max(review_count, int(cached.get("google_reviews", 0)))

                # Parse popular_dishes
                raw_dishes = row.get("popular_dishes") or "[]"
                try:
                    dishes = json.loads(raw_dishes)
                    if not isinstance(dishes, list):
                        dishes = []
                except (json.JSONDecodeError, TypeError):
                    dishes = []

                places.append(Place(
                    name=name,
                    type=raw_type,
                    cuisine_tags=_parse_tags(row.get("cuisine_tags") or ""),
                    style_tags=_parse_tags(row.get("style_tags") or ""),
                    address=address,
                    address_en=(row.get("address_en") or "").strip(),
                    lat=lat,
                    lng=lng,
                    district=(row.get("district") or "").strip(),
                    google_rating=google_rating,
                    or_rating=or_rating,
                    or_score=max(0.0, min(1.0, _safe_float(row.get("or_score")))),
                    review_count=review_count,
                    bookmark_count=max(0, _safe_int(row.get("bookmark_count"))),
                    price_range=(row.get("price_range") or "").strip(),
                    google_place_id=(row.get("google_place_id") or "").strip(),
                    booking_url=(row.get("booking_url") or "").strip(),
                    booking_platform=(row.get("booking_platform") or "").strip(),
                    opening_hours=(row.get("opening_hours") or "").strip(),
                    is_open_now=(row.get("is_open_now") or "").lower() == "true",
                    popular_dishes=dishes,
                    award_status=_safe_int(row.get("award_status")),
                    source_url=(row.get("source_url") or "").strip(),
                    is_secret_gem=(row.get("is_secret_gem") or "false").lower() in ("1", "true"),
                    is_closed=_parse_closed_status(row.get("status") or "", row.get("opening_hours") or "", row.get("source_url") or ""),
                    last_updated=(row.get("last_updated") or "").strip(),
                    source=(row.get("source") or "").strip(),
                ))
            except Exception as e:
                logger.warning(f"Error parsing row '{row.get('name', '?')}': {e}")
                continue

    logger.info(f"Loaded {len(places)} places from {path}")
    return places


def filter_by_type(places: list[Place], place_type: str) -> list[Place]:
    """Filter places by type (restaurant or bar)."""
    return [p for p in places if p.type == place_type]


def compute_distances(places: list[Place], user_lat: float, user_lng: float) -> list[Place]:
    """Compute haversine distance for each place and set walk/drive estimates."""
    from utils.haversine import haversine_distance, compute_walk_distance, compute_drive_distance

    for p in places:
        # Skip places with invalid or missing coordinates
        if (p.lat == 0.0 and p.lng == 0.0
                or math.isnan(p.lat) or math.isnan(p.lng)):
            p.distance_walk_m = 99999
            p.distance_drive_m = 99999
            continue

        straight_line = haversine_distance(user_lat, user_lng, p.lat, p.lng)
        p.distance_walk_m = compute_walk_distance(straight_line)
        p.distance_drive_m = compute_drive_distance(straight_line)

    return places


def get_unique_cuisines(places: list[Place]) -> list[str]:
    """Get all unique cuisine tags from a list of places."""
    tags: set[str] = set()
    for p in places:
        tags.update(p.cuisine_tags)
    return sorted(tags)


def filter_by_cuisine(places: list[Place], cuisines: list[str]) -> list[Place]:
    """Filter places that match any of the given cuisine tags."""
    cuisine_set = {c.lower() for c in cuisines}
    return [p for p in places if cuisine_set & set(p.cuisine_tags)]


def filter_by_any_tag(places: list[Place], tags: list[str]) -> list[Place]:
    """Filter places that match any cuisine or style tag."""
    tag_set = {t.lower() for t in tags}
    return [p for p in places if tag_set & (set(p.cuisine_tags) | set(p.style_tags))]


def get_all_places(csv_path: str | Path) -> list[Place]:
    """Convenience: load all places from the given CSV path."""
    return load_places(csv_path)
