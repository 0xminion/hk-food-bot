"""
Conversational handler for natural-language food/bar recommendations.

New entry point: /find (no state machine).
Parses free-form queries with LLM, runs the pipeline with semantic boost,
generates per-venue rationales.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import requests
import yaml
from telegram import Update
from telegram.ext import ContextTypes

from data.loader import load_places
from engine.recommender import recommend, RecommendationResult
from handlers.common import format_recommendations_message, HK_AREAS
from utils.haversine import haversine_distance, compute_walk_distance

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# ParsedQuery model
# -----------------------------------------------------------------------
@dataclass
class ParsedQuery:
    area: str | None
    place_type: str | None  # "restaurant" | "bar"
    cuisine: list[str]
    budget: str | None      # "$"-$"$$$$"
    constraints: list[str]   # e.g. ["open_now", "not_visited"]
    vibe: str | None
    time_context: str | None
    surprise: bool


# -----------------------------------------------------------------------
# LLM client helper
# -----------------------------------------------------------------------
class _OllamaClient:
    def __init__(self, url: str, model: str, max_tokens: int = 512, temperature: float = 0.3):
        # Ollama URL may already include /api/generate or be just the base
        base = url.rstrip("/")
        if base.endswith("/api/generate"):
            self.url = base
        else:
            self.url = base + "/api/generate"
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def generate(self, prompt: str, system: str | None = None) -> str:
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": self.max_tokens,
                "temperature": self.temperature,
            },
        }
        if system:
            body["system"] = system
        try:
            resp = requests.post(self.url, json=body, timeout=120)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception:
            logger.error("Ollama generation failed", exc_info=True)
            return ""


def _get_llm_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("conversational", {})


# -----------------------------------------------------------------------
# Query parser
# -----------------------------------------------------------------------
_QUERY_PARSER_SYSTEM = """You parse free-text restaurant/bar queries into structured JSON.
You must ONLY output valid JSON with no markdown formatting, no code blocks, no explanations.

Output JSON keys:
- area (string or null): Hong Kong area name
- place_type ("restaurant" or "bar" or null)
- cuisine (list of strings): specific cuisine/style tags
- budget ("$" | "$$" | "$$$" | "$$$$" or null)
- constraints (list of strings): e.g. ["open_now", "not_visited", "walking_distance", "hidden_gem"]
- vibe ("casual" | "fancy" | "romantic" | "quick" | "group" or null)
- time_context ("lunch" | "dinner" | "brunch" | "late_night" or null)
- surprise (boolean): true if user wants something unexpected

If anything is ambiguous, use null. Be generous with cuisine extraction."""

_QUERY_PARSER_TEMPLATE = """Parse this request into JSON: "{query}"

Available areas: {areas}"""


def parse_query(query: str, llm: _OllamaClient) -> ParsedQuery:
    """Call LLM to parse a natural language request."""
    prompt = _QUERY_PARSER_TEMPLATE.format(
        query=query,
        areas=", ".join(sorted(HK_AREAS.keys())),
    )
    raw = llm.generate(prompt, system=_QUERY_PARSER_SYSTEM)
    # Extract JSON from response (may have extra text)
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        data = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        # Fallback: deterministic extraction
        data = _fallback_parse(query)

    return ParsedQuery(
        area=data.get("area"),
        place_type=data.get("place_type"),
        cuisine=data.get("cuisine") or [],
        budget=data.get("budget"),
        constraints=data.get("constraints") or [],
        vibe=data.get("vibe"),
        time_context=data.get("time_context"),
        surprise=bool(data.get("surprise", False)),
    )


def _fallback_parse(query: str) -> dict:
    """Deterministic fallback when LLM fails."""
    q = query.lower()
    data: dict = {"area": None, "place_type": None, "cuisine": [], "budget": None,
                  "constraints": [], "vibe": None, "time_context": None, "surprise": False}

    # Area detection
    for name in HK_AREAS:
        if name.lower() in q:
            data["area"] = name
            break

    # Type detection
    if any(w in q for w in ("bar", "cocktail", "drink", "wine", "beer", "pub", "lounge")):
        data["place_type"] = "bar"
    elif any(w in q for w in ("eat", "food", "restaurant", "dinner", "lunch", "brunch")):
        data["place_type"] = "restaurant"

    # Cuisine detection
    known = {"japanese", "italian", "chinese", "thai", "korean", "vietnamese",
             "indian", "french", "spanish", "mexican", "american", "cantonese",
             "ramen", "hotpot", "seafood", "steakhouse", "vegetarian",
             "sichuan", "malay", "indonesian", "filipino", "greek",
             "cocktail-bar", "wine-bar", "speakeasy", "rooftop-bar", "craft-beer",
             "pub", "lounge", "izakaya", "dive-bar"}
    for tag in known:
        if tag in q:
            data["cuisine"].append(tag)

    # Surprise
    if any(w in q for w in ("surprise", "random", "anything", "unexpected")):
        data["surprise"] = True

    # Budget
    budget_map = {"cheap": "$$", "mid-range": "$$$", "upscale": "$$$$", "fine dining": "$$$$"}
    for k, v in budget_map.items():
        if k in q:
            data["budget"] = v

    # Constraints
    if "open now" in q or "currently open" in q:
        data["constraints"].append("open_now")
    if "new" in q or "haven't been" in q or "not visited" in q:
        data["constraints"].append("not_visited")

    return data


# -----------------------------------------------------------------------
# Rationale generator
# -----------------------------------------------------------------------
_RATIONALE_SYSTEM = """You generate a brief, warm one-sentence rationale for why a specific restaurant/bar matches a user's request. Use the venue data and the user's taste profile. Be specific — mention cuisine, ratings, or special traits."""

_RATIONALE_TEMPLATE = """User asked: "{query}"
Venue: {name} | Cuisine: {tags} | OR: {or_rating} | Google: {google_rating} | Reviews: {reviews}
Secret gem: {gem}
Taste weights: {weights}
Generate a one-sentence rationale:"""


def generate_rationale(place, query: str, taste_weights: dict, llm: _OllamaClient) -> str:
    """Call LLM to generate a per-venue rationale. Returns empty string on failure."""
    weights_str = ", ".join(f"{k}={v}" for k, v in list(taste_weights.items())[:5])
    prompt = _RATIONALE_TEMPLATE.format(
        query=query,
        name=place.name,
        tags=", ".join(place.cuisine_tags + place.style_tags),
        or_rating=place.or_rating or "N/A",
        google_rating=place.google_rating or "N/A",
        reviews=place.review_count or "N/A",
        gem="yes" if place.is_secret_gem else "no",
        weights=weights_str,
    )
    return llm.generate(prompt, system=_RATIONALE_SYSTEM).strip()


# -----------------------------------------------------------------------
# Recommendation execution
# -----------------------------------------------------------------------
def execute_conversational_recommendation(
    query: str,
    all_places: list,
    data_dir: Path,
    user_id: str | None = None,
) -> tuple[list, str]:
    """
    End-to-end conversational flow:
      1. Parse query with LLM
      2. Run recommend() with optional semantic boost
      3. Generate rationales
    Returns (places, crossover_suggestion or "")
    """
    cfg = _get_llm_config()
    llm = _OllamaClient(
        url=cfg.get("ollama_url", "http://localhost:11434"),
        model=cfg.get("model", "gemma4:31b-cloud"),
        max_tokens=cfg.get("max_tokens", 512),
        temperature=cfg.get("temperature", 0.3),
    )

    parsed = parse_query(query, llm)
    logger.info(f"Parsed query: {parsed}")

    # Resolve coordinates
    if parsed.area and parsed.area in HK_AREAS:
        lat, lng = HK_AREAS[parsed.area]
        area_name = parsed.area
    else:
        lat, lng = HK_AREAS["Central"]
        area_name = "Central"

    # Resolve place type
    place_type = parsed.place_type or "restaurant"

    # Determine time filter
    use_time = "open_now" in parsed.constraints

    # Determine distance
    max_distance = 5000 if place_type == "bar" else 1500
    if "walking_distance" in parsed.constraints:
        max_distance = 800

    # Resolve cuisine
    cuisine = None
    if parsed.surprise or not parsed.cuisine:
        cuisine = "surprise"
    else:
        # Use first cuisine tag for main filter; others for semantic boost
        cuisine = parsed.cuisine[0].lower().strip()
        # Clean up common mismatches
        if cuisine in ("cocktails", "cocktail"):
            cuisine = "cocktail-bar"

    # Semantic boost only if embeddings exist
    use_semantic = False
    semantic_query = ""
    if parsed.cuisine or parsed.surprise:
        from pathlib import Path
        if (Path(__file__).parent.parent / "data" / "venue_embeddings.npy").exists():
            use_semantic = True
            semantic_query = " ".join(parsed.cuisine) if parsed.cuisine else query

    result: RecommendationResult = recommend(
        all_places=all_places,
        place_type=place_type,
        area_lat=lat,
        area_lng=lng,
        cuisine=cuisine,
        num_results=5,
        use_time_filter=use_time,
        area_name=area_name,
        max_distance_m=max_distance,
        price_filter=parsed.budget,
        use_semantic_boost=use_semantic,
        semantic_query=semantic_query,
    )

    # Generate rationales
    from engine.taste import _USER_TASTE_PROFILE
    for p in result.places:
        p.rationale = generate_rationale(p, query, _USER_TASTE_PROFILE, llm)

    crossover = result.crossover_suggestion or ""
    if parsed.surprise and crossover:
        crossover = f"Surprise: {crossover}"

    return result.places, crossover


# -----------------------------------------------------------------------
# Wrapper class for backward-compatible imports
# -----------------------------------------------------------------------
class ConversationEngine:
    """Thin wrapper around execute_conversational_recommendation for external callers."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def process(self, text: str, all_places: list) -> dict:
        """Process a natural language query and return structured result."""
        # Night-out detection
        if any(w in text.lower() for w in ("night out", "dinner then", "dinner +", "then drinks", "+ bar")):
            from engine.night_out import plan_night_out
            from handlers.common import HK_AREAS
            parsed = _fallback_parse(text)
            area = parsed.get("area") or "Central"
            lat, lng = HK_AREAS.get(area, (22.2783, 114.1747))
            cuisine = parsed.get("cuisine", ["surprise"])
            itineraries = plan_night_out(
                all_places=all_places,
                area_lat=lat,
                area_lng=lng,
                area_name=area,
                dinner_cuisine=cuisine[0] if cuisine else None,
                budget=parsed.get("budget"),
            )
            return {
                "type": "night_out",
                "itineraries": itineraries,
                "parsed": type("obj", (), {
                    "area": area,
                    "place_type": "both",
                    "budget": parsed.get("budget"),
                })(),
            }

        places, crossover = execute_conversational_recommendation(
            query=text,
            all_places=all_places,
            data_dir=Path(__file__).parent.parent / "data",
        )
        parsed = _fallback_parse(text)
        return {
            "type": "recommendation",
            "places": places,
            "crossover": crossover,
            "parsed": type("obj", (), {
                "area": parsed.get("area") or "Hong Kong",
                "place_type": parsed.get("place_type") or "restaurant",
                "budget": parsed.get("budget"),
            })(),
        }


# -----------------------------------------------------------------------
# Telegram handler
# -----------------------------------------------------------------------
async def find_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /find command — triggers conversational recommendation."""
    text = update.message.text or ""
    # Strip /find prefix
    if text.lower().startswith("/find"):
        text = text[5:].strip()

    if not text:
        await update.message.reply_text(
            "🍽 <b>Find</b>\n"
            "Say what you're craving and I'll figure it out.\n\n"
            "Examples:\n"
            "• <code>/find spicy Italian in Wan Chai</code>\n"
            "• <code>/find cocktail bar near Central</code>\n"
            "• <code>/find something new and exciting</code>",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text("🔍 Parsing your request...")

    # Load places
    bot_dir = Path(context.bot_data.get("bot_dir", "."))
    csv_path = bot_dir / "data" / "merged_places.csv"
    all_places = context.bot_data.get("_cached_places")
    if all_places is None:
        all_places = load_places(csv_path)
        context.bot_data["_cached_places"] = all_places

    try:
        places, crossover = execute_conversational_recommendation(
            query=text,
            all_places=all_places,
            data_dir=bot_dir / "data",
            user_id=str(update.effective_user.id) if update.effective_user else None,
        )
    except Exception as e:
        logger.error("Conversational recommendation failed", exc_info=True)
        await update.message.reply_text(
            f"😅 Couldn't process that. Try: <code>/find Italian in Wan Chai</code>",
            parse_mode="HTML",
        )
        return

    if not places:
        await update.message.reply_text(
            "😅 No matches found. Try broadening your request or another area."
        )
        return

    # Format with rationales
    from handlers.common import format_recommendations_message
    message = format_recommendations_message(
        places=places,
        area_name="Near you" if "lat" in text.lower() else "Hong Kong",
        place_type=places[0].type,
        crossover=crossover,
    )

    # Append rationales
    rationale_lines = []
    for i, p in enumerate(places):
        if getattr(p, "rationale", ""):
            rationale_lines.append(f"<i>Why #{i+1}:</i> {p.rationale}")
    if rationale_lines:
        message += "\n\n" + "\n\n".join(rationale_lines)

    await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
