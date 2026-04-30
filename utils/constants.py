"""Shared constants used across multiple layers."""

# HK area definitions (keyed by short label, value = (lat, lng))
HK_AREAS = {
    "Central":      (22.2783, 114.1540),
    "Wan Chai":     (22.2790, 114.1750),
    "Causeway Bay": (22.2800, 114.1850),
    "TST":          (22.2970, 114.1700),
    "Mong Kok":     (22.3190, 114.1690),
    "Sai Ying Pun": (22.2860, 114.1420),
    "Sheung Wan":   (22.2860, 114.1500),
    "Admiralty":    (22.2780, 114.1650),
    "Tin Hau":      (22.2840, 114.1920),
    "Kennedy Town": (22.2810, 114.1300),
}

# Extra area coordinates for scope expansion (not in main UI)
EXTRA_AREA_COORDS = {
    "Jordan": (22.3064, 114.1717),
    "Yau Ma Tei": (22.3069, 114.1709),
    "North Point": (22.2910, 114.1970),
    "Prince Edward": (22.3247, 114.1686),
}
