from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from app.db.connection import init_db
from app.agent.graph import compiled_graph

app = FastAPI(title="Enterprise AI Support Hub Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.db.cache import get_cached_answer, set_cached_answer, invalidate_cache, clean_legacy_cache
from app.observability import MeasureLatency

@app.on_event("startup")
def startup_event():
    # Connect to PostgreSQL and verify schema availability on start
    init_db()
    clean_legacy_cache()

class ChatRequest(BaseModel):
    message: str
    thread_id: str
    user_id: str = "anonymous"

class InvalidateCacheRequest(BaseModel):
    thread_id: str = None

class SeedRequest(BaseModel):
    title: Optional[str] = None
    content: str
    category: Optional[str] = None
    metadata: Optional[dict] = None

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/api/v1/cache/invalidate")
def invalidate_cache_api(req: InvalidateCacheRequest = InvalidateCacheRequest()):
    """
    Manually invalidates semantic cache entries.
    If thread_id is specified in the body, only that thread's cache is purged.
    Otherwise, all semantic cache entries across threads are purged.
    """
    deleted = invalidate_cache(thread_id=req.thread_id)
    return {
        "status": "success",
        "thread_id": req.thread_id,
        "deleted_count": deleted
    }

from app.agent.guardrails import check_security_violation, inspect_and_sanitize
from app.agent.mcp_client import current_user_id

@app.post("/api/v1/chat")
async def chat(req: ChatRequest):
    """
    Executes the 3-Tier Enterprise AI multi-turn agentic workflow with semantic caching.
    - Tier 1: Guardrail & Hard Security Boundary (Secret/Prompt-injection rejection)
    - Tier 2: Safe/Low-Risk Autonomous Tool Execution
    - Tier 3: High-Impact Human-in-the-Loop Interrupt & Supervisor Approval
    """
    if not req.message or not req.thread_id:
        raise HTTPException(
            status_code=400, 
            detail="Missing required parameters: message and thread_id"
        )

    # Bind authenticated user ID into ContextVar for MCP tool execution
    current_user_id.set(req.user_id or "anonymous")

    # 0. Tier 1: Security Guardrail & Hard Boundary Check with Live Telemetry
    with MeasureLatency("Live_Security_Guardrails"):
        is_violation, refusal_msg = check_security_violation(req.message)
        if is_violation:
            return {
                "status": "blocked",
                "response": refusal_msg,
                "thread_id": req.thread_id,
                "role": "system",
                "cache_hit": False
            }
        sanitized_msg, warnings = inspect_and_sanitize(req.message)
        req.message = sanitized_msg

    # 1. Check Semantic Cache within this thread namespace with Live Telemetry
    with MeasureLatency("Live_Semantic_Cache_Lookup"):
        cached_hit = get_cached_answer(req.message, thread_id=req.thread_id)
        if cached_hit:
            return {
                "response": cached_hit["answer"],
                "thread_id": req.thread_id,
                "role": "ai",
                "cache_hit": True,
                "similarity": cached_hit["similarity"]
            }

    try:
        # 2. Invalidate stale cache for this thread as new conversational turn advances state
        invalidate_cache(thread_id=req.thread_id)

        config = {"configurable": {"thread_id": req.thread_id}}
        
        inputs = {
            "messages": [HumanMessage(content=req.message)],
            "user_id": req.user_id,
            "thread_id": req.thread_id
        }
        
        state = None
        # Stream graph updates until final state resolves with Live Telemetry
        with MeasureLatency("Live_LangGraph_Execution"):
            async for s in compiled_graph.astream(inputs, config=config, stream_mode="values"):
                state = s
            
        if not state or not state.get("messages"):
            raise HTTPException(status_code=500, detail="AI Graph failed to produce a response message")
            
        final_message = state["messages"][-1]

        # 3. Check if graph execution paused due to Tier 3 Human-in-the-Loop interrupt
        graph_state = compiled_graph.get_state(config)
        if graph_state.next and any(node in ("sensitive_tools", "tools") for node in graph_state.next):
            tool_calls = getattr(final_message, "tool_calls", [])
            tool_names = [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in tool_calls]
            return {
                "status": "interrupted",
                "message": f"Action requires human supervisor approval to execute tool(s): {', '.join(tool_names)}",
                "thread_id": req.thread_id,
                "tool_calls": tool_calls,
                "role": "ai",
                "cache_hit": False
            }

        response_text = final_message.content

        # 4. Save generated answer into Redis Semantic Cache for this thread (exclude refusals & errors)
        if response_text and response_text.strip():
            refusal_markers = ["access denied", "not authorized", "another customer", "internal processing error", "failed"]
            if not any(marker in response_text.lower() for marker in refusal_markers):
                set_cached_answer(req.message, response_text, thread_id=req.thread_id)

        return {
            "response": response_text,
            "thread_id": req.thread_id,
            "role": final_message.type,
            "cache_hit": False
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[CHAT ERROR] {type(e).__name__}: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"Graph execution failed: [{type(e).__name__}] {e} | Traceback: {tb}")

@app.post("/api/v1/seed")
@app.post("/api/v1/rag/seed")
def seed(req: SeedRequest):
    """
    Ingests a support document into the Hierarchical Hybrid RAG pipeline.
    Stores the full parent document in parent_documents, and generates
    semantically aligned child chunks in knowledge_base_chunks for dense vector + BM25 search.
    """
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="Content field is required")
    try:
        from app.db.hybrid_search import seed_hierarchical_document

        # Derive title: explicit -> metadata -> first sentence/line -> fallback
        title = req.title or (req.metadata.get("title") if req.metadata else None)
        if not title:
            first_line = req.content.strip().split("\n")[0].strip()
            first_line = first_line.rstrip(".:;")
            title = first_line[:70] if len(first_line) > 70 else first_line
            if not title:
                title = "Company Support Policy"

        # Derive category: explicit -> metadata -> fallback
        category = req.category or (req.metadata.get("category") if req.metadata else None) or "policy"

        parent_id = seed_hierarchical_document(
            title=title,
            full_content=req.content.strip(),
            category=category,
            metadata=req.metadata
        )
        return {
            "status": "success",
            "id": parent_id,
            "parent_id": parent_id,
            "title": title,
            "category": category
        }
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[SEED ERROR] {type(e).__name__}: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"Failed to seed hierarchical document: {e}")

class RagQueryRequest(BaseModel):
    query: str
    limit: int = 3

@app.post("/api/v1/rag/query")
def query_rag_endpoint(req: RagQueryRequest):
    """
    Directly query the Hierarchical Hybrid RAG pipeline to inspect dense+sparse RRF matches
    and Cross-Encoder joint attention re-ranking scores.
    """
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="Query field is required")
    from app.db.hybrid_search import query_hierarchical_rag
    results = query_hierarchical_rag(req.query.strip(), top_parents=req.limit)
    formatted = []
    for r in results:
        formatted.append({
            "id": r["parent_id"],
            "title": r.get("title", "Policy Document"),
            "content": r.get("content", ""),
            "matched_snippet": r.get("matched_snippet", ""),
            "rerank_score": r.get("rerank_score", 0.0),
            "rrf_score": r.get("rrf_score", 0.0),
            "metadata": {
                "title": r.get("title", ""),
                "rank_dense": r.get("rank_dense", 999),
                "rank_sparse": r.get("rank_sparse", 999),
                "category": "policy"
            }
        })
    return {"query": req.query, "results": formatted}

@app.get("/api/v1/rag/docs")
def list_knowledge_docs(limit: int = 50):
    """
    Retrieves all knowledge base documents currently stored in PostgreSQL parent_documents
    along with their semantic child chunk counts from knowledge_base_chunks.
    """
    import json
    from app.db import connection
    with connection.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.id, p.title, p.full_content, p.category, p.metadata,
                       COUNT(c.id) AS chunk_count
                FROM parent_documents p
                LEFT JOIN knowledge_base_chunks c ON c.parent_id = p.id
                GROUP BY p.id, p.title, p.full_content, p.category, p.metadata, p.created_at
                ORDER BY p.created_at DESC
                LIMIT %s;
            """, (limit,))
            rows = cur.fetchall()
            results = []
            for r in rows:
                meta = r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}")
                results.append({
                    "id": str(r[0]),
                    "title": r[1],
                    "content": r[2],
                    "category": r[3],
                    "chunk_count": r[5],
                    "metadata": {**meta, "category": r[3], "chunk_count": r[5]}
                })
            return {"documents": results, "count": len(results)}

class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool = True

@app.post("/api/v1/agent/approve")
async def approve_tool_execution(req: ApproveRequest):
    """
    Human-in-the-Loop (HITL) approval endpoint. Resumes graph execution
    for an interrupted thread state upon supervisor authorization.
    """
    if not req.thread_id:
        raise HTTPException(status_code=400, detail="Missing required parameter: thread_id")

    config = {"configurable": {"thread_id": req.thread_id}}
    
    try:
        graph_state = compiled_graph.get_state(config)
        if not graph_state.values or not graph_state.values.get("messages"):
            raise HTTPException(status_code=404, detail=f"No conversation state found for thread_id: {req.thread_id}")

        if not req.approved:
            return {
                "status": "rejected",
                "thread_id": req.thread_id,
                "message": "Tool execution was rejected by human supervisor."
            }

        if not graph_state.next:
            final_msg = graph_state.values["messages"][-1]
            return {
                "status": "already_completed",
                "thread_id": req.thread_id,
                "message": "Thread has no pending tool execution awaiting approval.",
                "response": final_msg.content,
                "role": final_msg.type
            }

        # Resume state machine execution from the interrupted state (passing None)
        state = None
        async for s in compiled_graph.astream(None, config=config, stream_mode="values"):
            state = s
            
        if not state or not state.get("messages"):
            raise HTTPException(status_code=500, detail="Failed to resume graph execution")

        final_msg = state["messages"][-1]
        response_text = final_msg.content

        # Cache final answer for subsequent duplicate queries in this thread
        if response_text and response_text.strip():
            human_msg = next((m.content for m in reversed(state["messages"]) if m.type == "human"), "")
            if human_msg:
                set_cached_answer(human_msg, response_text, thread_id=req.thread_id)

        return {
            "status": "resumed",
            "thread_id": req.thread_id,
            "response": response_text,
            "role": final_msg.type
        }
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[APPROVE ERROR] {type(e).__name__}: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"Failed to resume graph thread: {e}")
