import json
from datetime import datetime
from app.db.connection import get_connection
from app.db.rag import get_embedding

def store_user_memory(
    user_id: str,
    content: str,
    memory_type: str = "FACT",
    metadata: dict = None,
    confidence: float = 1.0
) -> str:
    """
    Stores an episodic long-term memory for a user with vector embedding in PostgreSQL.
    """
    if not user_id or not content.strip():
        return ""

    embedding = get_embedding(content)
    meta_json = json.dumps(metadata or {})

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_memories (user_id, memory_type, content, metadata, embedding, confidence, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING id;
            """, (user_id, memory_type, content.strip(), meta_json, embedding, confidence))
            memory_id = cur.fetchone()[0]
            conn.commit()
            return str(memory_id)

def retrieve_user_memories(user_id: str, query: str = None, limit: int = 5) -> list[dict]:
    """
    Retrieves long-term episodic memories for a user.
    If query is provided, ranks by semantic cosine similarity.
    Otherwise, orders by recency (created_at DESC).
    """
    if not user_id:
        return []

    with get_connection() as conn:
        with conn.cursor() as cur:
            if query and query.strip():
                query_vec = get_embedding(query.strip())
                cur.execute("""
                    SELECT 
                        id, 
                        memory_type, 
                        content, 
                        metadata, 
                        1 - (embedding <=> %s::vector) AS similarity,
                        created_at
                    FROM user_memories
                    WHERE user_id = %s
                    ORDER BY embedding <=> %s::vector ASC
                    LIMIT %s;
                """, (query_vec, user_id, query_vec, limit))
            else:
                cur.execute("""
                    SELECT 
                        id, 
                        memory_type, 
                        content, 
                        metadata, 
                        1.0 AS similarity,
                        created_at
                    FROM user_memories
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s;
                """, (user_id, limit))

            rows = cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    "id": str(r[0]),
                    "memory_type": r[1],
                    "content": r[2],
                    "metadata": r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}"),
                    "similarity": float(r[4]) if r[4] is not None else 0.0,
                    "created_at": r[5].isoformat() if r[5] else ""
                })
            return results

def format_user_memories(memories: list[dict]) -> str:
    """
    Formats retrieved user memories into a concise context block for LLM prompts.
    """
    if not memories:
        return "No prior customer memory or account profile notes on record."

    lines = ["[Long-Term Customer Profile & Episodic History]:"]
    for m in memories:
        m_type = m.get("memory_type", "FACT").upper()
        content = m.get("content", "")
        lines.append(f"- [{m_type}]: {content}")
    return "\n".join(lines)
