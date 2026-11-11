# SENSITIVE_TOOLS defines high-stakes mutations requiring Human-in-the-Loop approval
SENSITIVE_TOOLS = {
    "cancel_order",
    "request_refund",
    "process_refund",
    "delete_account",
    "transfer_funds",
}

# POLICY_KEYWORDS routes general customer questions directly to the Knowledge Base
POLICY_KEYWORDS = [
    "refund",
    "return",
    "policy",
    "cancellation",
    "warranty",
    "shipping",
    "faq",
    "eligible",
]

# MCP Server Defaults
DEFAULT_MCP_URL = "http://localhost:8080/api/v1/mcp"
