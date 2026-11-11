import uuid
from datetime import datetime
from langchain_core.tools import tool

@tool
def create_support_ticket(title: str, description: str, category: str = "BILLING_DISPUTE") -> str:
    """
    Creates an official enterprise support tracking ticket for unresolved issues or manual intervention.
    """
    ticket_id = f"TICKET-{str(uuid.uuid4())[:8].upper()}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"[Support Desk Ticket Generated]\n"
        f"Ticket ID: {ticket_id}\n"
        f"Category: {category}\n"
        f"Title: {title}\n"
        f"Description: {description}\n"
        f"Status: OPEN - PENDING SUPERVISOR TRIAGE\n"
        f"Timestamp: {timestamp}\n"
        f"Note: An enterprise representative will follow up within 2 business hours."
    )

@tool
def escalate_to_human_supervisor(ticket_reason: str, urgency: str = "HIGH") -> str:
    """
    Escalates high-friction disputes, Diamond VIP exceptions, or policy appeals directly to a live human supervisor.
    """
    escalation_ref = f"ESC-{str(uuid.uuid4())[:6].upper()}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"[Live Supervisor Handoff Queued]\n"
        f"Escalation Reference: {escalation_ref}\n"
        f"Reason: {ticket_reason}\n"
        f"Urgency Level: {urgency.upper()}\n"
        f"Timestamp: {timestamp}\n"
        f"Status: Routed to Priority Operations Desk. A senior supervisor has joined the monitoring channel."
    )
