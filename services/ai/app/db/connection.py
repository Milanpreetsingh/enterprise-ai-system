import psycopg_pool
from app.config import settings

pool = None

def init_db():
    """
    Initializes the PostgreSQL database connection pool and sets up tables:
    1. Installs the 'pgvector' extension.
    2. Scaffolds the 'knowledge_base' table for hybrid semantic RAG.
    3. Scaffolds the 'checkpoints' table for LangGraph conversation history.
    """
    global pool
    try:
        pool = psycopg_pool.ConnectionPool(
            conninfo=settings.DATABASE_URL,
            min_size=1,
            max_size=10,
            open=True
        )
        
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # 1. Enable pgvector extension
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                
                # 2. Create knowledge base table for vector indexing
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_base (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        content TEXT NOT NULL,
                        embedding VECTOR(1536) NOT NULL,
                        metadata JSONB
                    );
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS kb_embedding_idx 
                    ON knowledge_base USING hnsw (embedding vector_cosine_ops);
                """)
                
                # 3. Create checkpoints table for custom LangGraph checkpointer
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS checkpoints (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_id VARCHAR(255) NOT NULL,
                        parent_id VARCHAR(255),
                        checkpoint BYTEA NOT NULL,
                        metadata BYTEA,
                        PRIMARY KEY (thread_id, checkpoint_id)
                    );
                """)

                # 4. Create user_memories table for Long-Term Episodic Memory
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_memories (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id VARCHAR(64) NOT NULL,
                        memory_type VARCHAR(32) NOT NULL DEFAULT 'FACT',
                        content TEXT NOT NULL,
                        metadata JSONB DEFAULT '{}'::jsonb,
                        embedding VECTOR(1536),
                        confidence FLOAT DEFAULT 1.0,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_user_memories_user_id 
                    ON user_memories(user_id);
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_user_memories_embedding 
                    ON user_memories USING hnsw (embedding vector_cosine_ops);
                """)

                # 5. Create parent_documents table for Hierarchical Hybrid RAG
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS parent_documents (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        title VARCHAR(255) NOT NULL,
                        full_content TEXT NOT NULL,
                        category VARCHAR(64) NOT NULL,
                        metadata JSONB DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                # 6. Create knowledge_base_chunks table for Semantic Child Chunks + Sparse Search
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_base_chunks (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        parent_id UUID NOT NULL REFERENCES parent_documents(id) ON DELETE CASCADE,
                        chunk_content TEXT NOT NULL,
                        chunk_index INT NOT NULL,
                        embedding VECTOR(1536) NOT NULL,
                        tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', chunk_content)) STORED,
                        metadata JSONB DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_chunks_parent 
                    ON knowledge_base_chunks(parent_id);
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding 
                    ON knowledge_base_chunks USING hnsw (embedding vector_cosine_ops);
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_chunks_tsv 
                    ON knowledge_base_chunks USING gin (tsv);
                """)
                conn.commit()
        
        print("[Database] Successfully connected to PostgreSQL and initialized schemas!")
    except Exception as e:
        print(f"[Database] Connection or initialization failed: {e}")
        raise e

def get_connection():
    """Context manager or accessor returning a pooled database connection."""
    global pool
    if pool is None:
        init_db()
    return pool.connection()

