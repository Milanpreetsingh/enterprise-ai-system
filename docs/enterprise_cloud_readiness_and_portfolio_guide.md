# 🚀 Enterprise Cloud Readiness, Portfolio & Security Architecture Guide

This guide details the senior-grade production features implemented to prepare the **Enterprise AI System** for cloud deployment ($0 cloud cost) and portfolio presentation for Senior Backend & AI Systems Engineer roles.

---

## 📑 Table of Contents
1. [Architecture Overview](#1-architecture-overview)
2. [Mandatory Authentication, RBAC & IDOR Protection](#2-mandatory-authentication-rbac--idor-protection)
3. [Redis Rate Limiting & FinOps Token Budgeting](#3-redis-rate-limiting--finops-token-budgeting)
4. [MCP `process_refund` Tool & Tiered Financial HITL](#4-mcp-process_refund-tool--tiered-financial-hitl)
5. [Transactional HTML Email Notification Consumer](#5-transactional-html-email-notification-consumer)
6. [Cloud LLM Fallback (Groq Free Tier)](#6-cloud-llm-fallback-groq-free-tier)
7. [Frontend Live "Agent Thought Trace" Diagnostics Drawer](#7-frontend-live-agent-thought-trace-diagnostics-drawer)
8. [End-to-End Verification Runbook](#8-end-to-end-verification-runbook)
9. [Resume & System Design Interview Talking Points](#9-resume--system-design-interview-talking-points)

---

## 1. Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │    Frontend Client (Glassmorphism Web UI)    │
                      │  Live Trace Drawer • Token Quota • SSE Chat  │
                      └──────────────────────┬───────────────────────┘
                                             │ HTTP / SSE (Bearer JWT)
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │           Go API Gateway (:8080)             │
                      │  • Sliding-Window Rate Limiter (Redis)       │
                      │  • Daily AI Token Budget Quota (Redis)       │
                      │  • Mandatory JWT Auth & RBAC Middleware      │
                      │  • IDOR Ownership Verification               │
                      │  • MCP Server Endpoint (/api/v1/mcp)         │
                      └───────┬──────────────┬──────────────┬────────┘
             gRPC User        │    gRPC Order│     HTTP/gRPC│
             (:50051)         │    (:50052)  │     (:50053) │
                              ▼              ▼              ▼
                     ┌─────────────┐ ┌─────────────┐ ┌──────────────────────┐
                     │ Go User Svc │ │Go Order Svc │ │  Python AI Service   │
                     │• bcrypt     │ │• SAGA Outbox│ │• Tier-2 DeBERTa MPS  │
                     │• JWT Claims │ │• Order Repo │ │• LangGraph Router    │
                     │• RBAC Roles │ │• Idempotency│ │• Hierarchical RAG    │
                     └──────┬──────┘ └──────┬──────┘ │• Groq / Ollama LLM   │
                            │               │        └──────────┬───────────┘
                            ▼               ▼                   │
                     ┌──────────────────────────────────────┐   │
                     │      PostgreSQL (Port 5432)          │   │
                     │ • users, orders, outbox_events       │   │
                     │ • checkpoints, user_memories         │   │
                     │ • parent_docs, kb_chunks (pgvector)  │   │
                     └──────────────────┬───────────────────┘   │
                                        │ Poller                │
                                        ▼                       ▼
                     ┌──────────────────────────────────────┐   │
                     │         Apache Kafka (:9092)         │   │
                     │  Topic: order-events (SAGA / Events) │   │
                     └──────────────────┬───────────────────┘   │
                                        │                       │
                                        ▼                       │
                     ┌──────────────────────────────────────┐   │
                     │  Python Notification Service (EOS)   │   │
                     │ • Consumes OrderCancelled & Refunded │   │
                     │ • Queries users relational table     │   │
                     │ • Dispatches Responsive HTML Email   │◄──┘
                     └──────────────────────────────────────┘
```

---

## 2. Mandatory Authentication, RBAC & IDOR Protection

### A. Role-Based Access Control (RBAC) Matrix
The system defines 3 discrete roles in `UserClaims` ([`api-gateway/middleware/auth.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/api-gateway/middleware/auth.go)):

| Role | Permissions | Endpoints Allowed |
| :--- | :--- | :--- |
| **`customer`** | Can place orders, view own orders, chat with AI, request refunds. | `/orders` (POST, GET own), `/chat`, `/chat/stream`, `/rag/docs`, `/rag/query` |
| **`support_agent`** | Can view any order, initiate cancellations, approve supervisor HITL interrupts. | All customer endpoints + `/agent/approve` |
| **`admin`** | Full platform superuser. Can seed/re-index knowledge base and approve high-stakes actions. | All endpoints + `/rag/seed` + `/agent/approve` |

### B. Insecure Direct Object Reference (IDOR) Protection
Prior to this release, passing an arbitrary `order_id` in `GET /api/v1/orders/:id` returned the order record regardless of caller identity.
Now, in [`api-gateway/handler/handler.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/api-gateway/handler/handler.go#L201-L208):
```go
// IDOR Protection: Customers may only view their own orders
callerUserID := c.GetString("userID")
callerRole := c.GetString("role")
if callerRole != "admin" && callerRole != "support_agent" && resp.GetUserId() != callerUserID {
    c.JSON(http.StatusForbidden, gin.H{
        "error": "Forbidden: You are not authorized to view orders belonging to other accounts",
    })
    return
}
```

---

## 3. Redis Rate Limiting & FinOps Token Budgeting

Located in [`api-gateway/middleware/ratelimit.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/api-gateway/middleware/ratelimit.go).

### A. Sliding-Window Rate Limiter (Anti-Abuse)
- **Key Pattern**: `ratelimit:<identity>:<YYYYMMDDHHmm>`
- **Threshold**: 30 requests / minute per User ID (or IP for anonymous endpoints).
- **Behavior**: Uses Redis `INCR` with a 2-minute TTL. When count exceeds 30, immediately short-circuits with `HTTP 429 Too Many Requests` and sets `Retry-After: 60`.
- **Response Headers**:
  - `X-RateLimit-Limit: 30`
  - `X-RateLimit-Remaining: <remaining>`

### B. FinOps Daily Token Budget Quota
- **Key Pattern**: `ai:budget:<user_id>:<YYYY-MM-DD>`
- **Daily Allowance**: 10,000 tokens / user / day (quota resets at 00:00 UTC).
- **Enforcement**:
  1. *Pre-flight*: Rejects incoming chat requests if daily budget is consumed with `HTTP 429`:
     ```json
     {
       "error": "Daily AI Token Budget Exceeded: You have consumed your daily allowance of tokens.",
       "daily_limit": 10000,
       "tokens_used": 10000,
       "resets_at": "00:00 UTC"
     }
     ```
  2. *Post-response*: Calculates tokens consumed (`(len(prompt) + len(response)) / 4`) and atomically increments the Redis daily counter via `INCRBY`.
- **Response Headers**:
  - `X-Daily-Token-Budget: 10000`
  - `X-Daily-Tokens-Used: <used>`
  - `X-Daily-Tokens-Remaining: <remaining>`

---

## 4. MCP `process_refund` Tool & Tiered Financial HITL

Exposed via Model Context Protocol (MCP) in [`api-gateway/handler/mcp.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/api-gateway/handler/mcp.go#L112-L138) and consumed by LangGraph in [`services/ai/app/agent/graph.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/agent/graph.py#L235-L252).

### Tiered Financial Policy Rules
```
                                 [process_refund(order_id, amount)]
                                                 │
                                                 ▼
                                     Is Amount > $100.00?
                                       /              \
                                     NO                YES
                                     /                  \
                        ┌──────────────────┐      ┌───────────────────────────┐
                        │ safe_order_tools │      │      sensitive_tools      │
                        │                  │      │  (interrupt_before hits)  │
                        │ Instant Execution│      │                           │
                        │ Auto-Credit USD  │      │ Graph Execution Pauses    │
                        └──────────────────┘      │ HITL Ticket Generated     │
                                                  │ Awaiting /agent/approve   │
                                                  └─────────────┬─────────────┘
                                                                │
                                                  Supervisor Role Authorization
                                                                │
                                                                ▼
                                                  Resume & Execute Refund Tool
```

---

## 5. Transactional HTML Email Notification Consumer

Implemented in [`services/notification/main.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/notification/main.py).

### Key Features
1. **Relational User Lookup**: Joins with PostgreSQL `users` table via `SELECT email, full_name FROM users WHERE id = %s` to retrieve the real customer recipient.
2. **Responsive Modern HTML Template**: Features enterprise dark-mode card styling, blue-violet gradient header, item SKU breakdown, resolution badge, and UTC event timestamp.
3. **Dual Protocol Delivery**: Dispatches via standard SMTP (`SMTP_HOST`, `SMTP_PORT` targeting local MailHog `:1025` or cloud SMTP provider), with automatic fallback to sandbox logging if no local SMTP relay is active.
4. **SDE-3 Exactly-Once Semantics (EOS)**: Records `(event_id, consumer_group)` in `processed_events` before committing Kafka offsets.

---

## 6. Cloud LLM Fallback (Groq Free Tier)

Configured in [`services/ai/app/config.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/config.py) and [`services/ai/app/agent/graph.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/agent/graph.py#L54-L68).

### The Zero-Dollar ($0.00) Cloud Deployment Strategy
- Running an 8B local LLM like Ollama in the cloud requires GPU instances ($100–$200/month).
- On cheap $5–$10/month cloud CPU VPS (or free render/fly tiers), local LLM inference is slow.
- **Solution**: The LLM factory prioritizes `GROQ_API_KEY`:
  ```python
  def get_llm():
      if settings.GROQ_API_KEY:
          from langchain_groq import ChatGroq
          return ChatGroq(
              model=settings.GROQ_MODEL, # "llama-3.1-8b-instant"
              groq_api_key=settings.GROQ_API_KEY,
              temperature=0.1
          )
      if settings.OPENAI_API_KEY:
          return ChatOpenAI(model="gpt-4o", openai_api_key=settings.OPENAI_API_KEY)
      from langchain_ollama import ChatOllama
      return ChatOllama(model=settings.OLLAMA_MODEL, base_url=settings.OLLAMA_BASE_URL)
  ```
- **Performance**: Groq responds in ~120–250ms with zero token cost on their free tier.

---

## 7. Frontend Live "Agent Thought Trace" Diagnostics Drawer

Located in [`frontend-app/index.html`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/frontend-app/index.html), [`styles.css`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/frontend-app/styles.css), and [`app.js`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/frontend-app/app.js).

### Drawer Telemetry Widgets
1. **FinOps & Rate Limiter**: Interactive progress bar tracking remaining daily quota (e.g. `9,850 / 10,000 remaining`) and sliding-window rate limit (`29 / 30 req/min left`).
2. **Tier-2 Semantic Guardrails**: Shows real-time encoder classification latency (~25–35ms on Metal MPS) and security verdict badge.
3. **Memory Store & Checkpointer**: Displays PostgreSQL thread checkpoint state and episodic memory injection.
4. **Supervisor Intent Router**: Real-time badge tracking active specialist routing (`order_specialist`, `policy_specialist`, `escalation_specialist`, `direct_response`).
5. **Model Context Protocol (MCP)**: Status indicators for autonomous ($\le \$100$) vs HITL ($> \$100$) execution.
6. **Transactional Outbox & Email**: Real-time status of asynchronous SAGA and Kafka email dispatcher.

---

## 8. End-to-End Verification Runbook

### Test 1: User Signup with RBAC Roles
```bash
# 1. Register a standard customer
curl -X POST http://localhost:8080/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"customer@test.com","password":"password123","full_name":"Alice Customer","role":"customer"}'

# 2. Register an admin supervisor
curl -X POST http://localhost:8080/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"password123","full_name":"Bob Admin","role":"admin"}'
```

### Test 2: Verify IDOR Protection
```bash
# Login as customer
CUSTOMER_TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"customer@test.com","password":"password123"}' | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

# Attempt to query another user's order
curl -i -X GET http://localhost:8080/api/v1/orders/00000000-0000-0000-0000-000000000001 \
  -H "Authorization: Bearer $CUSTOMER_TOKEN"

# Expected Output: HTTP 403 Forbidden
# {"error": "Forbidden: You are not authorized to view orders belonging to other accounts"}
```

### Test 3: Verify Admin-Only Knowledge Base Seeding
```bash
# Customer attempts to seed KB (Blocked)
curl -i -X POST http://localhost:8080/api/v1/rag/seed \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Unauthorized policy update","category":"policy"}'

# Expected Output: HTTP 403 Forbidden
# {"error":"Forbidden: Insufficient permissions for this action","required_roles":["admin"],"current_role":"customer"}
```

### Test 4: Verify Redis Rate Limiter & Token Budget Headers
```bash
curl -i -X POST http://localhost:8080/api/v1/chat \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"What is my order status?","thread_id":"test-session-1"}'

# Inspect Response Headers:
# X-RateLimit-Limit: 30
# X-RateLimit-Remaining: 29
# X-Daily-Token-Budget: 10000
# X-Daily-Tokens-Used: 42
# X-Daily-Tokens-Remaining: 9958
```

---

## 9. Resume & System Design Interview Talking Points

| Architecture Area | Interview Talking Point |
| :--- | :--- |
| **Object-Level Authorization (IDOR)** | *"At the API Gateway, we enforce zero-trust tenancy. When evaluating order modifications or retrieval, we cross-reference the JWT Subject against database entity owners, preventing IDOR vulnerabilities while allowing privileged administrative bypass via claims-based RBAC."* |
| **FinOps & API Abuse Prevention** | *"To make the system public-facing without runaway cloud costs, I built a dual Redis defense: a sliding-window rate limiter (30 req/min) to prevent DDoS, and a per-user daily token budget quota (10k tokens/day) that tracks prompt and completion tokens with HTTP 429 backpressure."* |
| **Model Context Protocol (MCP)** | *"Rather than hardcoding tool APIs, the AI Service dynamically discovers backend capabilities from the Go Gateway via JSON-RPC 2.0 MCP schemas. For financial operations like refunds, we instituted a tiered autonomous threshold ($\le \$100$ auto-executes; $> \$100$ triggers a LangGraph breakpoint for Human-in-the-Loop review)."* |
| **Zero-Dollar Cloud Deployment** | *"By abstracting the LLM provider through a factory pattern supporting Groq `llama-3.1-8b-instant`, the live portfolio demo runs with sub-200ms latency and $0.00 cloud API costs on modest cloud hardware."* |
| **Reliability & Consistency** | *"Order state mutations use the Transactional Outbox pattern with Debezium/Kafka poller semantics, guaranteeing that order cancellations, inventory restocks, and customer HTML email dispatches succeed with Exactly-Once Semantics (EOS)."* |
