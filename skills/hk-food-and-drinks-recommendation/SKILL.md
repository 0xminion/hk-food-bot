---
name: hk-food-and-drinks-recommendation
description: Structured output format for HK Food Bot restaurant and bar recommendations.
---

# HK Food Bot — Recommendation Output Format

## When to use

Use this format whenever giving restaurant or bar recommendations for Hong Kong. If the HK Food Bot codebase is available at `~/workspaces/default/hk-food-bot/`, run the recommender engine to get real data. Otherwise, follow the format with available information.

## Output Structure

```
🍽 Restaurants in {Area}:
(or 🍸 Bars around {Area}:)

{Optional note about data availability}

1. {Name} ⭐ {OR_rating} (OR) · ⭐ {Google_rating} (Google, {review_count} reviews)
   [📍 Open in Google Maps]({maps_url})
   {💎 Secret gem!}
   {⭐⭐⭐ Michelin / 🏆 Asia's 50 Best}
   🍜 Cuisine: {comma-separated tags}
   {🟢 Open now / 🔴 Closed / ⏰ {hours}}
   🚶 ~{walk_min} min walk ({walk_m}m) · 🚗 ~{drive_min} min drive ({drive_m}m)
   📫 {full address}
   {[🎟 Book here]({booking_url}) / 🎟 Walk-in, no booking needed}
   {💵 {$ | $$ | $$$ | $$$$}}

2. ...

Want me to try a specific {cuisine/drink type} — {suggestion1}, {suggestion2}, {suggestion3}?
```

## Formatting Rules

### Ratings
- Show OpenRice rating first: `⭐ {rating} (OR)`
- Show Google rating second with review count: `⭐ {rating} (Google, {N} reviews)`
- Separate with ` · `
- If only one source available, show that one only
- Round to 2 decimal places for OR, 1 for Google

### Distance
- Always show walk time first, drive time second
- Format: `🚶 ~{N} min walk ({m}m) · 🚗 ~{N} min drive ({m}m)`
- Walk speed: 12 min/km, Drive speed: 2.4 min/km (25 km/h avg HK)
- Minimum 1 minute

### Open Status
- `🟢 Open now` — currently open
- `🔴 Closed` — currently closed
- `⚪ Hours unknown` — no data
- Place open status line after cuisine/style tags

### Secret Gems
- Show `💎 Secret gem!` line after the Maps link
- Only show if `is_secret_gem` is True

### Awards
- Show award badges on a single line after secret gem
- Format: `⭐⭐⭐ Michelin` or `🏆 Asia's 50 Best`
- Multiple badges space-separated on same line

### Cuisine/Style
- Restaurants: `🍜 Cuisine: {comma-separated tags}`
- Bars: use same format, or `🍸 Style: {tags}` if showing style_tags

### Price Range
- Show if available: `💵 {$ | $$ | $$$ | $$$$}` or `💵 {OpenRice price text}`

### Booking
- If booking_url exists: `[🎟 Book here]({booking_url})` (markdown link)
- If no booking: `🎟 Walk-in, no booking needed`

### Address
- Always show: `📫 {full address}`
- Include Chinese characters as-is

### Google Maps Link
- Always show as markdown embed: `[📍 Open in Google Maps]({maps_url})`
- Prefer `source_url` if it's a maps.app.goo.gl link
- Fallback: construct from name + address as `https://www.google.com/maps/search/?api=1&query={encoded_name+address}`

## Header
- Use `🍽` for restaurants, `🍸` for bars
- Format: `{emoji} {type} in {area}:` or `{emoji} {type} around {area}:`
- Add note in italics if area has sparse results

## Footer
- If crossover was used: `🔄 Expanded search with {cuisine} options`
- If < 5 results: `⚠️ Only {N} matches found — try another area or cuisine`
- End with a question offering to drill into specific cuisines

## Using the Recommender Engine

When the HK Food Bot codebase is available, run recommendations programmatically:

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / "workspaces" / "default" / "hk-food-bot"))

from data.loader import load_places
from engine.recommender import recommend
from handlers.common import HK_AREAS

places = load_places(
    Path.home() / "workspaces" / "default" / "hk-food-bot" / "data" / "merged_places.csv"
)

result = recommend(
    all_places=places,
    place_type="restaurant",  # or "bar"
    area_lat=lat,
    area_lng=lng,
    cuisine=cuisine_or_none,
    area_name=area_name,
    num_results=5,
    use_time_filter=True,  # only if checking current time
    price_filter=price_or_none,
)
```

Then format each place following the structure above.

## Example Output

```
🍽 Restaurants in Wan Chai:

1. Abbraccio ⭐ 4.5 (OR) · ⭐ 4.6 (Google, 320 reviews)
   [📍 Open in Google Maps](https://maps.app.goo.gl/abc123)
   💎 Secret gem!
   🍜 Cuisine: italian
   🟢 Open now
   🚶 ~17 min walk (1.4km) · 🚗 ~8 min drive (1.2km)
   📫 雲咸街75-77號嘉兆商業大廈5樓
   🎟 Walk-in, no booking needed

2. Bo Innovation ⭐ 4.5 (OR) · ⭐ 4.5 (Google, 890 reviews)
   [📍 Open in Google Maps](https://www.google.com/maps/search/?api=1&query=Bo+Innovation+Ship+Street+Wan+Chai)
   ⭐⭐ Michelin
   🍜 Cuisine: chinese, fine-dining
   🟢 Open now
   🚶 ~2 min walk (200m) · 🚗 ~1 min drive (200m)
   📫 Shop A, UG/F, Block 8, Ship Street, Wan Chai
   [🎟 Book here](https://chope.com/bo-innovation)

Want me to try a specific cuisine — Italian, Japanese, Thai?
```

---

## Opinion Layer — Curated Picks

After listing the raw recommendations, always add a curated picks section. Use your judgment to categorize each place — don't just sort by distance or rating, actually think about what makes each spot interesting.

### Format (Bars)

```
🎯 My picks tonight:

🏠 Closest: {Name} — {one-line why, e.g. "5 min walk, solid old-fashioneds, low-key vibe"}
🍸 Best cocktail: {Name} — {one-line why, e.g. "their bartender won Asia's 50 Best, the negroni is lethal"}
🎲 Adventurous: {Name} — {one-line why, e.g. "hidden speakeasy behind a laundromat, you won't find it on Google"}
🃏 Wildcard: {Name} — {one-line why, e.g. "honestly never been but the reviews are unhinged in a good way"}

💭 Honest take: {2-3 sentences. Real opinion. What you'd actually do tonight. Be blunt.}
```

### Format (Restaurants)

```
🎯 My picks tonight:

🏠 Closest: {Name} — {one-line why}
🔥 Best overall: {Name} — {one-line why, e.g. "Michelin star, the char siu is unreal, worth the walk"}
🎲 Adventurous: {Name} — {one-line why, e.g. "hole-in-the-wall with 3 tables, the mapo tofu will change your life"}
🃏 Wildcard: {Name} — {one-line why, e.g. "opened last month, zero reviews but the chef came from Lung King Heen"}

💭 Honest take: {same as bars}
```

### Rules for each pick

**Bars:**
- **🏠 Closest** — Nearest walkable option. Not a cop-out pick — must still be decent. If the closest place sucks, say "closest but skip it" and pick the closest *good* one instead.
- **🍸 Best cocktail** — Highest confidence for drink quality. Weight: cocktail-bar tag, style_tags, bookmark count, review quality signals. Not just highest rating — a 4.5 with 200 reviews where people mention drinks beats a 4.7 with 6 generic reviews.
- **🎲 Adventurous** — Something off the beaten path. Hidden gems, weird locations (rooftops, basements, behind unmarked doors), niche vibes, places most people haven't tried. Secret gems get priority here.
- **🃏 Wildcard** — The "fuck it, why not" pick. Could be polarizing, could be amazing. High variance. A place with split reviews, a weird concept, or something you just have a gut feeling about.

**Restaurants:**
- **🏠 Closest** — Same logic as bars. Nearest *good* food, not just nearest.
- **🔥 Best overall** — Best food quality signal. Weight: Michelin/awards, OR rating with high bookmark count, popular dishes that stand out, cuisine mastery (a Thai place with 4.8 beats a generic fusion with 4.9).
- **🎲 Adventurous** — Hole-in-the-walls, places with 3 tables, a cuisine you'd never think to try, or a dish that sounds insane but works. Unusual locations, non-obvious entrances, places locals know but tourists miss.
- **🃏 Wildcard** — New openings with no reputation, weird menu concepts, polarizing reviews ("either love it or hate it"), or a chef with an interesting pedigree at an unproven venue.

### Honest take guidelines

- Write like you're texting a friend, not writing a review
- If you've never been, say so — but still give an opinion based on signals
- Contrarian takes are welcome ("everyone hypes X but Y is better")
- End with a clear recommendation: "I'd go to {Name}" or "honestly just hit {Name} and call it a night"
- If the data is weak (few reviews, no hours, sparse info), call it out — don't pretend confidence you don't have
