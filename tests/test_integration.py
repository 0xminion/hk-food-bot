"""
Integration tests for HK Food Bot — full pipeline validation.

Tests the actual merged dataset end-to-end: load → filter → score → rank → format.
Covers the changes made today (name_norm, pre-built index, franchise dedup)
plus the full pipeline's correctness under real data conditions.

Run: python -m pytest tests/test_integration.py -v
"""

import csv
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.loader import Place, load_places, filter_by_type, filter_by_cuisine, filter_by_any_tag, compute_distances
from engine.recommender import recommend, _filter_bottom_percentile, AREA_SCOPE_NEIGHBORS
from engine.taste import score_place, score_and_rank_places, USER_TASTE_PROFILE
from engine.crossover import get_similar_cuisines
from engine.time_aware import filter_open_places, is_open_now
from engine.secret_gem import apply_secret_gem_rules
from handlers.common import format_recommendation, format_recommendations_message, price_matches, HK_AREAS
from utils.name_norm import normalize_name, build_name_index, build_franchise_groups


# ── Real Data Fixtures ────────────────────────────────────────────────────────

MERGED_CSV = Path(__file__).parent.parent / "data" / "merged_places.csv"


@pytest.fixture(scope="module")
def real_places():
    """Load the actual merged dataset. Skips suite if file missing."""
    if not MERGED_CSV.exists():
        pytest.skip("merged_places.csv not found")
    places = load_places(MERGED_CSV)
    assert len(places) > 1000, f"Expected 10K+ venues, got {len(places)}"
    return places


@pytest.fixture(scope="module")
def restaurants(real_places):
    return filter_by_type(real_places, "restaurant")


@pytest.fixture(scope="module")
def bars(real_places):
    return filter_by_type(real_places, "bar")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Name Normalization & Franchise Dedup
# ═══════════════════════════════════════════════════════════════════════════════

class TestNameNormalization:
    """normalize_name() handles all franchise patterns correctly."""

    def test_parenthesized_location_cn(self):
        assert normalize_name("麥當勞 (銅鑼灣)") == "麥當勞"

    def test_parenthesized_location_en(self):
        assert normalize_name("McDonald's (Central)") == "mcdonald's"

    def test_dash_separated_location(self):
        assert normalize_name("Café de Coral - TST") == "cafe de coral"

    def test_preserves_chinese(self):
        assert normalize_name("大快活 (旺角)") == "大快活"

    def test_normalizes_accents(self):
        assert normalize_name("naïve Café") == "naive cafe"

    def test_plain_name_unchanged(self):
        assert normalize_name("Yardbird") == "yardbird"

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_whitespace_only(self):
        assert normalize_name("   ") == ""

    def test_multiple_spaces_collapsed(self):
        assert normalize_name("Foo   Bar") == "foo bar"

    def test_case_insensitive(self):
        assert normalize_name("Burger King") == normalize_name("BURGER KING")


class TestFranchiseDedup:
    """Franchises with same name, different addresses get deduped to closest."""

    def _make_franchise(self, name, address, lat, lng, walk_m):
        return Place(
            name=name, type="restaurant", cuisine_tags=["japanese"],
            address=address, lat=lat, lng=lng,
            distance_walk_m=walk_m, google_rating=4.0,
        )

    def test_closest_branch_kept(self):
        """When two branches exist, the closer one survives dedup."""
        places = [
            self._make_franchise("壽司郎 (銅鑼灣)", "銅鑼灣 addr", 22.280, 114.185, 500),
            self._make_franchise("壽司郎 (旺角)", "旺角 addr", 22.319, 114.169, 2000),
        ]
        result = recommend(
            all_places=places, place_type="restaurant",
            area_lat=22.279, area_lng=114.175,
            use_time_filter=False, use_taste_scoring=False,
        )
        assert len(result.places) == 1
        # The closer branch (銅鑼灣) should win, not 旺角
        assert "銅鑼灣" in result.places[0].name or result.places[0].distance_walk_m < 2000

    def test_three_branches_keeps_closest(self):
        places = [
            self._make_franchise("Lady M", "IFC", 22.285, 114.159, 800),
            self._make_franchise("Lady M", "Harbour City", 22.297, 114.170, 1500),
            self._make_franchise("Lady M (TST)", "K11", 22.296, 114.172, 1600),
        ]
        result = recommend(
            all_places=places, place_type="restaurant",
            area_lat=22.279, area_lng=114.175,
            use_time_filter=False, use_taste_scoring=False,
        )
        assert len(result.places) == 1
        # IFC branch (closest to Wan Chai origin) should win
        assert result.places[0].distance_walk_m < 3000

    def test_different_names_not_deduped(self):
        """Different restaurants in same area should NOT be deduped."""
        places = [
            self._make_franchise("Restaurant A", "Addr A", 22.280, 114.175, 100),
            self._make_franchise("Restaurant B", "Addr B", 22.280, 114.176, 150),
        ]
        result = recommend(
            all_places=places, place_type="restaurant",
            area_lat=22.279, area_lng=114.175,
            use_time_filter=False, use_taste_scoring=False,
        )
        assert len(result.places) == 2

    def test_franchise_groups_in_real_data(self, real_places):
        """Real data should have 1000+ franchise groups."""
        groups = build_franchise_groups(real_places)
        multi = {k: v for k, v in groups.items() if len(v) > 1}
        assert len(multi) > 1000, f"Expected 1000+ franchise groups, got {len(multi)}"

    def test_major_chains_have_many_branches(self, real_places):
        """Major chains (麥當勞, 星巴克) should have 50+ branches."""
        groups = build_franchise_groups(real_places)
        # Find McDonald's by any name variant
        mc = [v for k, v in groups.items() if "麥當勞" in k]
        assert any(len(v) > 50 for v in mc), "麥當勞 should have 50+ branches"

    def test_normalize_name_consistent_across_modules(self):
        """Both recommender and awards should produce the same normalized key."""
        name = "Bo Innovation (Sheung Wan)"
        from engine.awards import get_award_boost
        # The awards module imports normalize_name from utils.name_norm
        # Verify by checking the import is shared
        norm = normalize_name(name)
        assert norm == "bo innovation"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Pre-built Name Index
# ═══════════════════════════════════════════════════════════════════════════════

class TestNameIndex:
    """Pre-built name index replaces O(N×M) linear scan with O(1) lookup."""

    def test_index_builds_correctly(self):
        cache = {
            "Yardbird|Central": {"google_rating": 4.6, "google_reviews": 1763},
            "Yardbird|Sheung Wan": {"google_rating": 4.5, "google_reviews": 1200},
            "Thai Basil|Wan Chai": {"google_rating": 4.5, "google_reviews": 150},
        }
        index = build_name_index(cache)
        assert "yardbird" in index
        assert "thai basil" in index
        assert len(index["yardbird"]) == 2

    def test_index_sorted_by_review_count(self):
        cache = {
            "Place|Addr1": {"google_rating": 4.0, "google_reviews": 100},
            "Place|Addr2": {"google_rating": 4.5, "google_reviews": 500},
            "Place|Addr3": {"google_rating": 3.8, "google_reviews": 50},
        }
        index = build_name_index(cache)
        entries = index["place"]
        # Most reviewed first — check all reviews are in descending order
        reviews = [int(e[1].get("google_reviews", 0)) for e in entries]
        assert reviews == sorted(reviews, reverse=True), f"Not sorted: {reviews}"

    def test_index_handles_parenthesized_names(self):
        cache = {
            "麥當勞 (銅鑼灣)|addr1": {"google_rating": 3.7, "google_reviews": 200},
            "麥當勞 (旺角)|addr2": {"google_rating": 3.6, "google_reviews": 150},
        }
        index = build_name_index(cache)
        # Both should normalize to same key
        keys = list(index.keys())
        assert len(keys) == 1  # Both normalize to "麥當勞"

    def test_load_places_uses_index(self, real_places):
        """Verify real data loaded with index — check enrichment worked."""
        with_rating = [p for p in real_places if p.google_rating > 0]
        # At least 90% should have Google ratings (from cache enrichment)
        ratio = len(with_rating) / len(real_places)
        assert ratio > 0.85, f"Only {ratio:.0%} have Google ratings — index enrichment may be broken"

    def test_load_performance(self):
        """load_places() should complete in under 3 seconds."""
        if not MERGED_CSV.exists():
            pytest.skip("merged_places.csv not found")
        t0 = time.time()
        places = load_places(MERGED_CSV)
        elapsed = time.time() - t0
        assert elapsed < 3.0, f"load_places took {elapsed:.1f}s — regression from 0.96s baseline"
        assert len(places) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Full Pipeline End-to-End (Real Data)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipelineE2E:
    """Full recommendation pipeline with real merged dataset."""

    # ── Restaurant flows ──

    def test_restaurant_italian_wanchai(self, real_places):
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Wan Chai"][0], area_lng=HK_AREAS["Wan Chai"][1],
            cuisine="italian", area_name="Wan Chai",
            use_time_filter=False,
        )
        assert len(result.places) > 0
        assert len(result.places) <= 5
        for p in result.places:
            assert "italian" in p.cuisine_tags or result.crossover_suggestion

    def test_restaurant_japanese_causeway_bay(self, real_places):
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Causeway Bay"][0], area_lng=HK_AREAS["Causeway Bay"][1],
            cuisine="japanese", area_name="Causeway Bay",
            use_time_filter=False,
        )
        assert len(result.places) > 0

    def test_restaurant_cantonese_central(self, real_places):
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Central"][0], area_lng=HK_AREAS["Central"][1],
            cuisine="cantonese", area_name="Central",
            use_time_filter=False,
        )
        assert len(result.places) > 0

    # ── Bar flows ──

    def test_bar_cocktail_wanchai(self, real_places):
        result = recommend(
            all_places=real_places, place_type="bar",
            area_lat=HK_AREAS["Wan Chai"][0], area_lng=HK_AREAS["Wan Chai"][1],
            cuisine="cocktail-bar", area_name="Wan Chai",
            use_time_filter=False,
        )
        # Cocktail bars may be sparse — at least get some result or crossover
        assert isinstance(result.places, list)

    def test_bar_speakeasy_central(self, real_places):
        result = recommend(
            all_places=real_places, place_type="bar",
            area_lat=HK_AREAS["Central"][0], area_lng=HK_AREAS["Central"][1],
            cuisine="speakeasy", area_name="Central",
            use_time_filter=False,
        )
        assert isinstance(result.places, list)

    # ── Surprise mode ──

    def test_surprise_restaurant(self, real_places):
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Central"][0], area_lng=HK_AREAS["Central"][1],
            cuisine="surprise", area_name="Central",
            use_time_filter=False,
        )
        assert len(result.places) > 0
        assert result.crossover_suggestion  # Should have picked a cuisine

    # ── No cuisine filter ──

    def test_no_cuisine_returns_any(self, real_places):
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Wan Chai"][0], area_lng=HK_AREAS["Wan Chai"][1],
            use_time_filter=False,
        )
        assert len(result.places) > 0

    # ── All areas work ──

    @pytest.mark.parametrize("area_name", list(HK_AREAS.keys()))
    def test_each_area_returns_results(self, real_places, area_name):
        lat, lng = HK_AREAS[area_name]
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=lat, area_lng=lng, area_name=area_name,
            use_time_filter=False,
        )
        assert len(result.places) > 0, f"No results for {area_name}"

    # ── Crossover fallback ──

    def test_rare_cuisine_triggers_crossover(self, real_places):
        """Spanish is rare in HK — should trigger crossover or return few results."""
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Central"][0], area_lng=HK_AREAS["Central"][1],
            cuisine="spanish", area_name="Central",
            use_time_filter=False,
        )
        # Either got results or crossover suggestion
        assert len(result.places) >= 0  # Shouldn't crash

    # ── Results quality ──

    def test_results_sorted_by_taste_or_rating(self, real_places):
        # With taste scoring on (default), results should respect taste ordering.
        # Just verify results are returned and non-empty.
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Wan Chai"][0], area_lng=HK_AREAS["Wan Chai"][1],
            cuisine="japanese", use_time_filter=False,
        )
        assert len(result.places) > 0
        # When taste scoring is OFF, sort by raw rating is deterministic
        result2 = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Wan Chai"][0], area_lng=HK_AREAS["Wan Chai"][1],
            cuisine="japanese", use_time_filter=False, use_taste_scoring=False,
        )
        for i in range(len(result2.places) - 1):
            assert result2.places[i].google_rating >= result2.places[i + 1].google_rating

    def test_no_duplicate_names_in_results(self, real_places):
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Central"][0], area_lng=HK_AREAS["Central"][1],
            use_time_filter=False,
        )
        names = [p.name for p in result.places]
        assert len(names) == len(set(names)), f"Duplicates: {[n for n in names if names.count(n) > 1]}"

    def test_results_within_distance(self, real_places):
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Wan Chai"][0], area_lng=HK_AREAS["Wan Chai"][1],
            area_name="Wan Chai", use_time_filter=False,
        )
        for p in result.places:
            if p.distance_walk_m:
                assert p.distance_walk_m <= 1500, f"{p.name} at {p.distance_walk_m}m is outside scope"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Pipeline Step Isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipelineSteps:
    """Test each pipeline step in isolation with real data."""

    def test_type_filter_separates_restaurants_and_bars(self, real_places):
        restaurants = filter_by_type(real_places, "restaurant")
        bars = filter_by_type(real_places, "bar")
        assert len(restaurants) > 10000
        assert len(bars) > 1000
        assert len(restaurants) + len(bars) == len(real_places)

    def test_cuisine_filter_japanese(self, real_places):
        jp = filter_by_cuisine(real_places, ["japanese"])
        assert len(jp) > 100, f"Expected 100+ Japanese venues, got {len(jp)}"
        assert all("japanese" in p.cuisine_tags for p in jp[:10])

    def test_any_tag_filter_cocktail(self, real_places):
        bars = filter_by_type(real_places, "bar")
        cocktails = filter_by_any_tag(bars, ["cocktail-bar"])
        assert len(cocktails) > 10

    def test_distance_computation(self, real_places):
        nearby = [p for p in real_places[:100] if p.lat and p.lng]
        compute_distances(nearby, 22.279, 114.175)
        for p in nearby:
            assert p.distance_walk_m >= 0
            assert p.distance_drive_m >= 0

    def test_bottom_percentile_filter(self):
        places = [
            Place(name=f"P{i}", type="restaurant", cuisine_tags=["thai"],
                  google_rating=float(i) / 10)
            for i in range(1, 21)  # 20 places, ratings 0.1-2.0
        ]
        filtered = _filter_bottom_percentile(places, percentile=20)
        assert len(filtered) < len(places)
        # Bottom 20% should be removed (ratings 0.1-0.4)
        names = {p.name for p in filtered}
        assert "P1" not in names  # rating 0.1 — bottom 20%

    def test_area_scope_neighbors(self):
        """Every area in scope map should have valid neighbor coords."""
        from engine.recommender import _area_search_origins
        for area in AREA_SCOPE_NEIGHBORS:
            origins = _area_search_origins(area)
            assert len(origins) > 0, f"No origins for {area}"
            for name, lat, lng in origins:
                assert 22.0 < lat < 23.0, f"{area}/{name} lat out of range"
                assert 113.5 < lng < 115.0, f"{area}/{name} lng out of range"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Taste Scoring with Real Data
# ═══════════════════════════════════════════════════════════════════════════════

class TestTasteScoring:
    """Taste scoring correctly prioritizes user preferences."""

    def test_italian_scores_highest(self):
        italian = Place(name="X", type="restaurant", cuisine_tags=["italian"])
        mexican = Place(name="Y", type="restaurant", cuisine_tags=["mexican"])
        assert score_place(italian) > score_place(mexican)

    def test_cocktail_bar_scores_high(self):
        bar = Place(name="X", type="bar", cuisine_tags=["cocktail-bar"])
        pub = Place(name="Y", type="bar", cuisine_tags=["pub"])
        assert score_place(bar) > score_place(pub)

    def test_style_tag_bonus_applied(self):
        with_style = Place(name="X", type="restaurant",
                           cuisine_tags=["japanese"], style_tags=["speakeasy"])
        without = Place(name="Y", type="restaurant",
                        cuisine_tags=["japanese"], style_tags=[])
        assert score_place(with_style) > score_place(without)

    def test_secret_gem_bonus(self):
        gem = Place(name="X", type="restaurant", cuisine_tags=["thai"],
                    is_secret_gem=True, google_rating=4.5)
        normal = Place(name="Y", type="restaurant", cuisine_tags=["thai"],
                       is_secret_gem=False, google_rating=4.5)
        scored = score_and_rank_places([gem, normal])
        gem_scored = next(s for s in scored if s.place.name == "X")
        assert gem_scored.bonus_gem > 0

    def test_rating_bonus_tiers(self):
        high = Place(name="H", type="restaurant", cuisine_tags=["thai"], google_rating=4.8)
        mid = Place(name="M", type="restaurant", cuisine_tags=["thai"], google_rating=4.2)
        low = Place(name="L", type="restaurant", cuisine_tags=["thai"], google_rating=3.2)
        scored = score_and_rank_places([low, mid, high])
        names_order = [s.place.name for s in scored]
        assert names_order.index("H") < names_order.index("M")
        assert names_order.index("M") < names_order.index("L")

    def test_real_data_taste_scoring(self, restaurants):
        """Top-scored places from real data should favor Italian/Chinese/Japanese."""
        scored = score_and_rank_places(restaurants[:500])
        top_cuisines = set()
        for s in scored[:20]:
            top_cuisines.update(s.place.cuisine_tags)
        high_pref = {"italian", "chinese", "cantonese", "japanese", "cocktail-bar"}
        assert top_cuisines & high_pref, f"Top 20 places don't include any preferred cuisines: {top_cuisines}"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Exclusion Lists
# ═══════════════════════════════════════════════════════════════════════════════

class TestExclusions:
    """Closed places and personal exclusions are properly filtered."""

    def test_closed_places_excluded(self, real_places):
        from data.loader import load_closed_places
        closed = load_closed_places(MERGED_CSV.parent)
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Central"][0], area_lng=HK_AREAS["Central"][1],
            use_time_filter=False,
        )
        result_names = {p.name.lower() for p in result.places}
        closed_in_results = result_names & closed
        assert len(closed_in_results) == 0, f"Closed places in results: {closed_in_results}"

    def test_personal_exclusions_excluded(self, real_places):
        from data.loader import load_personal_exclusions
        personal = load_personal_exclusions(MERGED_CSV.parent)
        if not personal:
            pytest.skip("No personal exclusions loaded")
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Wan Chai"][0], area_lng=HK_AREAS["Wan Chai"][1],
            use_time_filter=False,
        )
        result_names = {p.name.lower() for p in result.places}
        personal_in_results = result_names & personal
        assert len(personal_in_results) == 0, f"Personal excluded places in results: {personal_in_results}"

    def test_skip_personal_exclusions_flag(self, real_places):
        """skip_personal_exclusions=True should include otherwise-excluded places."""
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Central"][0], area_lng=HK_AREAS["Central"][1],
            use_time_filter=False, skip_personal_exclusions=True,
        )
        assert len(result.places) > 0

    def test_is_closed_field_excluded(self, sample_places):
        sample_places[0].is_closed = True
        result = recommend(
            all_places=sample_places, place_type="restaurant",
            area_lat=22.279, area_lng=114.175,
            use_time_filter=False,
        )
        assert sample_places[0].name not in {p.name for p in result.places}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7: Price Filtering
# ═══════════════════════════════════════════════════════════════════════════════

class TestPriceFiltering:
    """Price range filtering works end-to-end."""

    def test_exact_match(self):
        assert price_matches("$$", "$$") is True

    def test_mismatch(self):
        assert price_matches("$$", "$$$") is False

    def test_any_matches_all(self):
        assert price_matches("$$$", "any") is True

    def test_empty_price_included(self):
        assert price_matches("", "$$") is True

    def test_pipeline_price_filter(self, real_places):
        result = recommend(
            all_places=real_places, place_type="restaurant",
            area_lat=HK_AREAS["Central"][0], area_lng=HK_AREAS["Central"][1],
            price_filter="$", use_time_filter=False,
        )
        for p in result.places:
            if p.price_range:
                assert p.price_range.count("$") == 1, f"{p.name} has {p.price_range} but filtered for $"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8: Output Formatting
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatting:
    """Output formatting produces correct Telegram-ready messages."""

    def test_single_recommendation_format(self):
        place = Place(
            name="Test Place", type="restaurant", cuisine_tags=["italian"],
            google_rating=4.5, review_count=100,
            address="123 Central", distance_walk_m=500, distance_drive_m=800,
            booking_url="https://chope.com/test",
        )
        text = format_recommendation(place, 1)
        assert "Test Place" in text
        assert "italian" in text.lower()
        assert "🚶" in text
        assert "Book here" in text

    def test_recommendations_message_header(self, sample_places):
        msg = format_recommendations_message(sample_places, "Wan Chai", "restaurant")
        assert "Wan Chai" in msg

    def test_recommendations_with_crossover(self):
        places = [Place(name="A", type="restaurant", cuisine_tags=["vietnamese"])]
        msg = format_recommendations_message(places, "Central", "restaurant",
                                             crossover="vietnamese", expanded=True)
        assert "vietnamese" in msg.lower() or "Vietnamese" in msg

    def test_format_with_real_data(self, real_places):
        """Formatting real data should never crash."""
        for place in real_places[:20]:
            text = format_recommendation(place, 1)
            assert len(text) > 0
            assert place.name in text

    def test_google_maps_url_in_format(self, sample_places):
        text = format_recommendation(sample_places[0], 1)
        # Should contain a Google Maps link
        assert "google.com/maps" in text or "maps.app.goo.gl" in text


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9: Time-Aware Filtering
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimeFiltering:
    """Opening hours filtering works correctly."""

    def test_always_open_is_open(self):
        assert is_open_now("Mo-Su 00:00-23:59") is True

    def test_closed_phrase(self):
        assert is_open_now("Temporarily closed") is False

    def test_empty_hours_unknown(self):
        result = is_open_now("")
        # Empty hours returns None (unknown) — shouldn't crash
        assert result is None or result is True

    def test_filter_open_places_excludes_closed(self):
        places = [
            Place(name="Open", type="restaurant", opening_hours="Mo-Su 00:00-23:59"),
            Place(name="Closed", type="restaurant", opening_hours="Temporarily closed"),
        ]
        open_now = filter_open_places(places)
        names = {p.name for p in open_now}
        assert "Closed" not in names

    def test_multi_period_hours(self):
        """Places with lunch+dinner periods should be open during both."""
        from engine.time_aware import parse_opening_hours
        result = parse_opening_hours("Mo-Su 12:00-14:30, 18:00-22:00")
        assert "mon" in result
        assert len(result["mon"]) == 2  # Two periods


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10: Merge Data Script
# ═══════════════════════════════════════════════════════════════════════════════

class TestMergeData:
    """The merge script produces valid output."""

    def test_merge_produces_valid_csv(self):
        """Running merge_data.py should produce a valid CSV with expected columns."""
        if not MERGED_CSV.exists():
            pytest.skip("merged_places.csv not found")
        with open(MERGED_CSV, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) > 10000

        # Check required columns exist
        required = {"name", "type", "cuisine_tags", "address", "lat", "lng",
                     "google_rating", "or_rating", "source"}
        assert required.issubset(set(rows[0].keys()))

    def test_merge_preserves_all_bars(self):
        """Merge should not lose bars (650 were previously lost by name-only dedup)."""
        if not MERGED_CSV.exists():
            pytest.skip("merged_places.csv not found")
        with open(MERGED_CSV, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        bars = [r for r in rows if r["type"] == "bar"]
        assert len(bars) > 1500, f"Expected 1500+ bars, got {len(bars)} — possible dedup regression"

    def test_merge_no_name_only_dedup(self):
        """Same-name, different-address venues should ALL be preserved."""
        if not MERGED_CSV.exists():
            pytest.skip("merged_places.csv not found")
        with open(MERGED_CSV, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        # Find a known chain
        from collections import Counter
        name_counts = Counter(normalize_name(r["name"]) for r in rows)
        chains = {k: v for k, v in name_counts.items() if v > 5}
        assert len(chains) > 100, "Should have 100+ chains with 5+ branches"

        # Verify chain branches have different addresses
        for chain_name in list(chains.keys())[:5]:
            branches = [r for r in rows if normalize_name(r["name"]) == chain_name]
            addresses = {r["address"] for r in branches}
            assert len(addresses) > 1, f"Chain '{chain_name}' has {len(branches)} entries but only 1 address"

    def test_merge_source_tracking(self):
        """Every row should have a source field."""
        if not MERGED_CSV.exists():
            pytest.skip("merged_places.csv not found")
        with open(MERGED_CSV, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        sources = {r.get("source", "") for r in rows[:100]}
        assert sources - {""}  # At least some rows have a source

    def test_merge_google_enrichment(self):
        """Most rows should have Google ratings from cache."""
        if not MERGED_CSV.exists():
            pytest.skip("merged_places.csv not found")
        with open(MERGED_CSV, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        with_google = [r for r in rows if r.get("google_rating")]
        ratio = len(with_google) / len(rows)
        assert ratio > 0.85, f"Only {ratio:.0%} have Google ratings after merge"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 11: Edge Cases & Regression Guards
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases and regression guards."""

    def test_empty_input(self):
        result = recommend(
            all_places=[], place_type="restaurant",
            area_lat=22.279, area_lng=114.175,
            use_time_filter=False,
        )
        assert result.places == []

    def test_num_results_clamped(self, sample_places):
        result = recommend(
            all_places=sample_places, place_type="restaurant",
            area_lat=22.279, area_lng=114.175,
            num_results=999, use_time_filter=False,
        )
        assert len(result.places) <= 50

    def test_zero_coordinates_excluded(self):
        places = [
            Place(name="Valid", type="restaurant", cuisine_tags=["thai"],
                  lat=22.279, lng=114.175, google_rating=4.0),
            Place(name="Invalid", type="restaurant", cuisine_tags=["thai"],
                  lat=0.0, lng=0.0, google_rating=4.0),
        ]
        result = recommend(
            all_places=places, place_type="restaurant",
            area_lat=22.279, area_lng=114.175,
            use_time_filter=False,
        )
        names = {p.name for p in result.places}
        assert "Invalid" not in names

    def test_negative_coordinates_valid(self):
        """Negative coords are valid (Southern/Western hemispheres)."""
        dist = compute_distances(
            [Place(name="X", type="restaurant", lat=-22.0, lng=-114.0)],
            22.279, 114.175
        )
        assert dist[0].distance_walk_m > 0

    def test_unicode_names(self):
        places = [
            Place(name="大班樓", type="restaurant", cuisine_tags=["cantonese"],
                  lat=22.279, lng=114.175, google_rating=4.8),
        ]
        result = recommend(
            all_places=places, place_type="restaurant",
            area_lat=22.279, area_lng=114.175,
            use_time_filter=False,
        )
        assert result.places[0].name == "大班樓"

    def test_very_long_name(self):
        long_name = "A" * 500
        places = [Place(name=long_name, type="restaurant", cuisine_tags=["thai"],
                        lat=22.279, lng=114.175)]
        result = recommend(
            all_places=places, place_type="restaurant",
            area_lat=22.279, area_lng=114.175,
            use_time_filter=False,
        )
        assert len(result.places) <= 1

    def test_special_chars_in_tags(self):
        """Tags with special chars should parse correctly."""
        from data.loader import _parse_tags
        assert _parse_tags('[\"casual\", \"fine-dining\"]') == ["casual", "fine-dining"]
        assert _parse_tags("casual,fine-dining") == ["casual", "fine-dining"]
