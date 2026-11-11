import asyncio
import os
import sys

# Ensure services/ai is on sys.path regardless of how script is executed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import grpc
from langchain_core.messages import HumanMessage
from app.agent.graph import compiled_graph
from app.agent.guardrails import (
    check_security_violation,
    inspect_and_sanitize,
    semantic_guardrail_check,
    inspect_and_sanitize_output
)
from app.db.cache import get_cached_answer, set_cached_answer, invalidate_cache
from app.observability import MeasureLatency
from app.agent.mcp_client import current_user_id
import app.aipb.ai_pb2 as ai_pb2
import app.aipb.ai_pb2_grpc as ai_pb2_grpc

class AIServiceServicer(ai_pb2_grpc.AIServiceServicer):
    """
    gRPC Server Handler for AIService StreamChat RPC.
    Executes real-time token streaming using LangGraph's astream events.
    """
    async def StreamChat(self, request: ai_pb2.ChatStreamRequest, context):
        message = request.message
        thread_id = request.thread_id or "default-thread"
        user_id = request.user_id or "anonymous"

        # Bind authenticated user ID into ContextVar for MCP tool execution
        current_user_id.set(user_id)

        # 1. Dual-LLM Guardrails check with Live Observability
        with MeasureLatency("Stream_Security_Guardrails"):
            # Tier 1 Heuristic Regex Check
            is_violation, refusal_msg = check_security_violation(message)
            if is_violation:
                for word in refusal_msg.split(" "):
                    yield ai_pb2.ChatStreamResponse(token=word + " ", is_final=False)
                    await asyncio.sleep(0.01)
                yield ai_pb2.ChatStreamResponse(token="", is_final=True)
                return

            # Tier 2 Semantic Model Guardrail Check
            is_semantic_violation, semantic_refusal = semantic_guardrail_check(message)
            if is_semantic_violation:
                for word in semantic_refusal.split(" "):
                    yield ai_pb2.ChatStreamResponse(token=word + " ", is_final=False)
                    await asyncio.sleep(0.01)
                yield ai_pb2.ChatStreamResponse(token="", is_final=True)
                return


            sanitized_msg, warnings = inspect_and_sanitize(message)
            message = sanitized_msg
            if warnings:
                print(f"[gRPC Guardrail Warnings]: {warnings}")


        # 2. Check Redis Semantic Cache for this thread namespace
        cached_hit = get_cached_answer(message, thread_id=thread_id)
        if cached_hit:
            print(f"[gRPC Server] Semantic Cache Hit for stream: '{message}' (thread: {thread_id})")
            words = cached_hit["answer"].split(" ")
            for i, word in enumerate(words):
                token_chunk = word + (" " if i < len(words) - 1 else "")
                yield ai_pb2.ChatStreamResponse(token=token_chunk, is_final=False)
                await asyncio.sleep(0.01) # Sub-15ms chunk delivery
            yield ai_pb2.ChatStreamResponse(token="", is_final=True)
            return

        # 3. Invalidate stale cache for this thread as new conversational turn advances state
        invalidate_cache(thread_id=thread_id)

        # 4. Cache Miss: Execute LangGraph with astream for state resolution & token streaming
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {
            "messages": [HumanMessage(content=message)],
            "user_id": user_id,
            "thread_id": thread_id
        }

        full_response = ""
        try:
            state = None
            with MeasureLatency("Stream_LangGraph_Execution"):
                async for s in compiled_graph.astream(inputs, config=config, stream_mode="values"):
                    state = s

            if state and state.get("messages"):
                final_msg = state["messages"][-1]

                # 5. Check if graph execution paused due to Tier 3 Human-in-the-Loop breakpoint
                graph_state = compiled_graph.get_state(config)
                if graph_state.next and any(node in ("sensitive_tools", "tools") for node in graph_state.next):
                    tool_calls = getattr(final_msg, "tool_calls", [])
                    tool_names = [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in tool_calls]
                    interrupt_msg = f"⚠️ [Human-in-the-Loop Interruption]: Action requires human supervisor approval to execute tool(s): {', '.join(tool_names)}."
                    words = interrupt_msg.split(" ")
                    for i, word in enumerate(words):
                        token_chunk = word + (" " if i < len(words) - 1 else "")
                        yield ai_pb2.ChatStreamResponse(token=token_chunk, is_final=False)
                        await asyncio.sleep(0.01)
                    yield ai_pb2.ChatStreamResponse(token="", is_final=True)
                    return

                full_response = final_msg.content or ""
                if not full_response.strip():
                    full_response = "No response generated by AI model."

                # Tier 3 Data Loss Prevention (DLP) Output Guardrail
                full_response = inspect_and_sanitize_output(full_response)


                # Stream the final response in word chunks to simulate typewriter streaming
                words = full_response.split(" ")
                for i, word in enumerate(words):
                    token_chunk = word + (" " if i < len(words) - 1 else "")
                    yield ai_pb2.ChatStreamResponse(token=token_chunk, is_final=False)
                    await asyncio.sleep(0.02)
                yield ai_pb2.ChatStreamResponse(token="", is_final=True)
        except Exception as e:
            print(f"[gRPC Server] Error streaming events: {e}")
            yield ai_pb2.ChatStreamResponse(token=f"Error: {e}", is_final=True)
            return

        # Cache the generated response for subsequent duplicate queries in this thread
        if full_response and full_response.strip() and not full_response.startswith("Error:"):
            set_cached_answer(message, full_response, thread_id=thread_id)

async def serve_grpc():
    """
    Starts the asynchronous gRPC server listening on port :50053.
    """
    from app.db.connection import init_db
    init_db()

    port = os.getenv("GRPC_PORT", "50053")
    server = grpc.aio.server()
    
    # Register the AIServiceServicer with the gRPC server using compiled stubs
    ai_pb2_grpc.add_AIServiceServicer_to_server(AIServiceServicer(), server)
    
    listen_addr = f"[::]:{port}"
    server.add_insecure_port(listen_addr)
    print(f"[gRPC Server] Python AI Service gRPC server listening on {listen_addr}...")
    await server.start()
    await server.wait_for_termination()

if __name__ == "__main__":
    asyncio.run(serve_grpc())
