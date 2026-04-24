---
name: hk-food-bot
description: HK Food & Drink recommender — natural language food recommendations from 13,689 venues in Hong Kong. Covers restaurants, bars, cafes with Google Maps + OpenRice ratings.
category: leisure
---

# HK Food Bot Skill

Recommend restaurants and bars in Hong Kong from a dataset of 13,654 venues. Use this whenever the user asks about food, restaurants, bars, drinks, dining, or eating in Hong Kong.

## Quick Start

```bash
# Option A: pip install (requires pyproject.toml — created April 2026)
cd ~/workspaces/default/hk-food-bot
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Option B: requirements.txt (legacy)
pip install -r requirements.txt

# Run CLI
python3 scripts/recommend.py --area "Wan Chai" --type eat --cuisine japanese --count 5
```

## CLI Reference

```
python3 ~/workspaces/default/hk-food-bot/scripts/recommend.py \
  --area "AREA" \           # Required: HK area name
  --type eat|drink \        # eat=restaurant, drink=bar
  --cuisine "CUISINE" \     # Cuisine tag, group, or natural language
  --count N \               # Number of results (default 5)
  --surprise \              # Random cuisine surprise mode
  --include-personal \      # Include user's saved places (minion abc)
  --no-time-filter \        # Don't filter by open-now
  --all-areas \             # Search entire HK, not just nearby
  --lat 22.279 --lng 114.175  # Exact coordinates (overrides --area)
```

## Parsing Natural Language → CLI Args

### Area Detection
Extract area from user's message. Known areas:
- HK Island: Central, Wan Chai, Causeway Bay, Admiralty, Sheung Wan, Sai Ying Pun, Kennedy Town, Tin Hau, North Point
- Kowloon: TST, Mong Kok, Jordan, Yau Ma Tei, Prince Edward
- If no area mentioned, default to Central

### Type Detection
- "eat/food/restaurant/dinner/lunch/breakfast/brunch" → `--type eat`
- "drink/bar/drinks/cocktails/wine/beer/night out" → `--type drink`
- If ambiguous, default to eat

### Cuisine Resolution
The `--cuisine` arg accepts multiple formats:

**Direct tags:** japanese, thai, italian, chinese, korean, vietnamese, indian, french, spanish, mexican, american, cantonese, ramen, hotpot, seafood, steakhouse, vegetarian

**Group keywords:** 
- "asian" → chinese, japanese, korean, thai, etc.
- "sea" or "southeast asian" → thai, vietnamese, malaysian, etc.
- "eu" or "european" → italian, french, spanish, etc.
- "western" → italian, french, american, etc.
- "noodles" → japanese, chinese, thai, vietnamese
- "bbq" → korean, japanese, american

**Natural language:**
- "spicy" → thai, sichuan, indian, korean
- "comfort" → cantonese, japanese, hong kong
- "fancy" → french, italian, japanese
- "quick" → japanese, hong kong, korean
- "healthy" → japanese, vegetarian
- "romantic" → french, italian, japanese
- "casual" → hong kong, thai, vietnamese

**Drink types:**
- "cocktails" → cocktail-bar, speakeasy, rooftop-bar
- "wine" → wine-bar
- "beer" → craft-beer, pub

**Abbreviations:** jp=japanese, cn=chinese, kr=korean, th=thai, vn=vietnamese, hk=hong kong

**Surprise mode:** "surprise me", "random", "anything", or `--surprise`

### Include Personal Flag
Use `--include-personal` when:
- User says "my favorites", "places I like", "recommend from my list"
- User explicitly asks for their saved places
- User asks for cocktails/drinks and gets 0 results (all cocktail bars are in personal list)
Do NOT use it by default — the personal list excludes places the user has already been to.

## CLI JSON Output (reference — don't show to user)

The CLI returns JSON. Parse it, then format using the template below. Don't show raw JSON.

## Output Format (MUST follow exactly)

Always format recommendations using this template. No narration — just the structured output.

```
🍽 [Restaurants/Bars/Cafes] in [Area]:

1. [name]
   ⭐ [OR_rating] (OR) · ⭐ [Google_rating] (Google[, N reviews])
   📍 [Open in Google Maps](google_maps_link) [open_status]
   🍜 Cuisine: [cuisine]
   🚶 ~X min walk (Ym) · 🚗 ~X min drive (Ym)
   📫 [address]
   📋 [Booking required](booking_url)  ← when booking_url exists
   📋 No booking required               ← when no booking_url exists
```

**Rules:**
- Both OR and Google ratings on every result — never show just one
- Ratings go on their own line immediately below the name (not inline)
- OR rating first (primary metric), Google second
- Google Maps link + open/closed status on the same 📍 line (no separate 🕐 line)
- **Remove price range entirely** — do not show 💰 or price tier
- **Booking line:** if the venue has a `booking_url` or `booking_platform` field, render `📋 [Booking required](booking_url)` as a clickable markdown link. Otherwise, render plain text `📋 No booking required`
- Google Maps link: `https://www.google.com/maps/search/?api=1&query={url_encode(address + name)}`
- Type header: "Restaurants" for eat, "Bars" for drink, "Cafes" for cafe
- Distance: walk time = distance_m / 80 m/min; drive time = distance_m / 15 m/min (rough)
- If hours / open_status not in JSON data, skip the status (📍 line shows just the link)
- Secret gem: add 💎 next to the name
- Crossover suggestion: add a note below the list like "⚠️ No exact [cuisine] match — showing closest alternatives"

## Taste Profile — Config-Driven (April 2026 Refactor)

Taste profile weights live in `config.yaml` under the `taste_profile` section. Users customize cuisine and style preferences there (0.0-1.0); no code changes are required. `engine/taste.py` loads weights at import time via `_load_taste_profile()`. A `default_weight` key sets the fallback for unknown cuisines (default: 0.2).

Example `config.yaml`:
```yaml
taste_profile:
  italian: 1.0
  chinese: 1.0
  cocktail-bar: 0.95
  japanese: 0.8
  # ... see config.yaml for full list
  default_weight: 0.2
```

## Scoring Logic (for context)
- **Taste score**: max weight across all cuisine tags, with small bonus for multiple matching tags (≥0.5 weight) and preferred style tags (speakeasy, rooftop-bar, fine-dining, hidden-alley, izakaya, lounge)
- Award bonus: Michelin/50 Best/Black Pearl — 50 pts base, recency bonus (1.5x within 5 years)
- Rating bonus: ≥4.5 → +0.20, ≥4.0 → +0.10, ≥3.5 → +0.05
- Secret gem bonus: +0.15
- Bottom 20% by rating filtered out
- Personal exclusion list removes already-visited places (unless --include-personal)
- Closed places filtered out
- Franchise dedup: same-name chains keep closest location (shared normalizer in `utils/name_norm.py`)
- Distance: 1.5km default scope, expanded to 5km for bars (sparse data)
- **Cuisine keyboard sorted by taste weight** (Italian shows first, not random)

## Diagnosing Issues — Pipeline Tracing Method

When the user reports missing results or wrong data, trace the FULL pipeline:

1. **Source data**: Check `data/openrice_places.csv` and `data/merged_places.csv` directly. Count matching rows.
2. **Merge logic**: Run `scripts/merge_data.py` and compare counts. The merge deduplicates by exact name+address (NOT name-only — name-only dedup was the root cause of losing 628 bars).
3. **Type classification**: OpenRice uses CUISINE tags (japanese, western, international), not venue type. A cocktail bar tagged "japanese" won't match `--cuisine cocktail-bar`. Check both cuisine_tags AND style_tags.
4. **Personal exclusions**: `data/exclude_personal.txt` — all 10 well-known cocktail bars are in the user's personal list. Use `--include-personal` to re-include.
5. **Recommender fallback**: For bars, ensure fallback uses `filter_by_any_tag` (checks style_tags), NOT `filter_by_cuisine` (only cuisine_tags).

**Root cause pattern — "why is X missing?":**
- Start from CSV files (ground truth), work backwards through merge → scraper → API
- Check dedup logic (name vs name+address)
- Check tag sources (OpenRice cuisine vs Google Maps cocktail-bar tags)
- Check filter function (filter_by_cuisine vs filter_by_any_tag for bars)

## Time Filter Pitfall — Pre-Dinner False Negatives

**The problem:** At 5:00–6:30 PM, the bot's time filter often excludes restaurants that are actually open for dinner. OpenRice data frequently only lists lunch hours (e.g., "Mo-Su 11:30-15:00") even when the venue serves dinner from 5:30 or 6:00 PM. This causes valid dinner options to disappear from results.

**When it happens:**
- User asks "what should I eat tonight?" between 5:00–6:30 PM
- Restaurants with incomplete OpenRice hours show 🔴 Closed
- The real dinner service starts at 5:30 PM or 6:00 PM

**What to do:**
- Use `--no-time-filter` for dinner queries before 7:00 PM
- Or verify on the restaurant's actual booking page / website before ruling out a "closed" result
- Example: Nocino (Tai Hang) shows "Mo-Su 11:30-15:00" in the bot but serves dinner 5:30–10:30 PM — the OpenRice source data was lunch-only

**Don't blindly trust open_status between 5–7 PM.** It's the most common false-negative window.

## Known Data Gaps & Fallbacks

**Spanish food is very sparse in HK:** Only ~5 tagged venues total (Casa Iberica, Madera, Still, Bunny Churros, Iberico Ham Cellar). Wan Chai has 1 with no ratings. Use `--all-areas` for Spanish queries — the good ones are in Sai Ying Pun (Casa Iberica: Google 4.9).

**If 0 results returned:** Check if it's a personal exclusion issue. The `--include-personal` flag re-includes places the user has saved. If still empty, it's a genuine data gap — tell the user honestly.

**Cocktail bars — personal exclusion trap:** ~10 well-known cocktail bars (001, Bar Leone, Quinary, Dragonfly, GOKAN, Courtroom, Tell Camellia, The Wise King, ZZURA, Pistol Bar) are in the user's personal exclusion list. The remaining 88+ auto-tagged cocktail bars (lounges, speakeasy, etc.) are NOT excluded. If results seem thin, retry with `--include-personal`.

## Data Pipeline & Diagnosis

**Data sources:**
- OpenRice: ~13,639 raw rows → 13,639 unique by name+address dedup. Categories = cuisine (japanese, western, international), NOT venue type. Has style_tags (bar, izakaya, speakeasy, lounge, etc.) that are useful for bar subtypes.
- Google Maps: 15 venues in sample_places.csv. Has cocktail-bar, speakeasy, rooftop-bar tags. Small but high-quality data.
**Google cache**: `data/google_ratings_cache.json` — shared thread-safe singleton via `data/google_cache.py`. All modules (loader.py, secret_gem.py, lazy_resolve.py) use `get_cache()` instead of loading independently. `merge_and_save()` for concurrent writer safety. 12,738+ entries. Cache lookup uses pre-built name index (`utils/name_norm.py → build_name_index()`) for O(1) fallback instead of linear scan — load_places() runs in ~1s (was 7.8s). Parallel batch supervisor (`scripts/batch_parallel_supervisor.py`) runs 2 Camoufox workers with isolated caches. `scripts/refresh_data.py` provides automated data refresh pipeline (scrape + merge, designed for cron).
- Merge: `scripts/merge_data.py` — name+address dedup (NOT name-only). Uses shared `normalize_name()` from `utils/name_norm.py` for cache enrichment.

**Merge pipeline (`scripts/merge_data.py`):**
1. Load OpenRice → dedup by exact name+address (keeps all locations of same franchise)
2. Load Google Maps → overwrite OR entries with same key, add new ones
3. Enrich with Google ratings cache (exact name|addr match, then name-index fallback via `build_name_index()`)
4. For bars: merge drink-specific style tags (speakeasy, lounge, rooftop-bar, etc.) into cuisine_tags
5. For bars: name-based cocktail bar detection heuristic (names containing "cocktail", "lounge", "speakeasy", spirit names)
6. Sanitize coordinates (some OR rows have address text in lat field)
7. Sanitize is_secret_gem field (OpenRice sometimes returns URLs instead of booleans)
8. Output: ~13,689 venues, ~1,670 bars, ~98 cocktail-tagged bars

**Tag parsing fix (April 2026):** `normalize_tags()` now parses JSON arrays, strips backslash-escaped quotes (`\"casual\"` → `casual`), lowercases, and deduplicates. Previously 15 high-profile venues (Bo Innovation, Carbone, Yardbird, The Old Man, Penicillin, etc.) had corrupted tags.

**Cocktail bar detection — why it's hard:**
- OpenRice doesn't have "cocktail-bar" as a category — uses cuisine (japanese, western, etc.)
- OpenRice style_tags are sparse: only ~2 speakeasy, ~1 lounge, ~1 rooftop-bar out of 1,663 bars
- Fix: name-based heuristic + style tag merge. Bars with "cocktail", "lounge", "speakeasy" in name get auto-tagged.
- Result: 4 → 98 cocktail-tagged bars

**OpenRice scraper — PATCHED (April 15, 2026):**
Scraper now extracts: district, address_en, price_range, bookmark_count, or_score, is_open_now, popular_dishes, award_status. CSV_COLUMNS, parse_venue(), Place dataclass, merge script, and recommend.py all updated.

**Enrichment complete:** `scripts/enrich_full.py` ran through all cuisine IDs, backfilling new fields on 9,901 venues (99% coverage). district, price_range, bookmark_count, address_en populated. Run `python scripts/enrich_full.py` to re-enrich.

**Diagnosing \"0 results\" — trace the pipeline:**
1. Check source data: `data/openrice_places.csv` and `data/merged_places.csv` — are there venues matching the query?
2. Check if venues are bars vs restaurants: OpenRice classifies by cuisine, not venue type. A cocktail bar tagged "japanese" won't match `--cuisine cocktail-bar`.
3. Check personal exclusions: `data/exclude_personal.txt` — user's saved places get filtered out by default.
4. Check Google cache: `data/google_ratings_cache.json` — cache key is `name|address`, with name-index fallback in loader.py (pre-built via `utils/name_norm.build_name_index()`).
5. Rebuild merged data: `python scripts/merge_data.py` — regenerates `merged_places.csv` from sources.
6. Check for tag corruption: OpenRice API sometimes returns escaped quotes. `normalize_tags()` in merge_data.py cleans these — if tags look like `\"casual\"` or have backslashes, the merge script needs re-running.

## Shared Name Normalizer — `utils/name_norm.py`

Central utility for franchise deduplication and cache lookups. Replaces two inconsistent `_normalize_name()` implementations that were in `recommender.py` (stripped parens only) and `awards.py` (stripped all non-alphanumeric including Chinese chars).

**`normalize_name(name)`** handles:
- Parenthesized suffixes: `麥當勞 (銅鑼灣)` → `麥當勞`
- Dash-separated locations: `Café de Coral - TST` → `cafe de coral`
- Unicode accent decomposition: `naïve` → `naive`
- Chinese character preservation (never stripped)
- Case folding + space collapse

**`build_name_index(cache)`** builds a `normalized_name → [(key, entry)]` dict from the Google cache. Sorted by review count descending (most-reviewed branch = most reliable fallback). Used by `loader.py` and `merge_data.py` for O(1) cache fallback (was O(N×M) linear scan).

**`build_franchise_groups(places)`** groups a list of Place objects by normalized name. Useful for franchise density analysis.

**Pitfall — `scripts/merge_data.py` sys.path:** The merge script runs standalone. `utils/` imports require adding the project root to `sys.path` at the module level (not inside `main()`). Current code has this fix. If you refactor imports, don't move the path fix inside a function.

## Test Suite

Run the full suite: `python -m pytest tests/ -q` (220+ tests, ~15s).

`tests/test_integration.py` has 85 integration tests covering: name normalization, franchise dedup, pre-built index, full pipeline with real data (all 10 areas × restaurant/bar/surprise), taste scoring, exclusions, price filtering, formatting, time filtering, merge output validation, and edge cases. Uses the actual `merged_places.csv` (skips if missing).

## Google Maps Batch Caching — Architecture

**Parallel supervisor** (`scripts/batch_parallel_supervisor.py`):
- Splits uncached venues into 2 balanced groups by district
- Spawns 2 workers in parallel with isolated cache files (avoids JSON write races)
- Auto-restarts on crash/hang: 5 retries, 5-min stall timeout, 10-sec restart delay
- Merges worker caches into main `google_ratings_cache.json` on completion
- Status saved to `data/batch_status.json`

**Worker recycling** (`scripts/batch_cache_area.py`):
- Camoufox (anti-detect browser) crashes after ~100 venues due to memory leak
- Solution: recycle browser every 50 venues — close, GC, reopen fresh
- `RECYCLE_INTERVAL = 50` — adjustable
- Also handles mid-batch browser death gracefully (recycles on "browser has been closed" error)
- `CACHE_FILE_OVERRIDE` env var allows isolated cache per worker

**Watchdog cron** (`hk-food-bot-google-watchdog`): runs every 15 min, checks if supervisor/workers are alive, restarts if crashed.

**Diagnosing remaining uncached venues:**
- CSV files (`data/_uncached_*.csv`) have separate `name` and `address` columns — NOT a combined `name|address` column
- Cache keys use `name|address` format (pipe-separated): `f"{row['name']}|{row['address']}"`
- When checking remaining count, construct the composite key: `f"{r['name']}|{r['address']}"`
- If supervisor logs "All done. Success: True" with `+0 cached`, all venues were attempted. Remaining uncached entries are permanently unresolvable (no Google Maps match, closed, or name mismatch). This is normal — not a crash.
- Typical unresolvable count: ~20 venues out of 13,689. Don't restart the supervisor for this.

**Rate**: ~18 resolved venues/min per worker, ~84% success rate (rest are TimeoutError on unresolvable venues).

**Recommender fallback bug (FIXED):**
- For bars, the fallback (`get_similar_cuisines` and `get_crossover_cuisine`) used `filter_by_cuisine` which only checks cuisine_tags
- Fixed to use `filter_by_any_tag` for bars — checks both cuisine_tags and style_tags
- Without this fix, searching for "cocktail-bar" wouldn't find bars tagged "speakeasy" or "lounge" in style_tags

**When to use `--include-personal`:**
- Cocktail/wine queries that return 0 results (user's 10 favorite cocktail bars are in personal list)
- User explicitly asks for their favorites
- DON'T use by default — personal list = already visited

## Data
- 13,689 venues total (OpenRice 13,674 + Google Maps 15, after name+address dedup)
- 1,670 bars, 12,019 restaurants
- 98 cocktail-tagged bars (auto-detected from names + style tags)
- Enrichment coverage: district 99.3%, price_range 99.7%, bookmark_count 99.4%, address_en 98.8%, or_score 83.2%, opening_hours 88.3%, popular_dishes 15.8%, booking_url/platform ~20%
- Google ratings: 12,738+ in shared cache (`data/google_cache.py` — thread-safe singleton)
- Awards data: Michelin, Black Pearl, etc. (dynamic year — uses `datetime.now().year`)
- Merge script: `scripts/merge_data.py` — run to rebuild from sources
- Data refresh: `scripts/refresh_data.py` — automated scrape + merge pipeline (cron-friendly)
- Full enrichment: `scripts/enrich_full.py` — queries all cuisine IDs, updates existing venues (~25 min)
- Known data gaps: style_tags 77.8% missing (OR limitation), award_status 0% (not scraped), popular_dishes 15.8%
- **Price filtering**: available in pipeline — users can filter by $, $$, $$$, $$$$
- **Opening hours**: supports multi-period schedules (lunch + dinner: "Mo-Su 12:00-14:30, 18:00-22:00")
- **Startup health check**: bot validates CSV exists and loads data before accepting requests
