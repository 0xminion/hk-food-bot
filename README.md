# HK Food & Drinks Bot

A Telegram bot that recommends restaurants and bars in Hong Kong based on your personal taste profile, derived from your Google Maps saved list analysis.

## Features

- `/eat?` — Restaurant recommendations by area and cuisine
- `/drink?` — Bar recommendations by area and drink type
- Area-based filtering (10 HK districts: Central, Wan Chai, TST, etc.)
- Taste profile scoring (weights recommendations toward your favorites)
- Crossover engine (suggests related cuisines you haven't tried)
- Time-aware filtering (only shows currently open places)
- Secret gem detection (high-quality places with low exposure)
- Haversine distance calculation (walking/driving estimates)
- Booking deep links (Chope, OpenTable integration)

## Your Taste Profile

The bot is pre-loaded with your taste profile from your Google Maps "minion abc" list:

| Cuisine | Weight | Saved Places |
|---------|--------|-------------|
| Italian | 1.00 | 13 |
| Chinese | 1.00 | 13 |
| Cocktail Bars | 0.95 | 10 |
| Japanese | 0.80 | 8 |
| Cantonese | 0.85 | 6 |
| Thai | 0.75 | 6 |
| Spanish | 0.70 | 5 |
| Western | 0.65 | 5 |
| Ramen | 0.65 | 5 |
| Hotpot | 0.55 | 4 |

## Setup

### 1. Get a Telegram Bot Token

Talk to [@BotFather](https://t.me/BotFather) on Telegram. Create a new bot and copy the API token.

### 2. Configure

Edit `config.yaml` and replace `YOUR_BOT_TOKEN_HERE` with your actual token:

```yaml
telegram:
  token: "123456:ABC-DEF..."
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run

```bash
python bot.py
```

You should see `Starting HK Food Bot...` in the terminal.

### 5. Test

Open your bot in Telegram and send `/start`, then try `/eat?` or `/drink?`.

## Architecture

```
hk-food-bot/
├── bot.py                 # Main entry point (Telegram polling loop)
├── config.yaml            # Bot token + settings
├── requirements.txt       # Python dependencies
├── README.md
├── data/
│   ├── __init__.py
│   ├── loader.py          # CSV loading, filtering, parsing
│   ├── merged_places.csv  # 10,790 merged venues (164 Google Maps + 10,626 OpenRice)
│   └── openrice_places.csv
├── engine/
│   ├── __init__.py
│   ├── taste.py           # Taste profile scorer (user preference weighting)
│   ├── crossover.py       # Crossover recommendation engine (flavor similarity)
│   ├── time_aware.py      # Opening hours filter (time-aware)
│   ├── secret_gem.py      # Secret gem detection (curation rules)
│   └── recommender.py     # Main recommendation orchestrator (pipeline)
├── handlers/
│   ├── __init__.py
│   ├── eat.py             # /eat? handler (restaurant flow)
│   ├── drink.py           # /drink? handler (bar flow)
│   └── common.py          # Shared formatting, keyboards, area definitions
├── utils/
│   ├── __init__.py
│   └── haversine.py       # Distance calculation (Haversine formula)
├── tests/
│   ├── __init__.py
│   ├── conftest.py        # Shared test fixtures
│   ├── test_haversine.py  # Distance calculation tests
│   ├── test_loader.py     # CSV loading tests
│   ├── test_taste.py      # Taste scoring tests
│   ├── test_crossover.py  # Crossover engine tests
│   ├── test_time_aware.py # Time filtering tests
│   ├── test_secret_gem.py # Gem detection tests
│   ├── test_recommender.py# Recommendation pipeline tests
│   ├── test_handlers.py   # Handler formatting tests
│   └── test_system.py     # End-to-end integration tests
└── scrapers/
    └── openrice.py        # OpenRice scraper (data enrichment)
```

## Recommendation Pipeline

The bot follows this pipeline for each `/eat?` or `/drink?` request:

1. **Type filter** — Filter by restaurant or bar
2. **Distance computation** — Haversine distance from user's selected area
3. **Proximity filter** — Within ~5km radius
4. **Time filter** — Only currently open places (configurable)
5. **Secret gem enrichment** — Apply curation rules to flag hidden gems
6. **Cuisine filter** — Match selected cuisine (or serendipitous mode)
7. **Taste scoring** — Weight by user's taste profile
8. **Ranking** — Sort by score, return top 5

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
| A | Rating ≥ 4.3 AND reviews < 200 |
| C | Rating ≥ 4.0 AND reviews < 100 AND has hidden-alley/street-food style |
| E | Reviews ≤ 50 AND rating ≥ 4.2 |

Disqualifying factors:
- > 1,000 reviews (already mainstream)
- Located in a major mall (IFC, Harbour City, Times Square, etc.)

## Data

The `merged_places.csv` contains 10,790 venues:
- 164 from your Google Maps "minion abc" list
- 10,626 from OpenRice (HK's primary local food platform)

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
| review_count | int | Number of reviews |
| booking_url | string | Booking deep link |
| opening_hours | string | Structured hours |
| is_secret_gem | bool | Hidden gem flag |

## Testing

Run the full test suite:

```bash
python -m pytest tests/ -v
```

Test coverage:
- Unit tests: data loading, taste scoring, crossover, time filtering, gem detection
- Integration tests: full recommendation pipeline, handler formatting
- System tests: end-to-end flow simulation

## Configuration

`config.yaml` options:

```yaml
telegram:
  token: "YOUR_BOT_TOKEN_HERE"
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
```

## Dependencies

- `python-telegram-bot[ext]` >= 21.0 (async Telegram bot framework)
- `PyYAML` >= 6.0 (config parsing)
- `pytest` (testing)

## Roadmap

- [ ] Live location support (GPS-based "near me")
- [ ] Booking API integration (direct reservation)
- [ ] User preference learning across sessions
- [ ] Automated weekly data refresh pipeline
- [ ] Multi-city support
- [ ] Web mini-app
