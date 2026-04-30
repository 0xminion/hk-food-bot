"""Price-range parsing and matching logic."""


def _parse_price_tier(price_range: str) -> int:
    """Map OpenRice numeric price range to tier 0-4."""
    if not price_range:
        return 0
    pr = price_range.strip()
    # Match numeric patterns like $50以下, $51-100, $101-200, $201-400, $401-800, $801以上
    if pr.startswith("$50") or "50以下" in pr:
        return 1
    if "51-100" in pr or "101-200" in pr:
        return 1
    if "201-400" in pr:
        return 2
    if "401-800" in pr:
        return 3
    if "801" in pr:
        return 4
    # Fallback to dollar-sign count
    return pr.count("$")


def price_matches(price_range: str, selected: str) -> bool:
    """Check if a place's price_range matches the selected budget filter."""
    if selected == "any" or not price_range:
        return True
    selected_tier = _parse_price_tier(selected)
    range_tier = _parse_price_tier(price_range)
    if range_tier == 0:
        return True  # Unknown price — include it
    return range_tier == selected_tier
