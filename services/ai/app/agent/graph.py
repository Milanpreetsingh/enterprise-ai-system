import asyncio
import json
import re
from datetime import datetime
from typing import Literal
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from app.config import settings
from app.db.checkpointer import PostgresCheckpointSaver
from app.db.hybrid_search import query_hierarchical_rag
from app.db.memory_store import retrieve_user_memories, format_user_memories
from app.agent.state import AgentState
from app.agent.mcp_client import fetch_mcp_tools, current_user_id
from app.agent.escalation_tools import create_support_ticket, escalate_to_human_supervisor
from app.agent.guardrails import inspect_and_sanitize
from app.agent.constants import SENSITIVE_TOOLS, POLICY_KEYWORDS, DEFAULT_MCP_URL

# ── 1. Tool Setup ─────────────────────────────────────────────────────────────
@tool
def mock_mcp_tool(id: str) -> str:
    """A fallback placeholder tool used when the API Gateway is offline."""
    return f"[Mock Fallback Tool] Gateway offline. Searched context ID: {id}"

# Expose Hierarchical Hybrid RAG tool
@tool
def lookup_knowledge_base(query: str) -> str:
    """Search company knowledge base using Hybrid RRF (dense vector + sparse keyword) and Cross-Encoder re-ranking."""
    docs = query_hierarchical_rag(query, top_parents=2)
    if not docs:
        return "No relevant company policy documents found in the knowledge base."
    return "\n\n".join([f"### {doc['title']}\n{doc['content']}" for doc in docs])

# Fetch Order Tools dynamically from API Gateway MCP Server
mcp_tools = fetch_mcp_tools(DEFAULT_MCP_URL)
if not mcp_tools:
    mcp_tools = [mock_mcp_tool]

# Segregate tools by Specialist Domain
order_tools = mcp_tools
policy_tools = [lookup_knowledge_base]
escalation_tools = [create_support_ticket, escalate_to_human_supervisor]

# Safe order tools include lookups and instant refunds <= $100
safe_order_tool_list = [t for t in order_tools if t.name != "cancel_order"]
# Sensitive order tools include cancel_order and supervisor-gated refunds > $100
sensitive_order_tool_list = [t for t in order_tools if t.name in SENSITIVE_TOOLS or t.name == "process_refund"]
if not sensitive_order_tool_list:
    sensitive_order_tool_list = order_tools
if not safe_order_tool_list:
    safe_order_tool_list = order_tools

# ── 2. LLM Model Factory ─────────────────────────────────────────────────────
def get_llm():
    if settings.GROQ_API_KEY:
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=settings.GROQ_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=0.1
        )
    if settings.OPENAI_API_KEY:
        return ChatOpenAI(model="gpt-4o", openai_api_key=settings.OPENAI_API_KEY, temperature=0.1)
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.1
    )

# ── 3. Memory Injector Node ──────────────────────────────────────────────────
def memory_injector_node(state: AgentState):
    """
    Tiered Memory System: Injects long-term episodic memories for the user
    retrieved from PostgreSQL pgvector into the conversation context.
    """
    user_id = state.get("user_id") or "anonymous"
    messages = state.get("messages", [])
    last_human_msg = next((m.content for m in reversed(messages) if m.type == "human"), "")

    sanitized_input, warnings = inspect_and_sanitize(last_human_msg)
    if warnings:
        print(f"[Guardrails Warning] Sanitized user input: {warnings}")

    memories = retrieve_user_memories(user_id=user_id, query=sanitized_input, limit=3)
    memory_context = format_user_memories(memories)

    return {
        "user_memories": memory_context,
        "findings": [],
        "is_multi_intent": False,
        "plan_tasks": []
    }

# ── 4. Master Supervisor Router Node (Hybrid Architecture) ───────────────────
def _decompose_compound_query(text: str) -> list[dict]:
    """
    Decomposes a compound multi-intent customer inquiry into discrete sub-tasks
    for our specialist departments.
    """
    try:
        prompt = (
            "You are the Enterprise Multi-Agent Task Planner.\n"
            f"Customer Inquiry: \"{text}\"\n\n"
            "Decompose this inquiry into 2 to 3 discrete sub-tasks for our specialist departments:\n"
            "- order_specialist: For checking order status, tracking shipments, order lookups, cancellations, or refunds on an order.\n"
            "- policy_specialist: For company rules, return window policies, warranty, liquid damage, loyalty benefits.\n"
            "- escalation_specialist: For severe complaints, support tickets, manager escalations.\n\n"
            "Output ONLY a valid JSON list of objects in this exact format:\n"
            '[\n  {"agent": "order_specialist", "sub_query": "specific sub-question"},\n  {"agent": "policy_specialist", "sub_query": "specific sub-question"}\n]'
        )
        llm = get_llm()
        resp = llm.invoke([SystemMessage(content=prompt)]).content.strip()
        match = re.search(r'\[.*\]', resp, re.DOTALL)
        if match:
            tasks = json.loads(match.group(0))
            if isinstance(tasks, list) and len(tasks) >= 2:
                valid_agents = {"order_specialist", "policy_specialist", "escalation_specialist"}
                cleaned = [t for t in tasks if isinstance(t, dict) and t.get("agent") in valid_agents and t.get("sub_query")]
                if len(cleaned) >= 2:
                    return cleaned
    except Exception as e:
        print(f"[Orchestrator Decomposer Warning] Decomposition failed: {e}")
    return []


def _semantic_llm_router(messages: list) -> str:
    """
    Stage 3 Semantic Fallback: Uses fast LLM classification to resolve ambiguous,
    slang, or compound customer inquiries that evade deterministic keyword patterns.
    """
    try:
        recent_dialogue = []
        for m in messages[-4:]:
            speaker = "Customer" if m.type == "human" else "Assistant"
            content = m.content if isinstance(m.content, str) else str(m.content)
            recent_dialogue.append(f"{speaker}: {content[:150]}")
        dialogue_text = "\n".join(recent_dialogue)

        prompt = (
            "You are the Master Routing Dispatcher for an enterprise customer support platform.\n"
            "Classify the customer's latest request into EXACTLY ONE category:\n"
            "- ORDER: Order status tracking, package/parcel delivery, cancellations, item lookups, refund processing for an order.\n"
            "- POLICY: General company rules, return window policies, warranty, VIP benefits, hours, FAQ.\n"
            "- ESCALATION: Severe complaints, anger, demands for a human supervisor, legal disputes, fraud.\n"
            "- DIRECT: General greetings, pleasantries, questions about user's personal memory (name, job, location), conversational chat.\n\n"
            f"Recent Conversation:\n{dialogue_text}\n\n"
            "Respond ONLY with one word: ORDER, POLICY, ESCALATION, or DIRECT."
        )

        llm = get_llm()
        resp = llm.invoke([SystemMessage(content=prompt)])
        category = resp.content.strip().upper()

        if "ORDER" in category:
            return "order_specialist"
        elif "POLICY" in category:
            return "policy_specialist"
        elif "ESCALATION" in category:
            return "escalation_specialist"
        else:
            return "direct_response"
    except Exception as e:
        print(f"[Supervisor Router Warning] Semantic routing fallback failed: {e}. Defaulting to direct_response.")
        return "direct_response"


def supervisor_router_node(state: AgentState):
    """
    Hybrid Multi-Agent Supervisor:
    - Stage 0 (<0.05ms): Multi-Intent Compound Inquiry Detector with Structured LLM Decomposition.
    - Stage 1 (<0.1ms): Deterministic fast-path regex and keyword matrices for instant zero-cost routing.
    - Stage 2 (<0.5ms): Multi-turn conversational context resolver (handles affirmative follow-ups like 'Yes please cancel it').
    - Stage 3 (~50ms): Fast semantic LLM classifier fallback for nuanced, ambiguous, or slang inquiries.
    """
    messages = state.get("messages", [])
    print("state",state)
    print("messages in supervisor_router_node: ",messages)
    if not messages:
        return {"active_agent": "direct_response", "is_multi_intent": False}

    last_human_msg = next((m.content for m in reversed(messages) if m.type == "human"), "")
    text = last_human_msg.lower().strip()
    clean_text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text)

    # ── STAGE 0: Fast Heuristic Multi-Intent Detector (<0.05ms) ───────────
    has_uuid = bool(re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}', text))
    has_order_domain = has_uuid or any(phrase in text for phrase in [
        "order status", "cancel order", "cancel my order", "cancel this order", "track order",
        "track package", "track parcel", "track shipment", "where is my order", "where is my package",
        "where is my parcel", "shipping status", "delivery status", "cancel the order", "cancel shipment"
    ]) or (("order" in clean_text or "purchase" in clean_text or "package" in clean_text or "parcel" in clean_text) and any(v in clean_text for v in ["status", "cancel", "track", "tracking", "where", "delivered", "refund", "return", "ship"]))

    policy_markers = POLICY_KEYWORDS + [
        "diamond", "vip", "limit", "warranty", "authorization", "rules", "terms",
        "exchange", "fee", "cost", "hours", "return policy", "refund policy",
        "cancellation policy", "shipping policy"
    ]
    has_policy_domain = any(re.search(r'\b' + re.escape(kw) + r'\b', clean_text) for kw in policy_markers)

    complaint_markers = [
        "unacceptable", "terrible", "horrible", "dispute", "lawyer", "sue", "file a complaint", "escalate", "fraud", "scam",
        "connect to a supervisor", "speak to a supervisor", "talk to a manager", "human agent"
    ]
    has_escalation_domain = any(re.search(r'\b' + re.escape(kw) + r'\b', clean_text) for kw in complaint_markers)

    has_conjunction = bool(re.search(r'\b(and|also|plus|as well as|additionally|while)\b', clean_text)) or text.count('?') >= 2
    active_domains = sum([bool(has_order_domain), bool(has_policy_domain), bool(has_escalation_domain)])

    # Only invoke decomposer if at least 2 distinct domains AND compound conjunction / question structure
    if active_domains >= 2 and has_conjunction:
        decomposed_tasks = _decompose_compound_query(last_human_msg)
        if len(decomposed_tasks) >= 2:
            print(f"[Orchestrator] Multi-Intent Compound Inquiry detected! Decomposed into {len(decomposed_tasks)} parallel tasks: {decomposed_tasks}")
            return {
                "active_agent": "orchestrator_parallel",
                "is_multi_intent": True,
                "plan_tasks": decomposed_tasks
            }

    # ── STAGE 1: Deterministic Fast-Path (<0.1ms) ──────────────────────────

    # 1. High-Friction Complaints & Live Supervisor Handoffs
    supervisor_handoff_phrases = [
        "connect to a supervisor", "speak to a supervisor", "talk to a supervisor", "need a supervisor",
        "connect me to a supervisor", "speak to a manager", "talk to a manager", "talk to human",
        "speak to a human", "speak with a human", "real person", "human agent"
    ]
    is_complaint = any(re.search(r'\b' + re.escape(kw) + r'\b', clean_text) for kw in complaint_markers)
    is_handoff_request = any(phrase in text for phrase in supervisor_handoff_phrases)

    if is_complaint or is_handoff_request:
        return {"active_agent": "escalation_specialist", "is_multi_intent": False}

    # 2. Order Management, Tracking & Cancellations
    order_phrases = [
        "order status", "cancel order", "cancel my order", "cancel this order", "track order",
        "track package", "track parcel", "track shipment", "where is my order", "where is my package",
        "where is my parcel", "shipping status", "delivery status", "cancel the order", "cancel shipment"
    ]
    has_order_phrase = any(phrase in text for phrase in order_phrases)

    order_nouns = ["order", "package", "parcel", "shipment", "delivery", "purchase"]
    order_verbs = ["cancel", "status", "track", "tracking", "where", "refund", "return", "ship"]
    has_order_noun = any(re.search(r'\b' + re.escape(n) + r'\b', clean_text) for n in order_nouns)
    has_order_verb = any(re.search(r'\b' + re.escape(v) + r'\b', clean_text) for v in order_verbs)
    is_order_intent = has_uuid or has_order_phrase or (has_order_noun and has_order_verb)

    if is_order_intent:
        return {"active_agent": "order_specialist", "is_multi_intent": False}

    # 3. Company Policy, Warranty, Knowledge Base & VIP Rules
    if any(re.search(r'\b' + re.escape(kw) + r'\b', clean_text) for kw in policy_markers):
        return {"active_agent": "policy_specialist", "is_multi_intent": False}

    # 4. Pure Greetings & Short Pleasantries (<3 words)
    greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "howdy", "sup", "greetings"]
    words = clean_text.split()
    if clean_text in greetings or (len(words) <= 3 and any(w in greetings for w in words)):
        return {"active_agent": "direct_response", "is_multi_intent": False}

    # ── STAGE 2: Multi-Turn Conversational Follow-Up Resolution (<0.5ms) ───
    prev_agent = state.get("active_agent")
    last_ai_msg = next((m.content for m in reversed(messages) if m.type == "ai"), "")
    last_ai_lower = last_ai_msg.lower() if isinstance(last_ai_msg, str) else str(last_ai_msg).lower()

    affirmative_actions = ["yes", "yeah", "yep", "sure", "cancel it", "please cancel", "cancel", "refund it", "go ahead", "do it", "proceed", "confirm", "ok", "okay"]
    has_affirmative = any(re.search(r'\b' + re.escape(w) + r'\b', clean_text) for w in affirmative_actions) or clean_text in affirmative_actions

    if prev_agent == "order_specialist" or any(kw in last_ai_lower for kw in ["order", "cancel", "refund", "tracking"]):
        if has_affirmative or "cancel" in clean_text or "refund" in clean_text or has_uuid:
            return {"active_agent": "order_specialist", "is_multi_intent": False}

    if prev_agent == "escalation_specialist" or any(kw in last_ai_lower for kw in ["supervisor", "manager", "support ticket", "escalat"]):
        if has_affirmative or any(w in clean_text for w in ["yes", "ticket", "human", "talk", "speak"]):
            return {"active_agent": "escalation_specialist", "is_multi_intent": False}

    if prev_agent == "policy_specialist":
        if any(w in clean_text for w in ["how many", "what about", "why", "days", "eligible"]):
            return {"active_agent": "policy_specialist", "is_multi_intent": False}

    # ── STAGE 3: Semantic LLM Classifier Fallback (~50ms) ──────────────────
    return {"active_agent": _semantic_llm_router(messages), "is_multi_intent": False}


# ── 5. Specialist Agent Nodes ────────────────────────────────────────────────
def order_specialist_node(state: AgentState):
    """
    Specialist Agent scoped strictly to order lookups, verification, and cancellations.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    memory_context = state.get("user_memories", "")
    user_id = state.get("user_id") or "anonymous"
    current_user_id.set(user_id)

    prompt = (
        f"Current Date and Time: {now_str}.\n"
        f"Authenticated Customer User ID: {user_id}\n"
        f"{memory_context}\n\n"
        "You are the Enterprise Order Operations Specialist.\n"
        "Your responsibilities: Order status lookups, order tracking, order cancellations, and refund processing.\n"
        "Rules:\n"
        f"1. When calling `get_order_details`, `cancel_order`, or `process_refund`, always pass user_id='{user_id}'.\n"
        "2. If an order ID is mentioned or the user asks for order status, immediately call `get_order_details`.\n"
        "3. Standard cancellation window is 24 hours from purchase. However, if customer memory confirms Diamond VIP tier, Diamond policy allows 60 days.\n"
        "4. When cancelling an order, call `cancel_order`.\n"
        "5. When a refund is requested or an order is cancelled with refund, call `process_refund(order_id, amount, reason, user_id)`.\n"
        "   - Notice: Refunds <= $100.00 are instantly processed and credited.\n"
        "   - Refunds > $100.00 trigger Human-in-the-Loop review and will pause for supervisor approval.\n"
        "6. Speak concisely, authoritatively, and professionally. Do not disclose internal tool names."
    )

    llm = get_llm().bind_tools(order_tools)
    model_inputs = [SystemMessage(content=prompt)] + list(state["messages"])
    resp = llm.invoke(model_inputs)
    return {"messages": [resp]}


def policy_specialist_node(state: AgentState):
    """
    Specialist Agent scoped to company policy QA, warranty rules, and loyalty benefits.
    Automatically retrieves top parent policies via Hybrid RRF + Cross-Encoder re-ranking.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    memory_context = state.get("user_memories", "")
    messages = state.get("messages", [])
    last_human_msg = next((m.content for m in reversed(messages) if m.type == "human"), "")

    retrieved_docs = query_hierarchical_rag(last_human_msg, top_parents=2)
    kb_context = "\n\n".join([f"### {doc['title']}\n{doc['content']}" for doc in retrieved_docs]) if retrieved_docs else "No specific policy retrieved."

    prompt = (
        f"Current Date and Time: {now_str}.\n"
        f"{memory_context}\n\n"
        "You are the Enterprise Policy & Knowledge Base Specialist.\n"
        "Authoritative Company Policy Context (Retrieved via Hybrid Search & Cross-Encoder):\n"
        f"{kb_context}\n\n"
        "Strict Grounding Rules:\n"
        "1. Answer ONLY using the facts stated in the Authoritative Company Policy Context and Customer Memory above.\n"
        "2. If an exact number, dollar limit, duration, or rule is asked, cite the EXACT value from the policy context.\n"
        "3. NEVER invent, assume, or fabricate policies or refund dollar limits not explicitly present in the context.\n"
        "4. If the retrieved context does not contain the answer, state that clearly without guessing.\n"
        "5. If the customer is asking about personal details (e.g. their name, job, location) or facts stated earlier in the conversation history, answer directly from the conversation history instead of calling lookup_knowledge_base.\n"
        "6. Keep explanations professional, precise, and concise."
    )

    llm = get_llm().bind_tools(policy_tools)
    model_inputs = [SystemMessage(content=prompt)] + list(state["messages"])
    resp = llm.invoke(model_inputs)
    return {"messages": [resp]}


def escalation_specialist_node(state: AgentState):
    """
    Specialist Agent scoped to conflict resolution, ticketing, and live human supervisor handoffs.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    memory_context = state.get("user_memories", "")

    prompt = (
        f"Current Date and Time: {now_str}.\n"
        f"{memory_context}\n\n"
        "You are the Enterprise Escalation & Customer Care Specialist.\n"
        "Your responsibilities: Resolving customer frustration, creating official support tickets, and routing to live human supervisors.\n"
        "Rules:\n"
        "1. Empathize with the customer's situation and assure prompt resolution.\n"
        "2. For formal tracking or unresolved disputes, call `create_support_ticket`.\n"
        "3. When the customer requests a supervisor or manager, call `escalate_to_human_supervisor`.\n"
        "4. Provide the generated ticket or escalation reference directly to the customer."
    )

    llm = get_llm().bind_tools(escalation_tools)
    model_inputs = [SystemMessage(content=prompt)] + list(state["messages"])
    resp = llm.invoke(model_inputs)
    return {"messages": [resp]}


def direct_response_node(state: AgentState):
    """
    Supervisor direct conversational response for general conversation, memory recall,
    greetings, and pleasantries without tool invocation.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    memory_context = state.get("user_memories", "")
    prompt = (
        f"Current Date and Time: {now_str}.\n"
        f"{memory_context}\n\n"
        "You are Maya, a warm, friendly, and empathetic Senior Customer Support Specialist at Enterprise.\n"
        "Persona & Communication Style:\n"
        "1. Human, Conversational Tone: Speak naturally, warmly, and helpfully like a real person, not an AI or robotic system.\n"
        "2. Strict Ban on Robotic Meta-Language: NEVER say phrases like 'I can answer that directly now', 'based on the conversation history', "
        "'according to my system/checkpoints', or mention functions/tools. Speak naturally as if you genuinely remember the conversation.\n"
        "3. Remembering Customer Details: When the customer asks about themselves, their job, location, or past statements, "
        "reply warmly and seamlessly (for example: 'You're based in Seattle and working as a software engineer! How can I help you today, Alex?').\n"
        "4. Greetings: Welcome the customer warmly and invite them to ask about order tracking, cancellations, refunds, or company policies."
    )
    llm = get_llm()
    model_inputs = [SystemMessage(content=prompt)] + list(state["messages"])
    resp = llm.invoke(model_inputs)
    return {"messages": [resp]}


# ── 6. Parallel Orchestrator Workers & Synthesizer Node (Pattern 2) ───────────

async def _async_order_worker(sub_query: str, user_id: str, user_memories: str) -> dict:
    """Worker for executing order operations in parallel."""
    current_user_id.set(user_id)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = (
        f"Current Date and Time: {now_str}.\n"
        f"Authenticated Customer User ID: {user_id}\n"
        f"{user_memories}\n\n"
        "You are the Enterprise Order Operations Specialist.\n"
        f"Specific Sub-Task: {sub_query}\n"
        "Rules:\n"
        f"1. When calling `get_order_details`, `cancel_order`, or `process_refund`, always pass user_id='{user_id}'.\n"
        "2. If an order ID is mentioned, call `get_order_details` immediately.\n"
        "3. If order cancellation or refund is requested, note that cancellation requires supervisor approval and state the order status.\n"
        "4. Provide a clear, factual summary of the order details."
    )
    llm = get_llm().bind_tools(safe_order_tool_list)
    turn_messages = [SystemMessage(content=prompt), HumanMessage(content=sub_query)]
    resp = await llm.ainvoke(turn_messages)

    if hasattr(resp, "tool_calls") and resp.tool_calls:
        for tc in resp.tool_calls:
            tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            tool_fn = next((t for t in safe_order_tool_list if t.name == tool_name), None)
            if tool_fn:
                tool_out = tool_fn.invoke(tool_args)
                turn_messages.append(resp)
                turn_messages.append(ToolMessage(content=str(tool_out), tool_call_id=tc.get("id", "call_1")))
                final_resp = await llm.ainvoke(turn_messages)
                return {"agent_name": "Order Operations", "sub_query": sub_query, "result": final_resp.content}

    return {"agent_name": "Order Operations", "sub_query": sub_query, "result": resp.content}


async def _async_policy_worker(sub_query: str, user_id: str, user_memories: str) -> dict:
    """Worker for executing policy and knowledge base retrieval in parallel."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    retrieved_docs = query_hierarchical_rag(sub_query, top_parents=2)
    kb_context = "\n\n".join([f"### {doc['title']}\n{doc['content']}" for doc in retrieved_docs]) if retrieved_docs else "No specific policy retrieved."

    prompt = (
        f"Current Date and Time: {now_str}.\n"
        f"{user_memories}\n\n"
        "You are the Enterprise Policy & Knowledge Base Specialist.\n"
        f"Specific Sub-Task: {sub_query}\n"
        f"Authoritative Company Policy Context:\n{kb_context}\n\n"
        "Strict Grounding Rules:\n"
        "1. Answer ONLY using the facts stated in the Authoritative Company Policy Context and Customer Memory above.\n"
        "2. If an exact number, dollar limit, duration, or rule is asked, cite the EXACT value.\n"
        "3. Keep the summary precise, authoritative, and concise."
    )
    llm = get_llm()
    resp = await llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content=sub_query)])
    return {"agent_name": "Policy & Knowledge Base", "sub_query": sub_query, "result": resp.content}


async def _async_escalation_worker(sub_query: str, user_id: str, user_memories: str) -> dict:
    """Worker for executing customer care escalation in parallel."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = (
        f"Current Date and Time: {now_str}.\n"
        f"{user_memories}\n\n"
        "You are the Enterprise Escalation & Customer Care Specialist.\n"
        f"Specific Sub-Task: {sub_query}\n"
        "Rules: Create an escalation queue or acknowledge customer frustration professionally."
    )
    llm = get_llm().bind_tools(escalation_tools)
    resp = await llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content=sub_query)])
    if hasattr(resp, "tool_calls") and resp.tool_calls:
        for tc in resp.tool_calls:
            tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            tool_fn = next((t for t in escalation_tools if t.name == tool_name), None)
            if tool_fn:
                tool_out = tool_fn.invoke(tool_args)
                return {"agent_name": "Escalation Desk", "sub_query": sub_query, "result": str(tool_out)}
    return {"agent_name": "Escalation Desk", "sub_query": sub_query, "result": resp.content}


async def orchestrator_node(state: AgentState):
    """
    Parallel Orchestrator Node (Pattern 2):
    Executes decomposed sub-tasks concurrently across specialist domains on the asyncio event loop.
    Applies the Bulkhead Pattern so an error in one domain does not fail the other domains.
    """
    tasks = state.get("plan_tasks", [])
    user_id = state.get("user_id") or "anonymous"
    user_memories = state.get("user_memories", "")

    async def run_worker(task: dict):
        agent = task.get("agent")
        sub_query = task.get("sub_query", "")
        try:
            if agent == "order_specialist":
                return await _async_order_worker(sub_query, user_id, user_memories)
            elif agent == "policy_specialist":
                return await _async_policy_worker(sub_query, user_id, user_memories)
            elif agent == "escalation_specialist":
                return await _async_escalation_worker(sub_query, user_id, user_memories)
            else:
                return {"agent_name": agent or "Specialist", "sub_query": sub_query, "result": "Acknowledged."}
        except Exception as e:
            print(f"[Orchestrator Bulkhead Warning] Worker {agent} failed gracefully: {e}")
            return {
                "agent_name": agent or "Specialist",
                "sub_query": sub_query,
                "result": f"Department service temporarily unavailable: {str(e)[:100]}"
            }

    worker_coros = [run_worker(t) for t in tasks]
    gathered_findings = await asyncio.gather(*worker_coros)

    return {
        "findings": list(gathered_findings)
    }


async def synthesizer_node(state: AgentState):
    """
    Fan-In Aggregator: Combines findings from all parallel specialists
    into a single cohesive, unified, empathetic response for the customer.
    """
    findings = state.get("findings", [])
    messages = state.get("messages", [])
    last_human_msg = next((m.content for m in reversed(messages) if m.type == "human"), "")

    findings_blocks = []
    for f in findings:
        agent_name = f.get("agent_name", "Specialist")
        sub_q = f.get("sub_query", "")
        res = f.get("result", "")
        findings_blocks.append(f"### Finding from {agent_name} regarding '{sub_q}':\n{res}")

    context_text = "\n\n".join(findings_blocks)

    prompt = (
        "You are Maya, Senior Customer Support Specialist at Enterprise.\n"
        f"Customer Inquired: \"{last_human_msg}\"\n\n"
        f"Findings from our internal departments:\n"
        f"{context_text}\n\n"
        "Instructions for Final Customer Response:\n"
        "1. Write a single, cohesive, warm, empathetic, and comprehensive response that directly answers ALL parts of the customer's request.\n"
        "2. NEVER mention internal agent names, 'specialists', 'findings', or backend departments. Speak naturally as one unified person.\n"
        "3. If order details are present, explain the status clearly.\n"
        "4. If policy details are present, cite the exact rules/durations clearly.\n"
        "5. If an escalation ticket or reference ID is present, share it with the customer."
    )

    llm = get_llm()
    resp = await llm.ainvoke([SystemMessage(content=prompt)])
    return {"messages": [resp]}


# ── 7. Routing Edges ──────────────────────────────────────────────────────────
def route_from_supervisor(state: AgentState) -> Literal["orchestrator_parallel", "order_specialist", "policy_specialist", "escalation_specialist", "direct_response"]:
    agent = state.get("active_agent") or "direct_response"
    return agent


def route_order_tools(state: AgentState) -> Literal["sensitive_tools", "safe_order_tools", "end"]:
    messages = state["messages"]
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tc in last_message.tool_calls:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            if name == "cancel_order":
                return "sensitive_tools"
            if name == "process_refund":
                amt = float(args.get("amount", 0.0) or 0.0)
                if amt > 100.0:
                    return "sensitive_tools"
                else:
                    return "safe_order_tools"
            if name in SENSITIVE_TOOLS:
                return "sensitive_tools"
        return "safe_order_tools"
    return "end"


def route_policy_tools(state: AgentState) -> Literal["policy_tools", "end"]:
    messages = state["messages"]
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "policy_tools"
    return "end"


def route_escalation_tools(state: AgentState) -> Literal["escalation_tools", "end"]:
    messages = state["messages"]
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "escalation_tools"
    return "end"


# ── 8. Build and Compile Multi-Agent StateGraph ───────────────────────────────
workflow = StateGraph(AgentState)

# Nodes
workflow.add_node("memory_injector", memory_injector_node)
workflow.add_node("supervisor_router", supervisor_router_node)
workflow.add_node("orchestrator_parallel", orchestrator_node)
workflow.add_node("synthesizer", synthesizer_node)
workflow.add_node("order_specialist", order_specialist_node)
workflow.add_node("policy_specialist", policy_specialist_node)
workflow.add_node("escalation_specialist", escalation_specialist_node)
workflow.add_node("direct_response", direct_response_node)

# Tool Nodes
workflow.add_node("safe_order_tools", ToolNode(safe_order_tool_list))
workflow.add_node("sensitive_tools", ToolNode(sensitive_order_tool_list))
workflow.add_node("policy_tools", ToolNode(policy_tools))
workflow.add_node("escalation_tools", ToolNode(escalation_tools))

# Entry Flow
workflow.set_entry_point("memory_injector")
workflow.add_edge("memory_injector", "supervisor_router")

# Supervisor Conditional Routing (Adaptive Single vs. Multi-Intent)
workflow.add_conditional_edges(
    "supervisor_router",
    route_from_supervisor,
    {
        "orchestrator_parallel": "orchestrator_parallel",
        "order_specialist": "order_specialist",
        "policy_specialist": "policy_specialist",
        "escalation_specialist": "escalation_specialist",
        "direct_response": "direct_response"
    }
)

# Parallel Orchestrator Fan-Out & Synthesizer Fan-In Flow
workflow.add_edge("orchestrator_parallel", "synthesizer")
workflow.add_edge("synthesizer", END)

# Order Specialist Tool Loop & HITL Interrupt
workflow.add_conditional_edges(
    "order_specialist",
    route_order_tools,
    {
        "safe_order_tools": "safe_order_tools",
        "sensitive_tools": "sensitive_tools",
        "end": END
    }
)
workflow.add_edge("safe_order_tools", "order_specialist")
workflow.add_edge("sensitive_tools", "order_specialist")

# Policy Specialist Tool Loop
workflow.add_conditional_edges(
    "policy_specialist",
    route_policy_tools,
    {
        "policy_tools": "policy_tools",
        "end": END
    }
)
workflow.add_edge("policy_tools", "policy_specialist")

# Escalation Specialist Tool Loop
workflow.add_conditional_edges(
    "escalation_specialist",
    route_escalation_tools,
    {
        "escalation_tools": "escalation_tools",
        "end": END
    }
)
workflow.add_edge("escalation_tools", "escalation_specialist")

# Direct Response ends conversation turn
workflow.add_edge("direct_response", END)

# Compile Graph with Postgres Checkpointer & Human-in-the-Loop Interrupt
memory_saver = PostgresCheckpointSaver()
compiled_graph: CompiledStateGraph = workflow.compile(
    checkpointer=memory_saver,
    interrupt_before=["sensitive_tools"]
)
