"""Tests for haversine distance calculation."""

from utils.haversine import haversine_distance, compute_walk_distance, compute_drive_distance, estimate_walk_time, estimate_drive_time


def test_haversine_same_point():
    """Distance from a point to itself is 0."""
    dist = haversine_distance(22.2783, 114.1540, 22.2783, 114.1540)
    assert dist == 0.0


def test_haversine_known_distance():
    """Test a known distance: Central to Wan Chai ~3km."""
    dist = haversine_distance(22.2783, 114.1540, 22.2790, 114.1750)
    # Should be roughly 2.1 km straight-line
    assert 1500 < dist < 3000


def test_haversine_positive():
    """Distance should always be non-negative."""
    dist = haversine_distance(22.0, 114.0, 23.0, 115.0)
    assert dist > 0


def test_walk_distance_multiplier():
    """Walking distance should be greater than straight-line."""
    straight = 1000
    walk = compute_walk_distance(straight)
    assert walk > straight


def test_drive_distance_multiplier():
    """Driving distance should be slightly greater than straight-line."""
    straight = 1000
    drive = compute_drive_distance(straight)
    assert drive > straight
    assert drive < compute_walk_distance(straight)  # Drive < walk


def test_haversine_zero_coordinates():
    """Haversine should handle coordinates at 0,0 (Gulf of Guinea)."""
    dist = haversine_distance(0, 0, 1, 1)
    assert dist > 0


def test_haversine_negative_coordinates():
    """Haversine should handle negative coordinates."""
    dist = haversine_distance(-22.0, -114.0, 22.0, 114.0)
    assert dist > 0


def test_haversine_antipodal():
    """Distance between near-antipodal points should be close to half Earth circumference."""
    dist = haversine_distance(0, 0, 0, 180)
    # Half Earth circumference ≈ 20,015 km
    assert 19_000_000 < dist < 21_000_000


def test_estimate_walk_time_zero():
    """Zero distance should give 0 walk time."""
    assert estimate_walk_time(0) == 0


def test_estimate_drive_time_zero():
    """Zero distance should give 0 drive time."""
    assert estimate_drive_time(0) == 0


def test_walk_distance_zero():
    """Zero straight-line distance gives zero walk distance."""
    assert compute_walk_distance(0) == 0
