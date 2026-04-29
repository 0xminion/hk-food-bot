"""
Semantic filter: vector-based venue discovery.
Boosts candidates by cosine similarity between query text and pre-computed embeddings.
"""

import json
import logging
from pathlib import Path

import numpy as np

from engine.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)


def _normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize vectors in place."""
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return v / norms


class SemanticFilter:
    """Pre-computed embedding matrix with cosine similarity search."""

    def __init__(self, data_dir: str | Path, ollama_url: str, model: str, dim: int):
        d = Path(data_dir)
        vec_path = d / "venue_embeddings.npy"
        idx_path = d / "venue_index.json"

        if not vec_path.exists() or not idx_path.exists():
            raise FileNotFoundError(
                f"Embeddings not found at {vec_path}. Run scripts/build_embeddings.py first."
            )

        self.matrix = np.load(str(vec_path)).astype(np.float32)
        self.matrix = _normalize(self.matrix)

        with open(idx_path, encoding="utf-8") as f:
            self.index = {int(k): v for k, v in json.load(f).items()}

        self.name_to_idx = {v: k for k, v in self.index.items()}
        self.dim = dim
        self.client = EmbeddingClient(ollama_url, model, dim, batch_size=32)
        logger.info(f"SemanticFilter ready: {self.matrix.shape[0]} venues x {self.matrix.shape[1]} dims")

    def query(self, text: str, top_n: int = 50) -> list[tuple[str, float]]:
        """Embed query text, return top-N venue names by cosine similarity."""
        vec = self.client.embed([text])
        vec = _normalize(vec)[0]

        sims = np.dot(self.matrix, vec)  # [N]
        top_idx = np.argsort(sims)[::-1][:top_n]
        return [(self.index[i], float(sims[i])) for i in top_idx]

    def boost_candidates(
        self, candidates: list, query_text: str, boost_weight: float = 0.3
    ) -> list:
        """
        Augment candidate list with semantic_score.
        Normalizes scores to [0, 1] and adds boost_weight * score to the
        venue's taste-relevant sorting key (distance_walk_m).
        Returns candidates re-sorted by composite score.
        """
        semantic_hits = {name: score for name, score in self.query(query_text, top_n=200)}

        # Normalize semantic scores to [0, 1] within this candidate pool
        local_scores = [semantic_hits.get(p.name, 0.0) for p in candidates]
        if local_scores:
            smin, smax = min(local_scores), max(local_scores)
            if smax > smin:
                norm_scores = [(s - smin) / (smax - smin) for s in local_scores]
            else:
                norm_scores = [0.0] * len(local_scores)
        else:
            norm_scores = []

        for p, sem in zip(candidates, norm_scores):
            p.semantic_score = round(sem, 3)

        # Sort by taste_score (from taste.py) + semantic boost + distance penalty
        # We approximate composite: lower distance_walk_m is better
        def composite_score(p):
            distance_penalty = (p.distance_walk_m or 99999) / 2000.0  # ~0-5 scale
            # Assume score_and_rank_places already ran; if not, default to 0
            taste = getattr(p, "taste_score", 0.0)
            sem = getattr(p, "semantic_score", 0.0)
            return taste + (boost_weight * sem) - distance_penalty

        candidates.sort(key=composite_score, reverse=True)
        return candidates
