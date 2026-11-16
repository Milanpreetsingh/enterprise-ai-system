import json
import os
import re
import uuid
import numpy as np
import redis
from app.config import settings
from app.db.rag import get_embedding

# Support both REDIS_ADDR ("host:port") and separate REDIS_HOST / REDIS_PORT.
# Also safely handles Kubernetes default injected "tcp://ip:port" service environment variables.
redis_addr = os.getenv("REDIS_ADDR")
if redis_addr and ":" in redis_addr:
    REDIS_HOST, port_str = redis_addr.split(":", 1)
    REDIS_PORT = int(port_str)
else:
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    raw_port = os.getenv("REDIS_PORT", "6379")
    if raw_port.startswith("tcp://"):
        raw_port = raw_port.split(":")[-1]
    REDIS_PORT = int(raw_port)

try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
except Exception as e:
    print(f"[Redis Cache] Warning: Failed to connect to Redis: {e}")
    redis_client = None


def clean_legacy_cache() -> int:
    """
    Cleans up legacy unnamespaced keys (e.g. semantic_cache:<uuid>) that do not
    contain a thread_id namespace, ensuring clean state.
    """
    if not redis_client:
        return 0
    try:
        keys = redis_client.keys("semantic_cache:*")
        # Legacy keys only have 1 colon: "semantic_cache:<uuid>"
        # Thread-scoped keys have 2 colons: "semantic_cache:<thread_id>:<uuid>"
        legacy_keys = [k for k in keys if k.count(":") < 2]
        if legacy_keys:
            deleted = redis_client.delete(*legacy_keys)
            print(f"[Redis Cache] Cleaned up {deleted} legacy unnamespaced cache keys")
            return deleted
        return 0
    except Exception as e:
        print(f"[Redis Cache] Legacy cleanup error: {e}")
        return 0


# Clean up legacy cache keys on module load
clean_legacy_cache()


def invalidate_cache(thread_id: str | None = None) -> int:
    """
    Invalidates semantic cache entries in Redis.
    - If thread_id is provided, deletes all cached entries for that specific thread namespace.
    - If thread_id is None, deletes all semantic cache entries across all threads.
    Returns the number of keys deleted.
    """
    if not redis_client:
        return 0

    try:
        pattern = f"semantic_cache:{thread_id}:*" if thread_id else "semantic_cache:*"
        keys = redis_client.keys(pattern)
        if keys:
            deleted = redis_client.delete(*keys)
            print(f"[Redis Cache] Invalidated {deleted} cache entries for pattern '{pattern}'")
            return deleted
        return 0
    except Exception as e:
        print(f"[Redis Cache] Invalidation error: {e}")
        return 0


UUID_PATTERN = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 
    re.IGNORECASE
)


def extract_identifiers(text: str) -> set[str]:
    """
    Extracts entity identifiers (such as UUIDs) from query text to prevent
    semantic cache false positive hits when the question structure is identical
    but the target entity ID has changed.
    """
    if not text:
        return set()
    return set(UUID_PATTERN.findall(text.lower()))


def get_cached_answer(query: str, thread_id: str = "default", similarity_threshold: float | None = None) -> dict | None:
    """
    Computes query vector embedding and searches Redis for semantically similar
    previous queries WITHIN the specified thread_id namespace.
    If cosine similarity >= similarity_threshold and entity identifiers match,
    returns the cached answer.
    """
    if not redis_client:
        return None

    if similarity_threshold is None:
        similarity_threshold = settings.SEMANTIC_CACHE_THRESHOLD

    try:
        query_entities = extract_identifiers(query)
        query_vec = np.array(get_embedding(query))
        query_vec_norm = query_vec / np.linalg.norm(query_vec)

        # Scan only this thread's cache namespace
        keys = redis_client.keys(f"semantic_cache:{thread_id}:*")
        if not keys:
            return None

        best_match = None
        max_similarity = -1.0

        for key in keys:
            raw_data = redis_client.get(key)
            if not raw_data:
                continue
            entry = json.loads(raw_data)

            # Guard against cross-entity false positive semantic matches:
            # If queries mention distinct entity IDs (like different UUIDs),
            # they must NEVER be considered semantically identical.
            cached_query = entry.get("query", "")
            cached_entities = extract_identifiers(cached_query)
            if query_entities or cached_entities:
                if query_entities != cached_entities:
                    continue

            cached_vec = np.array(entry["embedding"])
            cached_vec_norm = cached_vec / np.linalg.norm(cached_vec)

            sim = float(np.dot(query_vec_norm, cached_vec_norm))
            if sim > max_similarity:
                max_similarity = sim
                best_match = entry

        if max_similarity >= similarity_threshold and best_match:
            print(f"[Redis Cache] HIT! Similarity: {max_similarity:.4f} | thread: {thread_id} | query: '{query}'")
            return {
                "answer": best_match["answer"],
                "similarity": max_similarity,
                "cache_hit": True
            }

        print(f"[Redis Cache] MISS | thread: {thread_id} | query: '{query}' (best sim: {max_similarity:.4f})")
        return None
    except Exception as e:
        print(f"[Redis Cache] Lookup error: {e}")
        return None


def set_cached_answer(query: str, answer: str, thread_id: str = "default", ttl_seconds: int = 86400):
    """
    Saves the query, its vector embedding, and the AI answer into Redis
    scoped under the given thread_id namespace.
    """
    if not redis_client or not answer or not answer.strip():
        return

    try:
        query_vec = get_embedding(query)
        entry = {
            "query": query,
            "embedding": query_vec,
            "answer": answer,
            "thread_id": thread_id
        }
        key = f"semantic_cache:{thread_id}:{uuid.uuid4()}"
        redis_client.setex(key, ttl_seconds, json.dumps(entry))
        print(f"[Redis Cache] Cached | thread: {thread_id} | query: '{query}'")
    except Exception as e:
        print(f"[Redis Cache] Save error: {e}")

