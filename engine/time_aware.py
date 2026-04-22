"""
Time-aware filtering module.

Filters places by opening hours, only showing currently open venues.
Also provides time-of-day awareness for suggestions (brunch, late-night, etc.).
"""

import logging
import re
from datetime import datetime, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

HK_TZ = ZoneInfo("Asia/Hong_Kong")

# Day name mapping
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_FULL = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def get_current_hk_time() -> datetime:
    """Get current time in Hong Kong timezone."""
    return datetime.now(HK_TZ)


def get_current_day_abbr() -> str:
    """Get current day abbreviation (e.g., 'mon', 'tue')."""
    now = get_current_hk_time()
    return DAY_NAMES[now.weekday()]


def get_time_of_day() -> str:
    """Classify the current time of day."""
    hour = get_current_hk_time().hour
    if 6 <= hour < 11:
        return "morning"
    elif 11 <= hour < 14:
        return "lunch"
    elif 14 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "dinner"
    elif 21 <= hour < 24:
        return "late-night"
    else:
        return "late-night"  # midnight to 6am


def parse_hours_range(hours_str: str) -> Optional[tuple[int, int, int, int]]:
    """
    Parse a time range like '11:30-22:00' into (start_hour, start_min, end_hour, end_min).
    Returns None if parsing fails.
    """
    match = re.search(r'(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})', hours_str)
    if match:
        start_h = int(match.group(1))
        start_m = int(match.group(2))
        end_h = int(match.group(3))
        end_m = int(match.group(4))
    else:
        # Fallback for strings without colon like "11-22"
        match = re.search(r'(\d{1,2})\s*[-–]\s*(\d{1,2})', hours_str)
        if not match:
            return None
        start_h = int(match.group(1))
        start_m = 0
        end_h = int(match.group(2))
        end_m = 0
    # Convert midnight (00:00) to 24:00 for consistent range logic
    if end_h == 0 and end_m == 0:
        end_h = 24
    return (start_h, start_m, end_h, end_m)


def parse_all_hours_ranges(hours_str: str) -> list[tuple[int, int, int, int]]:
    """
    Parse ALL time ranges from a string. Handles multiple periods like:
    '12:00-14:30, 18:00-22:00' → [(12, 0, 14, 30), (18, 0, 22, 0)]
    """
    ranges = []
    for match in re.finditer(r'(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})', hours_str):
        start_h = int(match.group(1))
        start_m = int(match.group(2))
        end_h = int(match.group(3))
        end_m = int(match.group(4))
        if end_h == 0 and end_m == 0:
            end_h = 24
        ranges.append((start_h, start_m, end_h, end_m))
    return ranges


def parse_opening_hours(opening_hours: str) -> dict[str, list[tuple[int, int, int, int]]]:
    """
    Parse structured opening hours string into a dict of day -> [(start, end)].
    
    Handles formats like:
    - "Mo-Fr 11:00-22:00"
    - "Mo-Su 12:00-23:00"
    - "11:00-22:00" (assumes all days)
    - "Mo-We,Fr 12:00-22:00"
    - "Mo-Su 12:00-14:30, 18:00-22:00" (multi-period)
    """
    result: dict[str, list[tuple[int, int]]] = {}

    if not opening_hours or not opening_hours.strip():
        return result

    hours_str = opening_hours.strip()

    # Extract ALL time ranges (handles multi-period like lunch + dinner)
    time_ranges = parse_all_hours_ranges(hours_str)
    if not time_ranges:
        return result

    # Try to extract day range
    day_patterns = {
        "mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    }

    # Check for day range like "Mo-Fr" or "Mo-Su"
    days_to_apply = list(range(7))  # Default: all days

    day_range_match = re.search(
        r'(mo|tu|we|th|fr|sa|su|mon|tue|wed|thu|fri|sat|sun)\s*[-–]\s*'
        r'(mo|tu|we|th|fr|sa|su|mon|tue|wed|thu|fri|sat|sun)',
        hours_str, re.IGNORECASE
    )
    if day_range_match:
        start_day = day_patterns.get(day_range_match.group(1).lower(), 0)
        end_day = day_patterns.get(day_range_match.group(2).lower(), 6)
        if start_day <= end_day:
            days_to_apply = list(range(start_day, end_day + 1))
        else:
            # Wraps around (e.g., Fr-Mo)
            days_to_apply = list(range(start_day, 7)) + list(range(0, end_day + 1))

    for day_idx in days_to_apply:
        day_name = DAY_NAMES[day_idx]
        for time_range in time_ranges:
            result.setdefault(day_name, []).append(time_range)

    # Also handle comma-separated individual days like "Mo,We,Fr 11:00-22:00"
    single_days = re.finditer(
        r'\b(mo|tu|we|th|fr|sa|su|mon|tue|wed|thu|fri|sat|sun)\b',
        hours_str, re.IGNORECASE
    )
    seen_single = set()
    for m in single_days:
        d = day_patterns.get(m.group(1).lower())
        if d is not None and d not in seen_single:
            seen_single.add(d)
            if d not in days_to_apply:
                day_name = DAY_NAMES[d]
                for time_range in time_ranges:
                    result.setdefault(day_name, []).append(time_range)

    return result


def is_open_now(opening_hours: str) -> Optional[bool]:
    """
    Check if a place is currently open based on opening_hours string.
    
    Returns:
        True if open, False if closed, None if cannot determine.
    """
    if not opening_hours or not opening_hours.strip():
        return None

    raw = opening_hours.strip().lower()
    if "temporarily closed" in raw or "permanently closed" in raw:
        return False
    if raw == "closed" or raw.startswith("closed "):
        return False

    parsed = parse_opening_hours(opening_hours)
    if not parsed:
        return None

    now = get_current_hk_time()
    current_day = DAY_NAMES[now.weekday()]
    current_hour = now.hour
    current_minute = now.minute
    current_time_decimal = current_hour + current_minute / 60.0

    day_hours = parsed.get(current_day, [])
    for start_h, start_m, end_h, end_m in day_hours:
        start_dec = start_h + start_m / 60.0
        end_dec = end_h + end_m / 60.0
        # Handle overnight hours (e.g., 22:00-02:00, where end_dec < start_dec)
        if end_dec <= start_dec:
            # Overnight: open from start until midnight, or from midnight until end
            if current_time_decimal >= start_dec or current_time_decimal < end_dec:
                return True
        else:
            if start_dec <= current_time_decimal < end_dec:
                return True

    return False


def filter_open_places(places: list) -> list:
    """
    Filter a list of places to only include currently open ones.
    Places with no hours data are included (we can't determine, so don't exclude).
    """
    open_places = []
    for place in places:
        status = is_open_now(place.opening_hours)
        if status is True or status is None:
            open_places.append(place)
        else:
            logger.debug(f"Filtered out (closed): {place.name}")

    return open_places


def get_open_status_label(opening_hours: str) -> str:
    """Get a human-readable open/closed label."""
    status = is_open_now(opening_hours)
    if status is True:
        return "🟢 Open now"
    elif status is False:
        return "🔴 Closed"
    else:
        return "⚪ Hours unknown"
