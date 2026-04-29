#!/usr/bin/env python3
"""
One-time script to pre-compute venue embeddings.
Usage:  python scripts/build_embeddings.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from data.loader import load_places
from engine.embeddings import build_embedding_matrix, EmbeddingClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    project_root = Path(__file__).parent.parent
    config_path = project_root / "config.yaml"
    csv_path = project_root / "data" / "merged_places.csv"
    data_dir = project_root / "data"

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    emb_cfg = cfg.get("embedding", {})
    ollama_url = emb_cfg.get("ollama_url", "http://localhost:11434")
    model = emb_cfg.get("model", "qwen3-embedding:0.6b")
    dim = emb_cfg.get("dim", 1024)
    batch_size = emb_cfg.get("batch_size", 32)

    logger.info("Loading places...")
    places = load_places(csv_path)
    logger.info(f"Loaded {len(places)} places")
    logger.info(f"Sample: {', '.join(p.name for p in places[:3])}")

    client = EmbeddingClient(ollama_url, model, dim, batch_size)
    vectors, index = build_embedding_matrix(places, client, output_dir=data_dir)
    logger.info(f"Done. Matrix shape: {vectors.shape}")


if __name__ == "__main__":
    main()
