import os
import sys
import asyncio
from langchain_core.messages import HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.connection import init_db

async def run_scenario(name, query, user_id, thread_id):
    from app.agent.graph import compiled_graph
    print(f"\n{'='*25} Scenario: {name} {'='*25}")
    print(f"Query: '{query}' | User: {user_id[:8]}... | Thread: {thread_id}")

    inputs = {
        "messages": [HumanMessage(content=query)],
        "user_id": user_id,
        "thread_id": thread_id
    }
    config = {"configurable": {"thread_id": thread_id}}

    async for s in compiled_graph.astream(inputs, config=config, stream_mode="values"):
        if "messages" in s and s["messages"]:
            m = s["messages"][-1]
            m_type = type(m).__name__
            tool_calls = getattr(m, "tool_calls", None)
            tool_name = getattr(m, "name", "")
            preview = str(m.content)[:120].replace('\n', ' ')
            print(f"-> [{m_type}] {tool_name} tc={tool_calls} content: {preview}")

async def main():
    init_db()
    diamond_user = "6f07dc9c-7d22-4630-8c78-70d5bf72e3b3"

    # Scenario 1: Direct Greeting
    await run_scenario("Direct Greeting", "Hello, good morning!", diamond_user, "thread-greet-test")

    # Scenario 2: Escalation to Supervisor Desk
    await run_scenario("Supervisor Escalation", "This is unacceptable! Connect me to a supervisor right now.", diamond_user, "thread-esc-test")

    # Scenario 3: Diamond VIP Policy Question
    await run_scenario("Policy Specialist QA", "Can I return an item after 40 days as a Diamond member?", diamond_user, "thread-policy-test")

    # Scenario 4: Order Status Lookup
    await run_scenario("Order Operations Lookup", "What is the status of my order 5a6af266-4232-426b-8e20-193812042952?", diamond_user, "thread-order-test")

if __name__ == "__main__":
    asyncio.run(main())
