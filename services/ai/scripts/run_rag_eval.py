import os
import sys
import json
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.connection import init_db
from app.db.hybrid_search import query_hierarchical_rag
from app.eval.rag_triad import evaluate_rag_triad
from app.observability import log_eval_metric

async def evaluate_test_case(name: str, query: str, user_id: str = "6f07dc9c-7d22-4630-8c78-70d5bf72e3b3"):
    from app.agent.graph import compiled_graph
    from langchain_core.messages import HumanMessage

    print(f"\n{'='*25} Evaluating: {name} {'='*25}")
    print(f"Query: \"{query}\"")

    # 1. Retrieve Context using Phase 2 Hierarchical Hybrid Engine
    retrieved_docs = query_hierarchical_rag(query, top_parents=2)
    contexts = [f"Title: {d['title']}\n{d['content']}" for d in retrieved_docs]
    print(f"[Retrieval] Retrieved {len(contexts)} parent documents.")

    # 2. Generate Agent Response using Phase 3 Multi-Agent State Machine
    thread_id = f"eval-thread-{name.lower().replace(' ', '-')}"
    inputs = {
        "messages": [HumanMessage(content=query)],
        "user_id": user_id,
        "thread_id": thread_id
    }
    config = {"configurable": {"thread_id": thread_id}}

    agent_response = ""
    async for s in compiled_graph.astream(inputs, config=config, stream_mode="values"):
        if "messages" in s and s["messages"]:
            m = s["messages"][-1]
            if type(m).__name__ == "AIMessage" and not getattr(m, "tool_calls", None):
                agent_response = str(m.content)

    print(f"[Agent Response]:\n{agent_response[:200]}...")

    # 3. Evaluate RAG Triad Metrics
    eval_result = evaluate_rag_triad(query=query, contexts=contexts, answer=agent_response)

    print(f"\n--- RAG Triad Scores for [{name}] ---")
    print(f"1. Context Relevance: {eval_result['context_relevance']['score']:.2f} | Reason: {eval_result['context_relevance']['reasoning']}")
    print(f"2. Groundedness (Faithfulness): {eval_result['groundedness']['score']:.2f} | Reason: {eval_result['groundedness']['reasoning']}")
    print(f"3. Answer Relevance:  {eval_result['answer_relevance']['score']:.2f} | Reason: {eval_result['answer_relevance']['reasoning']}")
    print(f"-> Composite Score:    {eval_result['composite_score']:.2f} | Result: {'PASSED ✅' if eval_result['passed'] else 'FAILED ❌'}")

    # 4. Log Structured Observability Telemetry
    log_eval_metric(
        test_name=name,
        passed=eval_result["passed"],
        details={
            "query": query,
            "composite_score": eval_result["composite_score"],
            "context_relevance": eval_result["context_relevance"]["score"],
            "groundedness": eval_result["groundedness"]["score"],
            "answer_relevance": eval_result["answer_relevance"]["score"]
        }
    )

    return eval_result

async def main():
    init_db()

    test_cases = [
        ("VIP Diamond Return Policy", "What is the return window and refund policy for Diamond tier members?"),
        ("Electronics Hardware Warranty", "What is the warranty period for consumer electronics and what is required to make a claim?"),
        ("High-Value Refund Guardrails", "What is the maximum refund limit that can be approved without supervisor authorization?"),
    ]

    results = []
    for name, query in test_cases:
        res = await evaluate_test_case(name, query)
        results.append((name, res))

    print("\n" + "="*60)
    print("                RAG TRIAD EVALUATION SUMMARY")
    print("="*60)
    for name, res in results:
        status = "PASSED ✅" if res["passed"] else "FAILED ❌"
        print(f"• {name:32} | Score: {res['composite_score']:.2f} | {status}")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
