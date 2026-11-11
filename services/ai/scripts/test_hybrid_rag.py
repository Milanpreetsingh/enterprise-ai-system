import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.connection import init_db
from app.db.hybrid_search import query_hybrid_rrf, query_hierarchical_rag

TEST_QUERIES = [
    "What is the warranty policy on product 5a6af266-4232-426b-8e20-193812043241?",
    "Can I get a refund after 20 days if I am a Diamond tier member?",
    "Is the AI allowed to approve a $750 refund without human approval?"
]

def main():
    print("=" * 70)
    print("    TESTING HYBRID SEARCH (RRF) & CROSS-ENCODER RE-RANKING    ")
    print("=" * 70)
    init_db()

    for idx, query in enumerate(TEST_QUERIES, 1):
        print(f"\n[Test Case {idx}] Query: \"{query}\"")
        print("─" * 70)

        # 1. Run First-Stage Hybrid RRF (Dense HNSW + Sparse BM25)
        raw_candidates = query_hybrid_rrf(query, top_candidates=4)
        print(f"-> Stage 1 (Hybrid RRF): Found {len(raw_candidates)} candidate chunks")
        for i, cand in enumerate(raw_candidates, 1):
            print(f"   [{i}] '{cand['parent_title']}' | RRF Score: {cand['rrf_score']:.5f} (Dense Rank: {cand['rank_dense']}, Sparse Rank: {cand['rank_sparse']})")

        # 2. Run Second-Stage Cross-Encoder Joint Re-Ranking
        final_results = query_hierarchical_rag(query, top_parents=1)
        print(f"\n-> Stage 2 (Cross-Encoder Re-Ranking Top Result):")
        if final_results:
            top = final_results[0]
            print(f"   🏆 Selected Parent: '{top['title']}'")
            print(f"   Re-Rank Score:      {top['rerank_score']:.4f}")
            print(f"   RRF Score:          {top['rrf_score']:.5f}")
            print(f"   Full Context Passed to LLM:")
            print(f"   \"{top['content']}\"")
        print("─" * 70)

if __name__ == "__main__":
    main()
