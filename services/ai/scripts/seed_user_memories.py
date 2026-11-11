import os
import sys

# Ensure services/ai is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.connection import init_db
from app.db.memory_store import store_user_memory, retrieve_user_memories, format_user_memories

def seed_memories():
    print("--- Initializing Database & Schemas ---")
    init_db()

    user_diamond = "6f07dc9c-7d22-4630-8c78-70d5bf72e3b3"
    user_standard = "b62f7a89-929a-4ffc-b1fb-e17351665f1c"

    memories_to_seed = [
        # Diamond VIP User
        (user_diamond, "Customer is a verified Diamond VIP Loyalty Member with active account since 2022. Eligible for 60-day return window, waived restocking fees, and dedicated priority supervisor support.", "TIER_STATUS", {"tier": "DIAMOND", "return_window_days": 60}),
        (user_diamond, "Customer strictly prefers immediate full refunds back to original credit card rather than store credit or gift vouchers.", "PREFERENCE", {"refund_preference": "original_payment"}),
        (user_diamond, "Customer experienced previous shipping delays on high-value electronics and was flagged for proactive priority handling.", "INCIDENT", {"priority": "HIGH"}),

        # Standard User
        (user_standard, "Customer is a Standard Tier shopper with standard 24-hour order cancellation window.", "TIER_STATUS", {"tier": "STANDARD"}),
        (user_standard, "Customer prefers SMS notifications over email.", "PREFERENCE", {"channel": "SMS"}),
    ]

    print("\n--- Seeding User Episodic Memories ---")
    for user_id, content, m_type, meta in memories_to_seed:
        mem_id = store_user_memory(user_id=user_id, content=content, memory_type=m_type, metadata=meta)
        print(f"Stored [{m_type}] memory (id={mem_id}) for user {user_id[:8]}...")

    print("\n--- Verifying Retrieval & Semantic Ranking for Diamond User ---")
    retrieved = retrieve_user_memories(user_diamond, query="What is the customer's loyalty tier and refund preference?")
    print(format_user_memories(retrieved))

if __name__ == "__main__":
    seed_memories()
