import os
import time

_cross_encoder = None

def get_cross_encoder():
    """
    Lazy loads a lightweight, fast Cross-Encoder model for re-ranking.
    ms-marco-MiniLM-L-6-v2 is an 80MB model optimized for sub-20ms passage scoring.
    """
    global _cross_encoder
    if _cross_encoder is None:
        from sentence_transformers import CrossEncoder
        model_name = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        print(f"[Cross-Encoder] Initializing Re-Ranker model: {model_name}...")
        _cross_encoder = CrossEncoder(model_name)
        print("[Cross-Encoder] Model loaded and ready for scoring.")
    return _cross_encoder

def rerank_passages(query: str, candidates: list[dict], top_k: int = 3) -> list[dict]:
    """
    Re-scores candidate passages against the query using full cross-attention.
    Candidates should have at least: 'id', 'chunk_content', 'parent_content'.
    """
    if not candidates:
        return []
    if len(candidates) <= 1:
        return candidates[:top_k]

    try:
        model = get_cross_encoder()
        # Formulate query-passage pairs
        pairs = [(query, cand.get("chunk_content", cand.get("content", ""))) for cand in candidates]
        
        t0 = time.time()
        scores = model.predict(pairs)
        duration_ms = (time.time() - t0) * 1000
        print(f"[Cross-Encoder] Re-ranked {len(candidates)} candidates in {duration_ms:.2f}ms.")

        for i, score in enumerate(scores):
            candidates[i]["rerank_score"] = float(score)

        # Sort descending by cross-encoder relevance score
        sorted_candidates = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)
        return sorted_candidates[:top_k]
    except Exception as e:
        print(f"[Cross-Encoder Warning] Re-ranking failed: {e}. Falling back to original order.")
        return candidates[:top_k]
