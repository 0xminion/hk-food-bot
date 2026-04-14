"""
Cuisine group fuzzy matching for HK Food Bot.
Maps regional/umbrella terms to specific cuisine tags.
"""

import re

# Regional cuisine groups
CUISINE_GROUPS = {
    # Southeast Asian
    "sea": ["thai", "vietnamese", "malaysian", "indonesian", "filipino", "singaporean", "cambodian", "burmese", "laotian"],
    "southeast asian": ["thai", "vietnamese", "malaysian", "indonesian", "filipino", "singaporean", "cambodian", "burmese", "laotian"],
    "southeast_asian": ["thai", "vietnamese", "malaysian", "indonesian", "filipino", "singaporean", "cambodian", "burmese", "laotian"],
    "southeastasian": ["thai", "vietnamese", "malaysian", "indonesian", "filipino", "singaporean", "cambodian", "burmese", "laotian"],
    "south-east-asian": ["thai", "vietnamese", "malaysian", "indonesian", "filipino", "singaporean", "cambodian", "burmese", "laotian"],

    # East Asian
    "east asian": ["chinese", "japanese", "korean", "taiwanese", "hong kong"],
    "east_asian": ["chinese", "japanese", "korean", "taiwanese", "hong kong"],

    # European / EU
    "eu": ["italian", "french", "spanish", "greek", "british", "german", "portuguese", "scandinavian", "eastern european"],
    "european": ["italian", "french", "spanish", "greek", "british", "german", "portuguese", "scandinavian", "eastern european"],
    "europe": ["italian", "french", "spanish", "greek", "british", "german", "portuguese", "scandinavian", "eastern european"],

    # South Asian
    "south asian": ["indian", "nepalese", "sri lankan", "pakistani", "bangladeshi"],
    "south_asian": ["indian", "nepalese", "sri lankan", "pakistani", "bangladeshi"],

    # Latin / Central / South American
    "latin": ["mexican", "peruvian", "brazilian", "argentinian", "colombian", "cuban"],
    "latin american": ["mexican", "peruvian", "brazilian", "argentinian", "colombian", "cuban"],
    "latino": ["mexican", "peruvian", "brazilian", "argentinian", "colombian", "cuban"],

    # Middle Eastern
    "middle eastern": ["lebanese", "turkish", "persian", "israeli", "iranian", "arabic"],
    "middle_eastern": ["lebanese", "turkish", "persian", "israeli", "iranian", "arabic"],

    # Mediterranean
    "mediterranean": ["italian", "greek", "turkish", "lebanese", "spanish", "moroccan", "french"],

    # Asian (broad)
    "asian": ["chinese", "japanese", "korean", "thai", "vietnamese", "malaysian", "indonesian", "indian", "taiwanese", "singaporean", "filipino"],

    # Noodles
    "noodles": ["japanese", "chinese", "korean", "thai", "vietnamese", "malaysian", "taiwanese"],

    # BBQ / Grilling
    "bbq": ["korean", "japanese", "american", "turkish"],
    "grill": ["korean", "japanese", "american", "turkish", "steakhouse"],
    "bbq and grill": ["korean", "japanese", "american", "turkish", "steakhouse"],

    # Seafood
    "seafood": ["seafood", "japanese", "chinese", "portuguese", "mediterranean"],

    # Western
    "western": ["italian", "french", "american", "british", "spanish", "german", "australian"],

    # Bar types
    "bars": ["cocktail-bar", "wine-bar", "speakeasy", "rooftop-bar", "craft-beer", "pub", "lounge"],
    "cocktail": ["cocktail-bar", "speakeasy", "rooftop-bar"],
    "cocktails": ["cocktail-bar", "speakeasy", "rooftop-bar"],
    "wine": ["wine-bar"],
    "beer": ["craft-beer", "pub"],
}

# Abbreviation lookup
ABBREVIATIONS = {
    "sea": "sea",
    "eu": "eu",
    "hk": "hong kong",
    "jp": "japanese",
    "cn": "chinese",
    "kr": "korean",
    "th": "thai",
    "vn": "vietnamese",
    "my": "malaysian",
    "id": "indonesian",
    "ph": "filipino",
    "in": "indian",
    "it": "italian",
    "fr": "french",
    "es": "spanish",
    "mx": "mexican",
}


def resolve_cuisine_input(text: str) -> list[str]:
    """
    Resolve user text input to cuisine tags.
    Handles abbreviations, regional groups, and direct cuisine names.

    Examples:
        "sea" -> ["thai", "vietnamese", "malaysian", ...]
        "South East Asian" -> ["thai", "vietnamese", "malaysian", ...]
        "EU" -> ["italian", "french", "spanish", ...]
        "European" -> ["italian", "french", "spanish", ...]
        "Italian" -> ["italian"]
    """
    normalized = re.sub(r'[^a-z0-9]+', '-', text.lower().strip()).strip('-')

    # Check abbreviations first
    if normalized in ABBREVIATIONS:
        normalized = ABBREVIATIONS[normalized]

    # Check direct group match
    if normalized in CUISINE_GROUPS:
        return CUISINE_GROUPS[normalized]

    # Check multi-word normalization
    multi_key = re.sub(r'[-_]+', ' ', normalized)
    if multi_key in CUISINE_GROUPS:
        return CUISINE_GROUPS[multi_key]

    # Also try collapsing spaces (e.g., "south east asian" -> "southeast asian")
    collapsed = re.sub(r'\s+', '', normalized)
    if collapsed in CUISINE_GROUPS:
        return CUISINE_GROUPS[collapsed]
    collapsed_dash = re.sub(r'\s+', '-', normalized)
    if collapsed_dash in CUISINE_GROUPS:
        return CUISINE_GROUPS[collapsed_dash]

    underscore_key = re.sub(r'[-\s]+', '_', normalized)
    if underscore_key in CUISINE_GROUPS:
        return CUISINE_GROUPS[underscore_key]

    # Check partial match against group names — prefer longer matches
    best_match = None
    best_match_len = 0
    for group_name, cuisines in CUISINE_GROUPS.items():
        if normalized in group_name or group_name in normalized:
            if len(group_name) > best_match_len:
                best_match = cuisines
                best_match_len = len(group_name)
    if best_match:
        return best_match

    # No group match — return as single cuisine tag
    return [normalized]
