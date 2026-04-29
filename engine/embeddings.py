"""
Ollama embedding client for venue vectorization.
Lightweight — only numpy + requests as deps.
"""

import json
import logging
from pathlib import Path
from typing import Iterator

import numpy as np
import requests

logger = logging.getLogger(__name__)


def _chunked(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class EmbeddingClient:
    """Thin wrapper around Ollama's /api/embed endpoint."""

    def __init__(self, ollama_url: str, model: str, dim: int, batch_size: int = 32):
        base = ollama_url.rstrip("/")
        # Ollama URL may already include /api/embed or be just the base
        if base.endswith("/api/embed"):
            self.url = base
        else:
            self.url = base + "/api/embed"
        self.model = model
        self.dim = dim
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        Embed a list of texts. Returns float32 [N x dim] matrix.
        """
        all_vectors: list[np.ndarray] = []
        total = len(texts)
        for i, batch in enumerate(_chunked(texts, self.batch_size)):
            try:
                resp = requests.post(
                    self.url,
                    json={"model": self.model, "input": batch, "truncate": False},
                    timeout=120,
                )
                resp.raise_for_status()
                payload = resp.json()
                embeddings = payload.get("embeddings", []) or payload.get("embedding", [])
                if not embeddings:
                    logger.warning("Empty embedding batch, returning zeros")
                    batch_vec = np.zeros((len(batch), self.dim), dtype=np.float32)
                else:
                    batch_vec = np.array(embeddings, dtype=np.float32)
                    if batch_vec.shape[1] != self.dim:
                        logger.warning(
                            f"Dimension mismatch: got {batch_vec.shape[1]}, expected {self.dim}"
                        )
                all_vectors.append(batch_vec)
                done = min((i + 1) * self.batch_size, total)
                logger.info(f"Embedding progress: {done}/{total} ({done/total*100:.1f}%)")
            except Exception:
                logger.error("Embedding request failed, returning zeros", exc_info=True)
                all_vectors.append(np.zeros((len(batch), self.dim), dtype=np.float32))
        return np.vstack(all_vectors)


def _format_venue_text(place) -> str:
    """Serialize a Place into an embedding-friendly text string."""
    parts = [
        place.name,
        place.address,
        f"Cuisine: {' '.join(place.cuisine_tags)}",
        f"Style: {' '.join(place.style_tags)}",
        f"District: {place.district}",
        f"Price: {place.price_range}",
    ]
    if place.popular_dishes:
        parts.append(f"Dishes: {', '.join(place.popular_dishes[:5])}")
    return " ".join(p for p in parts if p)


def build_embedding_matrix(
    places,
    client: EmbeddingClient,
    output_dir: str | Path = None,
) -> tuple[np.ndarray, dict]:
    """
    Pre-compute embeddings for all venues and persist to disk.

    Returns:
        vectors: float32 [N x dim] matrix
        index: dict[int, str] mapping vector index → place name
    """
    texts = [_format_venue_text(p) for p in places]
    logger.info(f"Building embeddings for {len(places)} venues via {client.model}")
    vectors = client.embed(texts)

    index = {i: p.name for i, p in enumerate(places)}

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        np.save(out / "venue_embeddings.npy", vectors)
        with open(out / "venue_index.json", "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
        logger.info(f"Saved to {out / 'venue_embeddings.npy'} ({vectors.shape})")

    return vectors, index


def load_embedding_matrix(data_dir: str | Path) -> tuple[np.ndarray, dict] | tuple[None, None]:
    """Load pre-computed embeddings and index from disk."""
    d = Path(data_dir)
    vec_path = d / "venue_embeddings.npy"
    idx_path = d / "venue_index.json"

    if not vec_path.exists() or not idx_path.exists():
        return None, None

    vectors = np.load(str(vec_path))
    with open(idx_path, encoding="utf-8") as f:
        index = {int(k): v for k, v in json.load(f).items()}

    logger.info(f"Loaded embeddings {vectors.shape} from {vec_path}")
    return vectors, index
