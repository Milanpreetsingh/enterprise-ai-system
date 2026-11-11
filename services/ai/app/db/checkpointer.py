import pickle
from typing import Iterator, Optional
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata, CheckpointTuple
from langchain_core.runnables import RunnableConfig
from app.db import connection

class PostgresCheckpointSaver(BaseCheckpointSaver):
    """
    A custom LangGraph Checkpoint Saver that persists conversational state 
    directly into a PostgreSQL database using pickle binary serialization.
    This enables full multi-turn chat memory across stateless server restarts.
    """
    
    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """
        Retrieves a checkpoint by thread_id and optionally checkpoint_id.
        """
        thread_id = config["configurable"].get("thread_id")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        with connection.pool.connection() as conn:
            with conn.cursor() as cur:
                if checkpoint_id:
                    cur.execute(
                        """
                        SELECT checkpoint, metadata, parent_id 
                        FROM checkpoints 
                        WHERE thread_id = %s AND checkpoint_id = %s;
                        """,
                        (thread_id, checkpoint_id)
                    )
                else:
                    # Fetch the latest checkpoint for the given conversation thread
                    cur.execute(
                        """
                        SELECT checkpoint, metadata, parent_id, checkpoint_id 
                        FROM checkpoints 
                        WHERE thread_id = %s 
                        ORDER BY checkpoint_id DESC 
                        LIMIT 1;
                        """,
                        (thread_id,)
                    )
                row = cur.fetchone()
                if not row:
                    return None
                
                checkpoint = pickle.loads(row[0])
                metadata = pickle.loads(row[1])
                parent_id = row[2]
                cp_id = checkpoint_id if checkpoint_id else row[3]
                
                return CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_id": cp_id
                        }
                    },
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_id": parent_id
                        }
                    } if parent_id else None
                )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions,           # LangGraph 1.x: new required 4th argument
    ) -> RunnableConfig:
        """
        Saves a checkpoint for a thread_id.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint["id"]
        parent_id = config["configurable"].get("checkpoint_id")

        checkpoint_bytes = pickle.dumps(checkpoint)
        metadata_bytes = pickle.dumps(metadata)

        with connection.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO checkpoints (thread_id, checkpoint_id, parent_id, checkpoint, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (thread_id, checkpoint_id) DO UPDATE 
                    SET checkpoint = EXCLUDED.checkpoint, metadata = EXCLUDED.metadata;
                    """,
                    (thread_id, checkpoint_id, parent_id, checkpoint_bytes, metadata_bytes)
                )
                conn.commit()

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id
            }
        }

    def put_writes(self, config: RunnableConfig, writes, task_id: str) -> None:
        """
        LangGraph 1.x: Required method for persisting intermediate node writes
        within a single graph step. Not needed for our basic checkpoint use case.
        """
        pass

    # ── Async versions required by LangGraph 1.x astream ──────────────────────

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Async wrapper — runs sync get_tuple in a thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_tuple, config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions,
    ) -> RunnableConfig:
        """Async wrapper — runs sync put in a thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: RunnableConfig, writes, task_id: str) -> None:
        """Async no-op — intermediate writes not persisted."""
        pass

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None
    ) -> Iterator[CheckpointTuple]:
        """
        Lists checkpoints. Not used by simple agent execution loop.
        """
        return iter([])

