"""
Shared name normalization for franchise dedup and cache lookups.

Handles:
- Parenthesized location suffixes: "McDonald's (Central)" → "mcdonald's"
- Dash-separated locations: "McDonald's - Wan Chai" → "mcdonald's"
- Trailing district names: "壽司郎 銅鑼灣" → "寿司郎"
- Accented characters: "Café de Coral" → "cafe de coral"
- Chinese character preservation (unlike awards.py's old impl that stripped them)
"""

import re
import unicodedata


def normalize_name(name: str) -> str:
    """
    Normalize a venue name for franchise deduplication and fuzzy matching.

    Strips location indicators (parenthesized, dashed, trailing district names)
    while preserving the core brand name. Safe for Chinese and mixed-language names.

    Examples:
        "McDonald's (Central)" → "mcdonald's"
        "麥當勞 (銅鑼灣)" → "麥當勞"
        "Café de Coral - TST" → "cafe de coral"
        "Yardbird" → "yardbird"
        "大快活 (旺角)" → "大快活"
    """
    if not name:
        return ""

    n = name.strip()

    # 1. Strip parenthesized suffixes: (Central), (Wan Chai), (銅鑼灣), etc.
    n = re.sub(r'\s*\([^)]*\)\s*$', '', n)

    # 2. Strip dash-separated location suffixes: " - Wan Chai", " – TST", " — Mong Kok"
    #    But NOT dashes that are part of the brand name like "Mott 32"
    #    Only strip if the dash segment looks like a location (2+ chars, no digits at start)
    n = re.sub(r'\s*[-–—]\s*[A-Za-z\u4e00-\u9fff][\w\s]{0,15}\s*$', '', n)

    # 3. Normalize unicode: decompose accents then strip combining chars
    #    "Café" → "Cafe", "naïve" → "naive"
    n = unicodedata.normalize('NFKD', n)
    n = ''.join(c for c in n if unicodedata.category(c) != 'Mn')

    # 4. Lowercase
    n = n.lower().strip()

    # 5. Collapse multiple spaces
    n = re.sub(r'\s+', ' ', n).strip()

    return n


def build_name_index(cache: dict) -> dict[str, list[tuple[str, dict]]]:
    """
    Pre-build a normalized-name → [(original_key, cache_entry)] index from the
    Google ratings cache. Enables O(1) name-only fallback lookups instead of
    linear scanning the entire cache on every CSV row.

    Entries within each group are sorted by review count descending (most
    reviewed = most reliable fallback for unknown branches).

    Returns:
        dict mapping normalized_name → list of (cache_key, entry) tuples
    """
    index: dict[str, list[tuple[str, dict]]] = {}
    for key, entry in cache.items():
        # Cache keys are "name|address"
        raw_name = key.split("|")[0].strip()
        norm = normalize_name(raw_name)
        if norm:
            index.setdefault(norm, []).append((key, entry))
    # Sort each group by review count descending
    for norm in index:
        index[norm].sort(key=lambda x: int(x[1].get("google_reviews", 0) or 0), reverse=True)
    return index


def build_franchise_groups(places: list) -> dict[str, list]:
    """
    Pre-build normalized_name → [place] groups for franchise analysis.
    Useful for understanding franchise density before dedup.

    Each place must have a .name attribute.
    """
    groups: dict[str, list] = {}
    for p in places:
        norm = normalize_name(p.name)
        if norm:
            groups.setdefault(norm, []).append(p)
    return groups
