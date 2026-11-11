import json
import re
from app.db import connection
from app.db.rag import get_embedding
from app.db.reranker import rerank_passages

def semantic_chunk(text: str, target_words: int = 100, overlap_words: int = 20) -> list[str]:
    """
    Splits text into semantically cohesive chunks along sentence and paragraph boundaries,
    preserving context overlap across chunk edges.
    """
    # 1. Split on paragraph and sentence boundaries
    raw_sentences = re.split(r'(?<=[.!?])\s+|\n{2,}', text)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    chunks = []
    current_chunk = []
    current_word_count = 0

    for sent in sentences:
        words = sent.split()
        if not words:
            continue

        if current_word_count + len(words) > target_words and current_chunk:
            # Finalize current chunk
            chunk_text = " ".join(current_chunk)
            chunks.append(chunk_text)

            # Keep overlapping words from previous chunk for semantic continuity
            overlap = []
            overlap_count = 0
            for prev_sent in reversed(current_chunk):
                prev_words = prev_sent.split()
                overlap.insert(0, prev_sent)
                overlap_count += len(prev_words)
                if overlap_count >= overlap_words:
                    break

            current_chunk = overlap
            current_word_count = overlap_count

        current_chunk.append(sent)
        current_word_count += len(words)

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks if chunks else [text]

def seed_hierarchical_document(title: str, full_content: str, category: str = "policy", metadata: dict = None) -> str:
    """
    Indexes a parent document and breaks it into child chunks for hierarchical hybrid retrieval.
    Parent stores full context; child chunks store vector embeddings and tsvectors.
    """
    metadata_json = json.dumps(metadata or {})
    
    with connection.pool.connection() as conn:
        with conn.cursor() as cur:
            # 1. Insert Parent Document
            cur.execute(
                """
                INSERT INTO parent_documents (title, full_content, category, metadata)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (title, full_content, category, metadata_json)
            )
            parent_id = cur.fetchone()[0]

            # 2. Generate Semantic Child Chunks
            chunks = semantic_chunk(full_content, target_words=100, overlap_words=20)
            print(f"[Hierarchical Indexer] Document '{title}' generated {len(chunks)} child chunks.")

            for idx, chunk_text in enumerate(chunks):
                embedding = get_embedding(chunk_text)
                vector_str = f"[{','.join(map(str, embedding))}]"
                chunk_meta = json.dumps({
                    **(metadata or {}),
                    "parent_id": str(parent_id),
                    "chunk_index": idx,
                    "title": title
                })

                # Insert child chunk with vector embedding; PostgreSQL auto-populates 'tsv'
                cur.execute(
                    """
                    INSERT INTO knowledge_base_chunks 
                    (parent_id, chunk_content, chunk_index, embedding, metadata)
                    VALUES (%s, %s, %s, %s, %s);
                    """,
                    (parent_id, chunk_text, idx, vector_str, chunk_meta)
                )

            conn.commit()
            print(f"[Hierarchical Indexer] Successfully indexed parent ID {parent_id} with {len(chunks)} chunks.")
            return str(parent_id)

def query_hybrid_rrf(query: str, top_candidates: int = 15, rrf_k: float = 60.0) -> list[dict]:
    """
    Executes Hybrid Search combining Dense Vector Cosine Distance (HNSW) and
    Sparse Keyword Search (tsvector BM25) blended via Reciprocal Rank Fusion (RRF).
    """
    embedding = get_embedding(query)
    vector_str = f"[{','.join(map(str, embedding))}]"

    # Clean query for PostgreSQL full-text search
    clean_kw_query = re.sub(r'[^\w\s]', ' ', query).strip()
    if not clean_kw_query:
        clean_kw_query = query

    sql = """
    WITH vector_matches AS (
        SELECT 
            id, 
            parent_id,
            chunk_content,
            ROW_NUMBER() OVER (ORDER BY embedding <=> %s) AS rank_dense
        FROM knowledge_base_chunks
        ORDER BY embedding <=> %s
        LIMIT 25
    ),
    keyword_matches AS (
        SELECT 
            id, 
            parent_id,
            chunk_content,
            ROW_NUMBER() OVER (ORDER BY ts_rank_cd(tsv, plainto_tsquery('english', %s)) DESC) AS rank_sparse
        FROM knowledge_base_chunks
        WHERE tsv @@ plainto_tsquery('english', %s)
        ORDER BY ts_rank_cd(tsv, plainto_tsquery('english', %s)) DESC
        LIMIT 25
    ),
    rrf_fused AS (
        SELECT 
            COALESCE(v.id, k.id) AS chunk_id,
            COALESCE(v.parent_id, k.parent_id) AS parent_id,
            COALESCE(v.chunk_content, k.chunk_content) AS chunk_content,
            COALESCE(1.0 / (%s + v.rank_dense), 0.0) +
            COALESCE(1.0 / (%s + k.rank_sparse), 0.0) AS rrf_score,
            v.rank_dense,
            k.rank_sparse
        FROM vector_matches v
        FULL OUTER JOIN keyword_matches k ON v.id = k.id
    )
    SELECT 
        r.chunk_id,
        r.parent_id,
        p.title AS parent_title,
        p.full_content AS parent_content,
        r.chunk_content,
        r.rrf_score,
        COALESCE(r.rank_dense, 999),
        COALESCE(r.rank_sparse, 999)
    FROM rrf_fused r
    JOIN parent_documents p ON p.id = r.parent_id
    ORDER BY r.rrf_score DESC
    LIMIT %s;
    """

    with connection.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    vector_str, vector_str,
                    clean_kw_query, clean_kw_query, clean_kw_query,
                    rrf_k, rrf_k,
                    top_candidates
                )
            )
            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append({
                    "chunk_id": str(row[0]),
                    "parent_id": str(row[1]),
                    "parent_title": row[2],
                    "parent_content": row[3],
                    "chunk_content": row[4],
                    "rrf_score": float(row[5]),
                    "rank_dense": int(row[6]),
                    "rank_sparse": int(row[7])
                })
            return results

def query_hierarchical_rag(query: str, top_parents: int = 2) -> list[dict]:
    """
    Two-Stage Hierarchical RAG Pipeline:
    1. First Stage: Candidate generation via Hybrid Dense+Sparse RRF search (fetches top 15).
    2. Second Stage: Cross-Encoder joint attention re-ranking (selects top 2 parents).
    3. Returns deduplicated parent contexts with their source match snippets.
    """
    # 1. Candidate Retrieval (Hybrid RRF)
    candidates = query_hybrid_rrf(query, top_candidates=15)
    if not candidates:
        return []

    print(f"[Hybrid RRF] Retrieved {len(candidates)} candidate chunks.")

    # 2. Cross-Encoder Re-Ranking
    reranked = rerank_passages(query, candidates, top_k=top_parents * 2)

    # 3. Deduplicate by parent_id (so the LLM gets unique parent sections)
    seen_parents = set()
    final_results = []

    for item in reranked:
        pid = item["parent_id"]
        if pid not in seen_parents:
            seen_parents.add(pid)
            final_results.append({
                "parent_id": pid,
                "title": item["parent_title"],
                "content": item["parent_content"],
                "matched_snippet": item["chunk_content"],
                "rrf_score": item["rrf_score"],
                "rerank_score": item.get("rerank_score", 0.0),
                "rank_dense": item["rank_dense"],
                "rank_sparse": item["rank_sparse"]
            })
            if len(final_results) >= top_parents:
                break

    return final_results
