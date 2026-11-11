import json
import numpy as np
from app.config import settings
from app.db import connection

_ollama_embedder = None

def _get_ollama_embedder():
    global _ollama_embedder
    if _ollama_embedder is None:
        from langchain_ollama import OllamaEmbeddings
        _ollama_embedder = OllamaEmbeddings(
            model=settings.OLLAMA_EMBED_MODEL,
            base_url=settings.OLLAMA_BASE_URL
        )
    return _ollama_embedder

def get_embedding(text: str) -> list[float]:
    """
    Generates a 1536-dimensional embedding vector for the given text.
    1. Uses OpenAIEmbeddings if OPENAI_API_KEY is present.
    2. Otherwise, uses OllamaEmbeddings (e.g. nomic-embed-text) via local Ollama.
       Vectors are zero-padded to 1536 dimensions so they match PostgreSQL VECTOR(1536)
       while preserving exact cosine similarities.
    3. Falls back to a deterministic vector generator if Ollama is unreachable.
    """
    if settings.OPENAI_API_KEY:
        from langchain_openai import OpenAIEmbeddings
        embeddings = OpenAIEmbeddings(openai_api_key=settings.OPENAI_API_KEY)
        return embeddings.embed_query(text)
    
    # 2. Local Ollama embedding model
    try:
        embedder = _get_ollama_embedder()
        raw_vec = embedder.embed_query(text)
        vec = np.array(raw_vec, dtype=float)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        
        # Zero-pad to 1536 dimensions to match PostgreSQL schema while preserving cosine distance
        if len(vec) < 1536:
            padded = np.zeros(1536, dtype=float)
            padded[:len(vec)] = vec
            return padded.tolist()
        return vec[:1536].tolist()
    except Exception as e:
        print(f"[Embedding Error] Ollama embedding failed: {e}. Falling back to deterministic vector.")

    # 3. Deterministic SHA256 vector generator fallback
    import hashlib
    h = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(h)
    vec = rng.standard_normal(1536)
    vec /= np.linalg.norm(vec)
    return vec.tolist()

def seed_document(content: str, metadata: dict = None) -> str:
    """
    Inserts a support document and its computed embedding into the knowledge base.
    """
    embedding = get_embedding(content)
    # Convert float list to pgvector string representation: [0.1, 0.2, ...]
    vector_str = f"[{','.join(map(str, embedding))}]"
    metadata_json = json.dumps(metadata or {})
    
    with connection.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO knowledge_base (content, embedding, metadata) VALUES (%s, %s, %s) RETURNING id;",
                (content, vector_str, metadata_json)
            )
            doc_id = cur.fetchone()[0]
            conn.commit()
            return str(doc_id)

def query_rag(query: str, limit: int = 3) -> list[dict]:
    """
    Retrieves semantically similar support documents using pgvector cosine distance.
    """
    embedding = get_embedding(query)
    vector_str = f"[{','.join(map(str, embedding))}]"
    
    with connection.pool.connection() as conn:
        with conn.cursor() as cur:
            # pgvector cosine distance: <=> operator
            cur.execute(
                """
                SELECT id, content, metadata, (embedding <=> %s) as distance 
                FROM knowledge_base 
                ORDER BY distance ASC 
                LIMIT %s;
                """,
                (vector_str, limit)
            )
            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append({
                    "id": str(row[0]),
                    "content": row[1],
                    "metadata": row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}"),
                    "distance": float(row[3])
                })
            return results
