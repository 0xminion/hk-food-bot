# HK Food & Drinks Bot

A Telegram bot that recommends restaurants and bars in Hong Kong based on your personal taste profile, derived from your Google Maps saved list analysis.

## Features

- `/eat?` — Restaurant recommendations by area, budget, and cuisine
- `/drink?` — Bar recommendations by area, budget, and drink type
- **Budget filtering** — filter by price range ($, $$, $$$, $$$$)
- **Taste profile scoring** — weights recommendations toward your favorites
- Area-based filtering (10 HK districts: Central, Wan Chai, TST, etc.)
- Crossover engine (suggests related cuisines you haven't tried)
- Time-aware filtering (only shows currently open places, including multi-period hours)
- Secret gem detection (high-quality places with low exposure)
- Style tag bonuses (speakeasy, rooftop, fine-dining, etc.)
- Haversine distance calculation (walking/driving estimates)
- Booking deep links (Chope, OpenRice integration)
- Startup health check (validates data on launch)

## Your Taste Profile

The bot uses a configurable taste profile to personalize recommendations. Cuisines and bar styles are weighted from `0.0` to `1.0` — higher values mean the bot will prioritize those places. Edit `config.yaml` under the `taste_profile` section to match your own preferences; no code changes are required.

## Setup

### 1. Get a Telegram Bot Token

Talk to @BotFather on Telegram. Create a new bot and copy the API token.

### 2. Clone the repo and create a virtual environment

```bash
git clone https://github.com/0xminion/hk-food-bot.git
cd hk-food-bot
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```

If you prefer `requirements.txt`:

```bash
pip install -r requirements.txt
```

### 3. Create your local secrets file

Create a file named `.env` in the repo root:

```bash
TELEGRAM_BOT_TOKEN=***
TELEGRAM_USER_ID=your_telegram_user_id
```

Important:
- `.env` is for secrets only
- do not commit it
- this repo already ignores `.env`

### 4. Configure bot behavior

Edit `config.yaml` for non-secret settings:

```yaml
telegram:
  parse_mode: "HTML"

data:
  places_csv: "data/merged_places.csv"

defaults:
  search_radius_m: 5000
  num_recommendations: 5
  num_cuisine_suggestions: 5

time_filter:
  enabled: true
  timezone: "Asia/Hong_Kong"

# Personalize your recommendation weights
taste_profile:
  italian: 1.0
  japanese: 0.8
  # ... add or remove cuisines as you like
```

### 5. Run

```bash
python bot.py
```

You should see `Health check passed: N places loaded` then `Starting HK Food Bot...`.

### 6. Test

Open your bot in Telegram and send `/start`, then try `/eat?` or `/drink?`.

## Architecture

```
hk-food-bot/
├── bot.py                     # Main entry point (Telegram polling loop, startup health check)
├── config.yaml                # Bot settings
├── requirements.txt           # Python dependencies
├── README.md
├── data/
│   ├── __init__.py
│   ├── loader.py              # CSV loading, filtering, parsing
│   ├── google_cache.py        # Shared Google ratings cache (thread-safe singleton)
│   └── merged_places.csv      # ~13k merged venues (OpenRice + Google Maps)
├── engine/
│   ├── __init__.py
│   ├── recommender.py         # Main recommendation orchestrator (pipeline)
│   ├── taste.py               # Taste profile scorer (cuisine + style tag weighting)
│   ├── crossover.py           # Crossover recommendation engine (flavor similarity)
│   ├── time_aware.py          # Opening hours filter (multi-period support)
│   ├── secret_gem.py          # Secret gem detection (source-aware thresholds)
│   ├── awards.py              # Awards and ranking data (Michelin, 50 Best, etc.)
│   ├── cuisine_groups.py      # Regional cuisine group resolution
│   └── lazy_resolve.py        # Background Google rating resolution (thread-safe)
├── handlers/
│   ├── __init__.py
│   ├── eat.py                 # /eat? handler (restaurant flow)
│   ├── drink.py               # /drink? handler (bar flow)
│   └── common.py              # Shared formatting, keyboards, price filtering
├── utils/
│   ├── __init__.py
│   └── haversine.py           # Distance calculation (Haversine formula)
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # Shared test fixtures
│   ├── test_haversine.py      # Distance calculation tests
│   ├── test_loader.py         # CSV loading tests
│   ├── test_taste.py          # Taste scoring tests
│   ├── test_crossover.py      # Crossover engine tests
│   ├── test_time_aware.py     # Time filtering tests
│   ├── test_secret_gem.py     # Gem detection tests
│   ├── test_recommender.py    # Recommendation pipeline tests
│   ├── test_handlers.py       # Handler formatting tests
│   ├── test_google_resolver.py# Cache + lazy resolve tests
│   └── test_system.py         # End-to-end integration tests
├── scrapers/
│   ├── openrice.py            # OpenRice scraper (API-based)
│   └── google_resolver.py     # Google Maps rating resolver
└── scripts/
    ├── merge_data.py          # Merge OpenRice + Google Maps data
    ├── refresh_data.py        # Automated data refresh pipeline
    └── batch_*.py             # Batch Google Maps scraping scripts
```

> **Note:** The `scripts/` directory contains ad-hoc data maintenance tools (scrapers, migration helpers, batch resolvers). You only need them if you are refreshing or rebuilding the venue dataset; they are not required to run the bot.

## Recommendation Pipeline

The bot follows this pipeline for each `/eat?` or `/drink?` request:

1. **Type filter** — Filter by restaurant or bar
2. **Distance computation** — Haversine distance from user's selected area
3. **Proximity filter** — Within ~1.5km (area scope) or 5km (bars)
4. **Price filter** — Match selected budget range ($, $$, $$$, $$$$)
5. **Time filter** — Only currently open places (multi-period aware)
6. **Cuisine filter** — Match selected cuisine (with similarity fallback)
7. **Taste scoring** — Weight by user's taste profile + style tag bonuses
8. **Franchise dedup** — Keep closest branch of same-name chains
9. **Bottom percentile filter** — Remove bottom 20% by rating
10. **Ranking** — Sort by total score (taste + gem + award + rating)

## Budget Filtering

After selecting an area, the bot asks for budget preference:

- **Any budget** — no filtering
- **💰 Cheap eats** — `$`
- **💰💰 Mid-range** — `$$`
- **💰💰💰 Upscale** — `$$$`
- **💰💰💰💰 Fine dining** — `$$$$`

Places without price data are always included regardless of filter.

## Crossover Engine

The crossover engine suggests related cuisines based on flavor-profile similarity:

- Thai → Vietnamese, Malay, Lao
- Italian → Spanish, French, Greek
- Cocktail Bar → Speakeasy, Wine Bar, Lounge
- Japanese → Korean, Chinese

If you pick "Thai" but there aren't enough Thai places nearby, the bot automatically includes top Vietnamese options.

## Serendipitous Mode ("Surprise Me!")

NOT random. The bot:
1. Identifies cuisines you haven't tried
2. Cross-references with flavor profiles similar to your favorites
3. Picks from the untried category with the highest predicted match

## Secret Gem Rules

A place is flagged as a secret gem if:

| Rule | Criteria |
|------|----------|
| A | Rating ≥ 4.3 AND reviews < 200 (OR) / < 1000 (Google) |
| C | Rating ≥ 4.0 AND very low reviews + hidden-alley/street-food style |
| E | Reviews ≤ 50 (OR) / ≤ 300 (Google) AND rating ≥ 4.2 |

Disqualifying factors:
- Located in a major mall (IFC, Harbour City, Times Square, etc.)
- Very high reviews (mainstream)

Source-aware thresholds: Google ratings skew higher and have 10-20x more reviews than OpenRice, so different thresholds apply.

## Data

The `merged_places.csv` contains ~13k venues:
- OpenRice venues (HK's primary local food platform)
- Google Maps saved places

### CSV Schema

| Field | Type | Description |
|-------|------|-------------|
| name | string | Restaurant/bar name |
| type | enum | `restaurant` or `bar` |
| cuisine_tags | list | e.g., `[thai, noodles]` |
| style_tags | list | e.g., `[fine-dining, rooftop]` |
| address | string | Full address |
| lat/lng | float | Coordinates |
| google_rating | float | 1.0-5.0 |
| or_rating | float | OpenRice rating |
| review_count | int | Number of reviews |
| price_range | string | e.g., `$`, `$$`, `$$$` |
| booking_url | string | Booking deep link |
| opening_hours | string | Structured hours (multi-period) |
| is_secret_gem | bool | Hidden gem flag |

## Data Refresh

Automated data refresh pipeline:

```bash
# Full pipeline (scrape + merge)
python scripts/refresh_data.py

# Merge only (skip scraping)
python scripts/refresh_data.py --merge-only

# Dry run
python scripts/refresh_data.py --dry-run
```

Designed for cron: `0 3 * * 0` (Sunday 3am).

## Testing

Run the full test suite:

```bash
python -m pytest tests/ -v
```

## Configuration

`config.yaml` options:

```yaml
telegram:
  parse_mode: "HTML"

data:
  places_csv: "data/merged_places.csv"

defaults:
  search_radius_m: 5000
  num_recommendations: 5
  num_cuisine_suggestions: 5

time_filter:
  enabled: true
  timezone: "Asia/Hong_Kong"

# Personalize recommendation weights (0.0 - 1.0)
taste_profile:
  italian: 1.0
  japanese: 0.8
  thai: 0.75
  # ... see config.yaml for the full list
```

## Dependencies

Core runtime dependencies (see `pyproject.toml`):

- `python-telegram-bot[ext]` >= 21.0 (async Telegram bot framework)
- `PyYAML` >= 6.0 (config parsing)

Development / testing:

- `pytest` >= 7.0
- `pytest-asyncio` >= 0.21

Install everything including dev dependencies:

```bash
pip install -e ".[dev]"
```

Or use the classic `requirements.txt` if you prefer:

```bash
pip install -r requirements.txt
```

## Roadmap

- [ ] Live location support (GPS-based "near me")
- [ ] Booking API integration (direct reservation)
- [ ] User preference learning across sessions
- [ ] Multi-city support
- [ ] Web mini-app
