import sys
import os

# Ensure services/ai is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.connection import init_db
from app.db.hybrid_search import seed_hierarchical_document

DOCUMENTS = [
    {
        "title": "Standard Cancellation and Refund Policy",
        "category": "cancellation_policy",
        "content": (
            "Standard consumer orders placed on the platform may be cancelled for a 100% full refund "
            "strictly within 24 hours of purchase, provided the package has not been handed over to the courier. "
            "When a cancellation request is submitted, the order state immediately transitions to PENDING_CANCELLATION "
            "while our automated warehouse systems verify the restock status. "
            "Once an order enters SHIPPED status, cancellation is no longer possible and the customer must initiate a standard 30-day RMA return upon delivery. "
            "Approved refunds are automatically credited back to the original payment method within 3 to 5 business days."
        ),
        "metadata": {"policy_id": "POL-101", "window_hours": 24, "type": "standard"}
    },
    {
        "title": "VIP Loyalty Member Extended Returns Policy",
        "category": "vip_policy",
        "content": (
            "VIP Loyalty Tiers (Gold, Platinum, and Diamond) receive special customer guarantees. "
            "Gold and Platinum VIP members enjoy an extended 30-day refund window, while top-tier Diamond VIP members "
            "receive an exclusive 60-day no-questions-asked return and full refund guarantee across all categories. "
            "In addition, all VIP members benefit from expedited zero-wait refund crediting directly to their bank or card, "
            "bypassing the standard banking processing delays. "
            "Restocking fees are permanently waived for all Gold, Platinum, and Diamond accounts across all categories."
        ),
        "metadata": {"policy_id": "POL-202", "diamond_window_days": 60, "gold_window_days": 30, "tiers": ["Gold", "Platinum", "Diamond"]}
    },

    {
        "title": "Electronics and Hardware Warranty Guidelines",
        "category": "warranty_policy",
        "content": (
            "Hardware products including Ergonomic Mechanical Keyboards (Product ID 5a6af266-4232-426b-8e20-193812043241) "
            "and Wireless Noise-Cancelling Headphones (Product ID 123e4567-e89b-12d3-a456-426614174000) "
            "include a 2-year complimentary manufacturer hardware warranty from date of purchase. "
            "Coverage includes internal switch failure, Bluetooth connectivity issues, and unexpected battery capacity drops below 80%. "
            "Physical abuse, intentional liquid immersion, and third-party modifications are not covered under the limited hardware warranty. "
            "To make a warranty claim, customers must provide the product serial number and original order purchase receipt."
        ),
        "metadata": {"policy_id": "POL-303", "warranty_years": 2, "category": "electronics", "claim_requirement": "serial_number_and_receipt"}

    },
    {
        "title": "High-Value Transaction and Human Supervisor Guardrails",
        "category": "security_policy",
        "content": (
            "To safeguard customer accounts against unauthorized transactions and fraud, "
            "refunds up to $500.00 USD can be processed and approved autonomously without supervisor authorization. "
            "Any order cancellation or refund exceeding $500.00 USD requires mandatory Human-in-the-Loop (HITL) supervisor authorization. "
            "AI agents are strictly forbidden from executing single financial modifications exceeding $500.00 autonomously. "
            "When high-risk actions exceeding $500.00 are initiated, the system pauses execution and generates a cryptographic approval ticket for review by an operations manager."
        ),
        "metadata": {"policy_id": "POL-404", "threshold_usd": 500, "hitl_required": True}
    }

]

def main():
    print("==========================================================")
    print("    Seeding Hierarchical Knowledge Base (Parent-Child)    ")
    print("==========================================================")
    init_db()

    from app.db.connection import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE knowledge_base_chunks, parent_documents CASCADE;")
            conn.commit()
    print("[Database] Cleaned existing parent and child document tables.")


    for doc in DOCUMENTS:
        parent_id = seed_hierarchical_document(
            title=doc["title"],
            full_content=doc["content"],
            category=doc["category"],
            metadata=doc["metadata"]
        )
        print(f"-> Seeded: '{doc['title']}' (Parent ID: {parent_id})")

    print("\nHierarchical Knowledge Base successfully seeded with child chunks and tsvectors!")

if __name__ == "__main__":
    main()
