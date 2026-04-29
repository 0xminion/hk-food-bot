"""Tests for embedding infrastructure."""

import json
import numpy as np
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.loader import Place
from engine.embeddings import EmbeddingClient, _format_venue_text, build_embedding_matrix


class FakeEmbeddingClient:
    """Deterministic fake for testing without Ollama."""

    def __init__(self, dim: int = 4):
        self.dim = dim
        self.model = "fake"
        self.batch_size = 32

    def embed(self, texts: list[str]) -> np.ndarray:
        np.random.seed(42)
        return np.random.randn(len(texts), self.dim).astype(np.float32)


def test_format_venue_text():
    p = Place(
        name="Test Restaurant",
        type="restaurant",
        cuisine_tags=["italian", "pasta"],
        style_tags=["fine-dining"],
        district="Central",
        price_range="$$$",
        address="1 Test St",
        popular_dishes=["carbonara", "tiramisu", "bruschetta"],
    )
    text = _format_venue_text(p)
    assert "Test Restaurant" in text
    assert "italian" in text
    assert "fine-dining" in text
    assert "Central" in text
    assert "carbonara" in text
    assert "tiramisu" in text
    assert "bruschetta" in text


def test_build_embedding_matrix(tmp_path: Path):
    places = [
        Place(name="A", type="restaurant", cuisine_tags=["italian"]),
        Place(name="B", type="bar", cuisine_tags=["cocktail-bar"]),
        Place(name="C", type="restaurant", cuisine_tags=["thai"]),
    ]
    client = FakeEmbeddingClient(dim=4)
    vectors, index = build_embedding_matrix(places, client, output_dir=str(tmp_path))

    assert vectors.shape == (3, 4)
    assert index[0] == "A"
    assert index[1] == "B"
    assert index[2] == "C"
    assert (tmp_path / "venue_embeddings.npy").exists()
    assert (tmp_path / "venue_index.json").exists()


def test_cosine_similarity_orthogonality():
    a = np.array([[1, 0, 0, 0]], dtype=np.float32)
    b = np.array([[0, 1, 0, 0]], dtype=np.float32)
    from engine.semantic_filter import _normalize
    na = _normalize(a)
    nb = _normalize(b)
    # Orthogonal -> similarity = 0
    sim = float(np.dot(na, nb.T)[0, 0])
    assert sim == pytest.approx(0.0, abs=1e-6)


def test_semantic_filter_query(tmp_path: Path):
    from engine.semantic_filter import SemanticFilter
    # Create fake embedding files
    vectors = np.array([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0.9, 0.1, 0, 0],
    ], dtype=np.float32)
    index = {0: "Venue A", 1: "Venue B", 2: "Venue C"}
    np.save(tmp_path / "venue_embeddings.npy", vectors)
    with open(tmp_path / "venue_index.json", "w") as f:
        json.dump(index, f)

    # Mock client: embed query to [1, 0, 0, 0] → should match Venue A (exact) + C (close)
    class MockClient:
        def embed(self, texts):
            return np.array([[1, 0, 0, 0]], dtype=np.float32)
    import engine.semantic_filter as sf
    orig_client = sf.EmbeddingClient
    sf.EmbeddingClient = lambda *a, **k: MockClient()
    try:
        filt = SemanticFilter(str(tmp_path), "", "", 4)
        results = filt.query("italian restaurant", top_n=2)
        assert results[0][0] == "Venue A"
        assert results[0][1] == pytest.approx(1.0, abs=1e-5)
        assert results[1][0] == "Venue C"
    finally:
        sf.EmbeddingClient = orig_client
