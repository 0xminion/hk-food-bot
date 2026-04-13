"""Tests for time-aware filtering."""

from engine.time_aware import (
    parse_opening_hours,
    parse_hours_range,
    get_time_of_day,
    get_open_status_label,
)


def test_parse_hours_range_simple():
    """Parse a simple time range."""
    result = parse_hours_range("11:00-22:00")
    assert result == (11, 22)


def test_parse_hours_range_with_dash():
    """Parse with en-dash."""
    result = parse_hours_range("11:00–22:00")
    assert result == (11, 22)


def test_parse_hours_range_no_minutes():
    """Parse without minutes."""
    result = parse_hours_range("11-22")
    assert result == (11, 22)


def test_parse_opening_hours_all_days():
    """Parse hours without day range (all days)."""
    result = parse_opening_hours("11:00-22:00")
    assert len(result) > 0  # Should apply to at least some days


def test_parse_opening_hours_day_range():
    """Parse Mo-Fr range."""
    result = parse_opening_hours("Mo-Fr 11:00-22:00")
    assert "mon" in result
    assert "fri" in result
    assert "sat" not in result


def test_parse_opening_hours_empty():
    """Empty string returns empty dict."""
    assert parse_opening_hours("") == {}
    assert parse_opening_hours(None) == {}


def test_get_time_of_day():
    """Time of day should return a valid string."""
    tod = get_time_of_day()
    assert tod in ("morning", "lunch", "afternoon", "dinner", "late-night")


def test_get_open_status_label_unknown():
    """Empty hours returns unknown status."""
    label = get_open_status_label("")
    assert "unknown" in label.lower()


def test_parse_hours_range_midnight():
    """Midnight end (00:00) should be converted to 24."""
    result = parse_hours_range("18:00-00:00")
    assert result == (18, 24)


def test_parse_opening_hours_midnight_end():
    """Hours ending at midnight should apply to all days with end=24."""
    result = parse_opening_hours("Mo-Su 18:00-00:00")
    assert "mon" in result
    assert result["mon"] == [(18, 24)]


def test_parse_opening_hours_overnight():
    """Overnight hours (22:00-02:00) should parse correctly."""
    result = parse_opening_hours("Mo-Su 22:00-02:00")
    assert "mon" in result
    assert result["mon"] == [(22, 2)]


def test_parse_opening_hours_no_day_range():
    """Hours without day range should apply to all days."""
    result = parse_opening_hours("11:00-22:00")
    assert len(result) == 7  # All 7 days
    assert "mon" in result
    assert "sun" in result


def test_parse_opening_hours_weekend_only():
    """Weekend-only hours should only apply to Sat/Sun."""
    result = parse_opening_hours("Sa-Su 12:00-23:00")
    assert "sat" in result
    assert "sun" in result
    assert "mon" not in result
    assert "fri" not in result
