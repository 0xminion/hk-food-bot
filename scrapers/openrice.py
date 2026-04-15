#!/usr/bin/env python3
"""
OpenRice Hong Kong Scraper
==========================
Extracts restaurant and bar data from OpenRice's internal JSON API.
No HTML scraping or JS rendering required — the API returns clean JSON
when called with a mobile User-Agent.

Usage:
    python scrapers/openrice.py --output data/openrice_places.csv
    python scrapers/openrice.py --output data/openrice_places.csv --max-pages 100
    python scrapers/openrice.py --output data/openrice_places.csv --cuisine-ids 2004,2009
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip install requests")
    sys.exit(1)

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL = "https://www.openrice.com/api/pois"
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
DEFAULT_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "application/json",
    "Accept-Language": "en,zh;q=0.9",
    "Referer": "https://www.openrice.com/en/hongkong/restaurants",
}

# Rate limit: seconds between API requests
REQUEST_DELAY = 1.0
# Max retries per request
MAX_RETRIES = 3
# Retry backoff multiplier
RETRY_BACKOFF = 2.0

# Day-of-week mapping (OpenRice: 1=Mon, 7=Sun)
DOW_MAP = {1: "Mo", 2: "Tu", 3: "We", 4: "Th", 5: "Fr", 6: "Sa", 7: "Su"}

# Verified working cuisine IDs from OpenRice API (tested 2026-04-13).
# Each query is capped ~250 results, so querying by cuisine maximizes total venues.
DEFAULT_CUISINE_IDS = [
    # Asian (2000s)
    2001,  # 韓國菜 (Korean)
    2002,  # 越南菜 (Vietnamese)
    2003,  # 菲律賓菜 (Filipino)
    2004,  # 泰國菜 (Thai)
    2005,  # 新加坡菜 (Singaporean)
    2006,  # 印度菜 (Indian)
    2007,  # 印尼菜 (Indonesian)
    2008,  # 尼泊爾菜 (Nepalese)
    2009,  # 日本菜 (Japanese)
    2010,  # 斯里蘭卡菜 (Sri Lankan)
    2013,  # 緬甸菜 (Burmese)
    2021,  # 中東菜 (Middle Eastern)
    2022,  # 澳洲菜 (Australian)
    2023,  # 黎巴嫩菜 (Lebanese)
    2024,  # 馬來西亞菜 (Malaysian)
    6000,  # 多國菜 (International/Fusion)
    # European (3000s)
    3001,  # 德國菜 (German)
    3002,  # 葡國菜 (Portuguese)
    3004,  # 瑞士菜 (Swiss)
    3005,  # 愛爾蘭菜 (Irish)
    3006,  # 意大利菜 (Italian)
    3007,  # 奧地利菜 (Austrian)
    3008,  # 荷蘭菜 (Dutch)
    3009,  # 英國菜 (British)
    3010,  # 法國菜 (French)
    3011,  # 西班牙菜 (Spanish)
    3012,  # 地中海菜 (Mediterranean)
    3013,  # 比利時菜 (Belgian)
    3021,  # 東歐菜 (Eastern European)
    # Americas (4000s)
    4000,  # 西式 (Western)
    4001,  # 美國菜 (American)
    4002,  # 墨西哥菜 (Mexican)
    4003,  # 古巴菜 (Cuban)
    4004,  # 巴西菜 (Brazilian)
    4005,  # 阿根廷菜 (Argentinian)
    4006,  # 秘魯菜 (Peruvian)
    # African (5000s)
    5001,  # 非洲菜 (African)
    5004,  # 埃及菜 (Egyptian)
    5005,  # 摩洛哥菜 (Moroccan)
]

# Bar/pub related dish IDs that help identify bars
BAR_DISH_IDS = {1008}  # 酒 (Alcohol)

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("openrice")


# ── API Helpers ────────────────────────────────────────────────────────────────

def fetch_page(
    session: requests.Session,
    page: int = 1,
    cuisine_id: Optional[int] = None,
    sort_by: str = "DEFAULT",
) -> dict:
    """Fetch a single page of results from the OpenRice API."""
    params = {
        "uiLangId": 1,  # English
        "uiCityId": 1,  # Hong Kong
        "page": page,
        "sortBy": sort_by,
    }
    if cuisine_id is not None:
        params["cuisineId"] = cuisine_id

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            last_exc = e
            wait = REQUEST_DELAY * (RETRY_BACKOFF ** attempt)
            log.warning(f"Attempt {attempt}/{MAX_RETRIES} failed for page {page}: {e}. Retrying in {wait:.1f}s")
            time.sleep(wait)

    raise RuntimeError(f"Failed to fetch page {page} after {MAX_RETRIES} attempts: {last_exc}")


def parse_hours(poi_hours: list) -> str:
    """
    Convert OpenRice poiHours array to a compact string like:
    Mo-Th 12:00-22:30; Fr-Sa 12:00-23:00
    """
    if not poi_hours:
        return ""

    # Group hours by time range
    schedule: dict[tuple[str, str], set[int]] = {}
    for h in poi_hours:
        if h.get("isClose"):
            continue
        dow = h.get("dayOfWeek")
        if dow not in DOW_MAP:
            continue
        start = h.get("period1Start", "")[:5]  # HH:MM
        end = h.get("period1End", "")[:5]
        if not start or not end:
            continue
        key = (start, end)
        schedule.setdefault(key, set()).add(dow)

    if not schedule:
        return ""

    parts = []
    for (start, end), days in sorted(schedule.items()):
        day_list = sorted(days)
        # Compress consecutive days: Mo, Tu, We -> Mo-We
        ranges = []
        run_start = day_list[0]
        run_end = day_list[0]
        for d in day_list[1:]:
            if d == run_end + 1:
                run_end = d
            else:
                ranges.append((run_start, run_end))
                run_start = run_end = d
        ranges.append((run_start, run_end))

        day_strs = []
        for s, e in ranges:
            if s == e:
                day_strs.append(DOW_MAP[s])
            else:
                day_strs.append(f"{DOW_MAP[s]}-{DOW_MAP[e]}")
        parts.append(f"{','.join(day_strs)} {start}-{end}")

    return "; ".join(parts)


def classify_venue(categories: list) -> tuple[str, list[str], list[str]]:
    """
    Determine venue type (restaurant|bar), cuisine_tags, and style_tags
    from OpenRice categories.

    categoryTypeId:
        1 = cuisine (泰國菜, 日本菜, etc.)
        2 = dish type (海鮮, 烤肉, 酒, etc.)
        3 = amenity/type (居酒屋, 咖啡店, etc.)
    """
    cuisine_names = []
    dish_names = []
    amenity_names = []

    for cat in categories:
        cat_type = cat.get("categoryTypeId")
        name = cat.get("callName", cat.get("name", ""))
        if cat_type == 1:
            cuisine_names.append(name)
        elif cat_type == 2:
            dish_names.append(name)
        elif cat_type == 3:
            amenity_names.append(name)

    # Determine if venue is a bar
    is_bar = False
    bar_keywords = {"酒吧", "酒", "啤酒", "cocktail", "bar", "pub", "居酒屋", "清吧"}
    all_names = cuisine_names + dish_names + amenity_names
    for n in all_names:
        for kw in bar_keywords:
            if kw.lower() in n.lower():
                is_bar = True
                break
    # Also check amenity types
    bar_amenity_keywords = {"酒吧", "pub", "bar", "lounge"}
    for n in amenity_names:
        for kw in bar_amenity_keywords:
            if kw.lower() in n.lower():
                is_bar = True
                break

    venue_type = "bar" if is_bar else "restaurant"

    # Style tags from amenity types
    style_tag_mapping = {
        "居酒屋": "izakaya",
        "咖啡店": "cafe",
        "酒吧": "bar",
        "清吧": "chill-bar",
    }
    style_tags = []
    for n in amenity_names:
        for cn, en in style_tag_mapping.items():
            if cn in n:
                style_tags.append(en)

    # Translate common cuisine names to English
    cuisine_translation = {
        # Full format (XX菜)
        "泰國菜": "thai",
        "日本菜": "japanese",
        "韓國菜": "korean",
        "越南菜": "vietnamese",
        "意大利菜": "italian",
        "中國菜": "chinese",
        "法國菜": "french",
        "印度菜": "indian",
        "美國菜": "american",
        "西班牙菜": "spanish",
        "多國菜": "international",
        "地中海菜": "mediterranean",
        "新加坡菜": "singaporean",
        "英國菜": "british",
        "德國菜": "german",
        "俄羅斯菜": "russian",
        "希臘菜": "greek",
        "葡萄牙菜": "portuguese",
        "墨西哥菜": "mexican",
        "中東菜": "middle-eastern",
        "台灣菜": "taiwanese",
        "四川菜": "sichuan",
        "上海菜": "shanghainese",
        "廣東菜": "cantonese",
        "潮州菜": "teochew",
        "客家菜": "hakka",
        "北京菜": "beijing",
        "雲南菜": "yunnan",
        "星馬菜": "malaysian",
        "fusion": "fusion",
        "蒙古菜": "mongolian",
        # OpenRice shorthand (XX式, XX-YY)
        "西式": "western",
        "港式": "hk-style",
        "日式": "japanese",
        "韓式": "korean",
        "泰式": "thai",
        "越式": "vietnamese",
        "意式": "italian",
        "法式": "french",
        "美式": "american",
        "中式": "chinese",
        "印度式": "indian",
        "西班牙式": "spanish",
        "墨西哥式": "mexican",
        "台灣式": "taiwanese",
        # OpenRice hyphenated format (菜系-地區)
        "粵菜-廣東": "cantonese",
        "粵菜": "cantonese",
        "川菜-四川": "sichuan",
        "川菜": "sichuan",
        "滬菜-上海": "shanghainese",
        "滬菜": "shanghainese",
        "湘菜": "hunan",
        "閩菜": "fujian",
        "魯菜": "shandong",
        "浙菜": "zhejiang",
        "東北菜": "northeastern-chinese",
        "新疆菜": "xinjiang",
        "雲南菜": "yunnan",
        "潮州菜": "teochew",
        "客家菜": "hakka",
        "北京菜": "beijing",
        "星馬菜": "malaysian",
        # Dish-based categories (common on OpenRice)
        "火鍋": "hotpot",
        "燒烤": "bbq",
        "拉麵": "ramen",
        "壽司": "sushi",
        "刺身": "sashimi",
        "串燒": "yakitori",
        "居酒屋": "izakaya",
        "甜品": "dessert",
        "麵包": "bakery",
        "咖啡": "coffee",
        "茶餐廳": "cha-chaan-teng",
        "粥麵": "congee-noodles",
        "點心": "dim-sum",
        "粉麵": "noodles",
        "小吃": "snacks",
        "素食": "vegetarian",
        "海鮮": "seafood",
        "牛排": "steakhouse",
        # Regional Chinese cuisines (niches from OpenRice)
        "京川滬": "beijing-sichuan-shanghainese",
        "京菜-官府菜": "beijing",
        "湘菜-湖南": "hunan",
        "閩菜-福建": "fujian",
        "鲁菜-山東": "shandong",
        "浙菜-浙江": "zhejiang",
        "滇菜-雲南": "yunnan",
        "晋菜-山西": "shanxi",
        "陕菜-陕西": "shaanxi",
        "桂菜-廣西": "guangxi",
        "順德菜": "shunde",
        "淮揚菜": "huaiyang",
        "農家菜": "rural-chinese",
        "京菜": "beijing",
        "湘菜": "hunan",
        "閩菜": "fujian",
        "鲁菜": "shandong",
        "浙菜": "zhejiang",
        # Southeast Asian
        "馬來西亞菜": "malaysian",
        "印尼菜": "indonesian",
        "菲律賓菜": "filipino",
        "泰緬菜": "thai-burmese",
        "斯里蘭卡菜": "sri-lankan",
        # Middle East / Africa
        "黎巴嫩菜": "lebanese",
        "土耳其菜": "turkish",
        "摩洛哥菜": "moroccan",
        "非洲菜": "african",
        "中亞菜": "central-asian",
        # Europe
        "瑞士菜": "swiss",
        "東歐菜": "eastern-european",
        "比利時菜": "belgian",
        "奧地利菜": "austrian",
        "葡國菜": "portuguese",
        "澳洲菜": "australian",
        "英國菜": "british",
        "俄羅斯菜": "russian",
        # Latin America
        "阿根廷菜": "argentinian",
        "巴西菜": "brazilian",
        "秘魯菜": "peruvian",
        "墨西哥菜": "mexican",
        # Other
        "蒙古菜": "mongolian",
        "尼泊爾菜": "nepalese",
        "fusion菜": "fusion",
        # Newly discovered via API ID verification
        "愛爾蘭菜": "irish",
        "荷蘭菜": "dutch",
        "古巴菜": "cuban",
        "埃及菜": "egyptian",
        "緬甸菜": "burmese",
        "摩洛哥": "moroccan",
    }
    cuisine_tags = []
    for cn in cuisine_names:
        cuisine_tags.append(cuisine_translation.get(cn, cn.lower()))

    return venue_type, cuisine_tags, style_tags


def parse_venue(r: dict) -> Optional[dict]:
    """Parse a single venue from the API response into our CSV schema."""
    name = r.get("name", "").strip()
    if not name:
        return None

    categories = r.get("categories", [])
    venue_type, cuisine_tags, style_tags = classify_venue(categories)

    # Hours
    opening_hours = parse_hours(r.get("poiHours", []))

    # Source URL
    url_ui = r.get("urlUI", "")
    source_url = f"https://www.openrice.com{url_ui}" if url_ui else ""

    # Booking URL — OpenRice may have booking integration
    booking_url = ""
    booking_platform = ""
    # If the venue has table map or is booking-enabled
    if r.get("hasTableMapPoint") or r.get("tableMapPoiId"):
        booking_url = source_url  # Booking via OpenRice page
        booking_platform = "openrice"

    return {
        "name": name,
        "type": venue_type,
        "cuisine_tags": json.dumps(cuisine_tags, ensure_ascii=False),
        "style_tags": json.dumps(style_tags, ensure_ascii=False),
        "address": r.get("address", ""),
        "address_en": r.get("addressOtherLang", ""),
        "lat": r.get("mapLatitude", ""),
        "lng": r.get("mapLongitude", ""),
        "district": (r.get("district") or {}).get("name", ""),
        "google_rating": "",  # OpenRice rating, not Google
        "or_rating": r.get("scoreOverall", ""),  # Keep OpenRice rating separately
        "or_score": r.get("orScore", ""),
        "review_count": r.get("reviewCount", 0),
        "bookmark_count": r.get("bookmarkedUserCount", 0),
        "price_range": (r.get("priceUI") or "").strip(),
        "google_place_id": "",  # Not available from OpenRice
        "booking_url": booking_url,
        "booking_platform": booking_platform,
        "opening_hours": opening_hours,
        "is_open_now": str(r.get("openNow", False)),
        "popular_dishes": json.dumps(
            [t.get("name", "") for t in r.get("tags", []) if t.get("name")],
            ensure_ascii=False,
        ),
        "award_status": str(r.get("awardStatus", 0)),
        "source_url": source_url,
        "is_secret_gem": "false",
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


# ── Main Scraper ───────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "name", "type", "cuisine_tags", "style_tags", "address", "address_en",
    "lat", "lng", "district", "google_rating", "or_rating", "or_score",
    "review_count", "bookmark_count", "price_range", "google_place_id",
    "booking_url", "booking_platform", "opening_hours", "is_open_now",
    "popular_dishes", "award_status", "source_url", "is_secret_gem",
    "last_updated",
]


def _write_csv(venues: list[dict], output_path: str):
    """Write venues to CSV (overwrite)."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(venues)


def _load_existing_ids(output_path: str) -> tuple[set[str], list[dict]]:
    """Load existing venues from CSV for dedup and resumption. Returns (seen_names, existing_venues)."""
    seen_names: set[str] = set()
    existing: list[dict] = []
    if not os.path.exists(output_path):
        return seen_names, existing
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = f"{row.get('name', '').strip()}|{row.get('address', '').strip()}"
                if key not in seen_names:
                    seen_names.add(key)
                    existing.append(row)
        log.info(f"Loaded {len(existing)} existing venues from {output_path}")
    except Exception as e:
        log.warning(f"Could not load existing CSV: {e}")
    return seen_names, existing


def scrape(
    output_path: str,
    max_pages: int = 200,
    cuisine_ids: Optional[list[int]] = None,
    delay: float = REQUEST_DELAY,
    sort_by: str = "DEFAULT",
):
    """Main scraping loop. Writes CSV incrementally after each cuisine batch."""
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    # Load existing data for resumption
    seen_names, all_venues = _load_existing_ids(output_path)

    if cuisine_ids is None:
        # First: scrape default listing (no cuisine filter)
        cuisine_ids = [None] + DEFAULT_CUISINE_IDS
    else:
        cuisine_ids = [None] + cuisine_ids

    for cuisine_id in cuisine_ids:
        cuisine_label = f"cuisine={cuisine_id}" if cuisine_id else "default"
        log.info(f"Scraping: {cuisine_label}")

        empty_streak = 0
        page = 1

        while page <= max_pages:
            try:
                data = fetch_page(session, page=page, cuisine_id=cuisine_id, sort_by=sort_by)
            except RuntimeError as e:
                log.error(f"Stopping {cuisine_label} at page {page}: {e}")
                break

            results = data.get("searchResult", {}).get("paginationResult", {}).get("results", [])
            if not results:
                empty_streak += 1
                if empty_streak >= 3:
                    log.info(f"  No results for 3 consecutive pages. Done with {cuisine_label}.")
                    break
                page += 1
                time.sleep(delay)
                continue

            empty_streak = 0
            new_count = 0
            updated_count = 0

            for r in results:
                venue = parse_venue(r)
                if not venue:
                    continue
                name_key = f"{venue['name'].strip()}|{venue['address'].strip()}"
                if name_key not in seen_names:
                    seen_names.add(name_key)
                    all_venues.append(venue)
                    new_count += 1
                else:
                    # Update existing venue with new fields
                    for existing in all_venues:
                        ekey = f"{existing['name'].strip()}|{existing['address'].strip()}"
                        if ekey == name_key:
                            for field in ("address_en", "district", "or_score", "bookmark_count",
                                          "price_range", "is_open_now", "popular_dishes", "award_status"):
                                if venue.get(field) and not existing.get(field):
                                    existing[field] = venue[field]
                                    updated_count += 1
                            break

            log.info(f"  Page {page}: {len(results)} results, {new_count} new, {updated_count} updated. Total: {len(all_venues)}")

            page += 1
            time.sleep(delay)

        # Incremental save after each cuisine batch
        _write_csv(all_venues, output_path)
        log.info(f"  Saved {len(all_venues)} venues to {output_path}")

    # ── Final CSV ──────────────────────────────────────────────────────────────

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_venues)

    log.info(f"Wrote {len(all_venues)} venues to {output_path}")

    # Print summary stats
    types = {}
    for v in all_venues:
        t = v["type"]
        types[t] = types.get(t, 0) + 1
    log.info(f"By type: {types}")

    return all_venues


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OpenRice Hong Kong Scraper")
    parser.add_argument(
        "--output", "-o",
        default="data/openrice_places.csv",
        help="Output CSV path (default: data/openrice_places.csv)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=200,
        help="Max pages per query/cuisine (default: 200)",
    )
    parser.add_argument(
        "--cuisine-ids",
        type=str,
        default=None,
        help="Comma-separated cuisine IDs to scrape (default: all major cuisines)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY,
        help=f"Delay between requests in seconds (default: {REQUEST_DELAY})",
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        default="DEFAULT",
        help="Sort method: DEFAULT, RATING, REVIEW_COUNT, etc.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    cuisine_ids = None
    if args.cuisine_ids:
        cuisine_ids = [int(x.strip()) for x in args.cuisine_ids.split(",")]

    scrape(
        output_path=args.output,
        max_pages=args.max_pages,
        cuisine_ids=cuisine_ids,
        delay=args.delay,
        sort_by=args.sort_by,
    )


if __name__ == "__main__":
    main()
