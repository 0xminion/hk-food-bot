"""Haversine distance calculation utilities."""

import math
from typing import NamedTuple


class Coordinates(NamedTuple):
    """Geographic coordinates."""
    lat: float
    lng: float


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate the great-circle distance between two points on Earth
    using the Haversine formula.

    Returns distance in meters.
    """
    # Guard against NaN inputs
    if any(math.isnan(v) for v in (lat1, lng1, lat2, lng2)):
        return float('inf')

    R = 6371000  # Earth's radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def estimate_walk_time(distance_m: float) -> int:
    """Estimate walking time in minutes. Average walking speed ~5 km/h."""
    return int(distance_m / 1000 * 12)  # 12 min per km


def estimate_drive_time(distance_m: float) -> int:
    """Estimate driving time in minutes. Average HK driving speed ~25 km/h."""
    return int(distance_m / 1000 * 2.4)  # ~25 km/h average in HK


def compute_walk_distance(distance_m: float) -> int:
    """Compute walking distance (roughly 1.3x straight-line for urban HK)."""
    return int(distance_m * 1.3)


def compute_drive_distance(distance_m: float) -> int:
    """Compute driving distance (roughly 1.15x straight-line)."""
    return int(distance_m * 1.15)
