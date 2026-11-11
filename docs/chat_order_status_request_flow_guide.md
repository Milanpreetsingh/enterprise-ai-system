# Comprehensive Request Execution Flow: Chat Order Status Query

> [!NOTE]
> **SDE-3 Production Architecture Update:**
> For the updated production request flow covering **HTTP/SSE streaming via Go API Gateway**, **Dual-LLM Security Guardrails**, **Tiered Memory**, **Master Supervisor Router**, **Hierarchical Hybrid RAG (pgvector HNSW + BM25 tsvector + Cross-Encoder)**, and the **Atomic Transactional Outbox Pattern with Idempotent Kafka Consumers**, please refer to the dedicated guide:
> 🔗 [`revamped_chat_order_status_request_flow_guide.md`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/docs/revamped_chat_order_status_request_flow_guide.md).

This document provides a step-by-step, code-level execution walkthrough of query and mutation flows in the initial Enterprise AI System.


## 📌 Document Navigation
- [1. Autonomous Read Query (Tier 2): Order Status](#-end-to-end-architecture-flow)
  - [End-to-End Architecture Flow](#-end-to-end-architecture-flow)
  - [Detailed Code-Level Journey (Steps 1–15)](#-detailed-code-level-journey)
  - [Component Responsibility Matrix](#-summary-table-component-responsibility-matrix)
- [2. Advanced Architectural Q&A: Multi-Node Orchestration](#-advanced-architectural-qa-multi-node-orchestration--complex-queries)
- [3. Deep Dive Q&A: LangGraph Edge Routing Mechanics](#-deep-dive-qa-langgraph-edge-routing--execution-decision-mechanics)
- [4. Multi-Turn Memory & State Checkpointing: End-to-End Code Flow (Connected APIs)](#-multi-turn-memory--state-checkpointing-end-to-end-code-flow-connected-apis)
- [5. High-Stakes Mutation (Tier 3): End-to-End Code Flow & Human-in-the-Loop Breakpoint Interrupt](#-high-stakes-mutation-tier-3-end-to-end-code-flow--human-in-the-loop-breakpoint-interrupt)

---

### Scenario Request 1: Autonomous Read Query (Tier 2)
```bash
curl --location 'http://localhost:8000/api/v1/chat' \
--header 'Content-Type: application/json' \
--data '{
    "message": "What is the status of order 427e35ad-dada-4c13-acf7-7a017aa964a7?",
    "thread_id": "t5"
}'
```

---

## 🏛️ End-to-End Architecture Flow

```
                      [ USER / CLIENT ]
                             │
                             │ 1. HTTP POST :8000/api/v1/chat
                             ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   AI SERVICE (FastAPI - Port 8000)                     │
│                                                                        │
│ 2. Guardrails Check: check_security_violation() ──> [PASSED]           │
│ 3. Semantic Cache Check (Redis) ──> [MISS]                             │
│ 4. LangGraph State Machine Execution:                                  │
│    • route_question() detects order UUID ──> Routes to "llm"           │
│    • llm_node() (Ollama llama3.1:8b) emits ToolCall: get_order_details │
│    • should_continue() detects safe tool ──> Routes to "safe_tools"    │
│    • safe_tools executes (Autonomous / No Interrupt)                   │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     │ 5. Network Hop 1: HTTP POST :8080/api/v1/mcp
                                     │    (JSON-RPC 2.0 tools/call)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   API GATEWAY (Gin - Port 8080)                        │
│                                                                        │
│ 6. HandleMCP() parses JSON-RPC request                                 │
│ 7. handleCallTool() dispatches tool: "get_order_details"               │
│ 8. Invokes gRPC Client: h.orderClient.GetOrder(ctx, req)               │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     │ 9. Network Hop 2: HTTP/2 gRPC :50052
                                     │    (/order.OrderService/GetOrder)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   ORDER SERVICE (gRPC - Port 50052)                    │
│                                                                        │
│ 10. OrderHandler.GetOrder() in internal/handler/grpc.go                │
│ 11. OrderService.GetOrder() in internal/service/order_service.go       │
│ 12. PostgresOrderRepository.GetByID() in internal/repository/          │
│ 13. GORM Query: SELECT * FROM orders WHERE id = '427e35ad...'         │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     │ 14. gRPC Response (*orderpb.OrderResponse)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   API GATEWAY (Gin - Port 8080)                        │
│                                                                        │
│ 15. Formats JSON string payload: {"id":"...", "status":"PENDING"...}  │
│ 16. Returns JSON-RPC 2.0 Response to AI Service                        │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     │ 17. HTTP Response with Tool Output
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   AI SERVICE (FastAPI - Port 8000)                     │
│                                                                        │
│ 18. Wraps output into ToolMessage and feeds back to llm_node()         │
│ 19. Ollama synthesizes final message:                                  │
│     "The status of order 427e35ad-dada-4c13-acf7-7a017aa964a7 is      │
│      PENDING."                                                         │
│ 20. Checkpointer persists conversation history to PostgreSQL           │
│ 21. Redis Semantic Cache stores vector embedding + response            │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     │ 22. HTTP Response 200 OK
                                     ▼
                      [ USER / CLIENT ]
```

---

## 🔍 Detailed Code-Level Journey

### Step 1: Ingress into FastAPI (`services/ai/app/main.py`)

The request hits the FastAPI endpoint:

```python
# services/ai/app/main.py (Lines 50-59)
@app.post("/api/v1/chat")
async def chat(req: ChatRequest):
    if not req.message or not req.thread_id:
        raise HTTPException(status_code=400, detail="Missing required parameters: message and thread_id")
```

The payload is parsed into Pydantic model `ChatRequest`:
- `req.message` = `"What is the status of order 427e35ad-dada-4c13-acf7-7a017aa964a7?"`
- `req.thread_id` = `"t5"`
- `req.user_id` = `"anonymous"` (default)

---

### Step 2: Tier 1 Security Guardrails Check (`services/ai/app/agent/guardrails.py`)

Before calling any LLM, tool, or database, the system executes hard security boundaries:

```python
# services/ai/app/main.py (Lines 61-70)
is_violation, refusal_msg = check_security_violation(req.message)
if is_violation:
    return {
        "status": "blocked",
        "response": refusal_msg,
        "thread_id": req.thread_id,
        "role": "system",
        "cache_hit": False
    }
```

#### What happens inside `check_security_violation(text)`?
- Checks against `EXTRACTION_PATTERN_1` and `EXTRACTION_PATTERN_2` for credential extraction (e.g. asking for `openai api key`, `.env`, `db_password`).
- Checks against `INJECTION_OVERRIDE_PATTERNS` for prompt injection (e.g. `ignore previous instructions`).
- **Result**: Neither pattern matches $\implies$ `is_violation = False`. Execution proceeds.

---

### Step 3: Semantic Cache Lookup (`services/ai/app/db/cache.py`)

The system checks if this exact or semantically similar query was already answered in thread `t5`:

```python
# services/ai/app/main.py (Lines 72-81)
cached_hit = get_cached_answer(req.message, thread_id=req.thread_id)
if cached_hit:
    return {
        "response": cached_hit["answer"],
        "thread_id": req.thread_id,
        "role": "ai",
        "cache_hit": True,
        "similarity": cached_hit["similarity"]
    }
```

#### Under the hood:
1. `get_embedding(req.message)` calls Ollama (`nomic-embed-text`) at `http://localhost:11434/api/embed` to get a 768-dim vector, padded to 1536-dim.
2. Performs cosine similarity comparison against keys in Redis under namespace `semantic_cache:<thread_id>:*`.
3. **Entity Boundary Guard**: If the query mentions an entity identifier (such as an order UUID), the cache checks whether the incoming query's UUID matches the cached query's UUID. If the order UUID is different, it immediately skips the entry to prevent cross-entity false positive cache hits (even if natural language similarity exceeds 90%).
4. If this is a new query or different order, it returns `None` (**Cache Miss**).
5. `invalidate_cache(thread_id=req.thread_id)` runs to evict the previous stale state for this conversational thread.

---

### Step 4: Graph Invocation & Entry Router (`main.py` ➔ `graph.py`)

#### 4A. Invoking the Compiled Graph in `services/ai/app/main.py`

In [main.py](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/main.py#L90-L101), the FastAPI endpoint imports `compiled_graph` and invokes it asynchronously:

```python
# services/ai/app/main.py (Lines 90-101)
config = {"configurable": {"thread_id": req.thread_id}}

inputs = {
    "messages": [HumanMessage(content=req.message)],
    "user_id": req.user_id,
    "thread_id": req.thread_id
}

state = None
# This is where the state machine graph is triggered!
async for s in compiled_graph.astream(inputs, config=config, stream_mode="values"):
    state = s
```

**How this invocation works:**
1. **Thread Scope (`config`)**: `{"configurable": {"thread_id": "t5"}}` instructs the `PostgresCheckpointSaver` to look up any previous message history stored in PostgreSQL for thread `"t5"`. If it exists, LangGraph loads and merges that history with `inputs`.
2. **Initial State (`inputs`)**: Passes the new `HumanMessage` matching the `AgentState` schema.
3. **`compiled_graph.astream(...)`**: Triggers the LangGraph engine. The engine immediately checks the graph's registered entry point.

---

#### 4B. Deep-Dive: What is `astream`, Where is it Defined, and Why "Go to Definition" Fails

When trying to navigate to `astream` in your IDE (VS Code / PyCharm / Antigravity), you may notice **"No definition found"**. Here is why:

##### 1. Class Inheritance Chain (Method Resolution Order)
In Python, `compiled_graph` is an instance of `CompiledStateGraph`. Its class inheritance hierarchy is:

```
CompiledStateGraph
       └── Pregel                <── `astream` is defined here!
             └── PregelProtocol
                   └── Runnable  (LangChain Core Interface)
```

- **Exact Source File**: `services/ai/venv/lib/python3.13/site-packages/langgraph/pregel/main.py` (Line 3154)
- **Signature**:
  ```python
  async def astream(
      self,
      input: Union[dict[str, Any], Any],
      config: Optional[RunnableConfig] = None,
      *,
      stream_mode: Optional[Union[StreamMode, list[StreamMode]]] = None,
      ...
  ) -> AsyncIterator[Union[dict[str, Any], Any]]:
  ```

##### 2. Why the IDE Fails:
`workflow.compile(...)` is a dynamic factory method. Without an explicit type hint, Python language servers (Pylance, Pyright) infer `compiled_graph` as `Any`. Adding a type annotation in `graph.py` fixes IDE navigation:
```python
from langgraph.graph.state import CompiledStateGraph

compiled_graph: CompiledStateGraph = workflow.compile(...)
```

---

#### 4C. Graph Assembly & Wiring Blueprint (`services/ai/app/agent/graph.py`)

Here is how the nodes, edges, conditional routing, and checkpointers are wired together in [graph.py](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/agent/graph.py#L138-L177):

```python
# services/ai/app/agent/graph.py (Lines 138-177)

# 1. Instantiate the Directed State Machine
workflow = StateGraph(AgentState)

# 2. Register Nodes
workflow.add_node("rag", rag_node)
workflow.add_node("llm", llm_node)
workflow.add_node("safe_tools", ToolNode(mcp_tools))
workflow.add_node("sensitive_tools", ToolNode(mcp_tools))

# 3. Register the Conditional Entry Point (Router)
workflow.set_conditional_entry_point(
    route_question,
    {
        "rag": "rag",
        "llm": "llm"
    }
)

# 4. Connect Edges
workflow.add_edge("rag", "llm")
workflow.add_conditional_edges(
    "llm",
    should_continue,
    {
        "safe_tools": "safe_tools",
        "sensitive_tools": "sensitive_tools",
        "end": END
    }
)
workflow.add_edge("safe_tools", "llm")
workflow.add_edge("sensitive_tools", "llm")

# 5. Compile the State Machine with Postgres Checkpointing & Interrupts
memory_saver = PostgresCheckpointSaver()
compiled_graph: CompiledStateGraph = workflow.compile(
    checkpointer=memory_saver,
    interrupt_before=["sensitive_tools"]
)
```

---

#### 4D. How `astream` Calls `route_question` Under the Hood

You never explicitly call `route_question(state)` in your application code. How does `compiled_graph.astream(...)` execute it?

1. **The Virtual `__start__` Node**:
   When you call `workflow.set_conditional_entry_point(route_question, {"rag": "rag", "llm": "llm"})`, LangGraph attaches a special `BranchSpec` object to its internal root node named `__start__`:
   ```python
   BranchSpec(
       path=route_question,                   # 👈 Pointer to your Python function
       ends={"rag": "rag", "llm": "llm"},     # 👈 Mapping dictionary
       input_schema=AgentState
   )
   ```

2. **The Execution Loop (Tick 0)**:
   When `astream(inputs)` starts:
   - LangGraph injects `inputs` into `state` at the `__start__` node.
   - The Pregel engine reads the writers on `__start__` and sees the registered `BranchSpec`.
   - The engine automatically invokes your function pointer:
     ```python
     selected_key = route_question(current_state)
     ```
   - If `route_question` returns `"llm"`, the engine looks up `"llm"` in `ends`, determines the next active node is `"llm"`, and schedules `llm_node(current_state)`.

```
astream(inputs) 
      │
      ▼
┌───────────────┐
│   __start__   │  (Pregel Root Node)
└───────┬───────┘
        │
        │ 1. Executes: route_question(state)
        ▼
┌────────────────────────┐
│ route_question(state)  │
│ Checks for order UUID  │
│ Returns: "llm"         │
└───────┬────────────────┘
        │
        │ 2. Ends mapping: {"rag": "rag", "llm": "llm"}["llm"] ──> "llm"
        ▼
┌───────────────┐
│   llm_node    │  (Schedules first real node!)
└───────────────┘
```

---

#### 4E. The `route_question` Code & Routing Decision

```python
# services/ai/app/agent/graph.py (Lines 80-97)
def route_question(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1].content.lower()

    if (
        re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}', last_message)
        or "status of order" in last_message
        or "details of order" in last_message
        or "cancel order" in last_message
    ):
        return "llm"

    keywords = ["refund", "return", "policy", "fraud", "warranty", "cancellation policy"]
    if any(kw in last_message for kw in keywords):
        return "rag"
    
    return "llm"
```

- Regex `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}` matches `427e35ad-dada-4c13-acf7-7a017aa964a7`.
- String `"status of order"` also matches.
- **Route Decision**: Returns `"llm"`. The Pregel engine activates the `llm` node directly (bypassing generic RAG policy retrieval).

---

### Step 5: LLM Invocation & Tool Call Decision (`llm_node`)

The `llm_node` function runs:

```python
# services/ai/app/agent/graph.py (Lines 54-75)
def llm_node(state: AgentState):
    messages = list(state["messages"])
    if not any(isinstance(m, SystemMessage) for m in messages):
        messages = [SYSTEM_PROMPT] + messages

    # Local Ollama path
    from langchain_ollama import ChatOllama
    llm = ChatOllama(model="llama3.1:8b", base_url="http://localhost:11434")
    llm_with_tools = llm.bind_tools(mcp_tools)
    resp = llm_with_tools.invoke(messages)
    return {"messages": [resp]}
```

#### What happens here?
- `mcp_tools` was imported dynamically on startup from the API Gateway:
  - `get_user_profile`
  - `get_order_details`
  - `cancel_order`
- Ollama (`llama3.1:8b`) receives the prompt and decides it cannot answer from memory.
- It returns an `AIMessage` with structured tool call metadata:
  ```json
  {
    "name": "get_order_details",
    "args": {
      "id": "427e35ad-dada-4c13-acf7-7a017aa964a7"
    },
    "id": "call_abc123",
    "type": "tool_call"
  }
  ```

---

### Step 6: Criticality Router (`should_continue`)

The graph evaluates where to send the tool call:

```python
# services/ai/app/agent/graph.py (Lines 102-113)
SENSITIVE_TOOLS = {
    "cancel_order",
    "request_refund",
    "process_refund",
    "delete_account",
    "transfer_funds",
}

def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tc in last_message.tool_calls:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            if name in SENSITIVE_TOOLS:
                return "sensitive_tools"
        return "safe_tools"
    return "end"
```

- The requested tool is `"get_order_details"`.
- `"get_order_details"` is **NOT** in `SENSITIVE_TOOLS`.
- **Decision**: Returns `"safe_tools"`.

---

### Step 7: Tool Execution Node (`safe_tools` - Autonomous Tier 2)

Notice the graph compilation in `graph.py`:
```python
compiled_graph = workflow.compile(
    checkpointer=memory_saver,
    interrupt_before=["sensitive_tools"]  # ONLY sensitive_tools interrupts!
)
```
Because the destination node is `"safe_tools"`, **no interruption occurs**. The graph immediately invokes the tool closure defined in `mcp_client.py`.

```python
# services/ai/app/agent/mcp_client.py (Lines 50-74)
def make_call_func(t_name="get_order_details"):
    def call_func(**kwargs):
        call_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": t_name,
                "arguments": kwargs  # {"id": "427e35ad-dada-4c13-acf7-7a017aa964a7"}
            },
            "id": 2
        }
        res = requests.post("http://localhost:8080/api/v1/mcp", json=call_payload, timeout=5)
        ...
```

---

### Step 8: Network Hop 1 — AI Service to API Gateway (`:8080`)

The AI Service sends a standard HTTP JSON-RPC 2.0 request over TCP to the API Gateway:

```http
POST /api/v1/mcp HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_order_details",
    "arguments": {
      "id": "427e35ad-dada-4c13-acf7-7a017aa964a7"
    }
  },
  "id": 2
}
```

---

### Step 9: API Gateway MCP Dispatch (`api-gateway/handler/mcp.go`)

In `api-gateway/handler/mcp.go`:

```go
// Lines 38-62: HandleMCP router
func (h *GatewayHandler) HandleMCP(c *gin.Context) {
    ...
    switch req.Method {
    case "tools/call":
        h.handleCallTool(c, req.Params, req.ID)
    }
}
```

Inside `handleCallTool` (Lines 164-190):
```go
case "get_order_details":
    var args struct {
        ID string `json:"id"`
    }
    json.Unmarshal(callParams.Arguments, &args)

    // Call internal Order Service over gRPC
    resp, err := h.orderClient.GetOrder(ctx, &orderpb.GetOrderRequest{Id: args.ID})
```

---

### Step 10: Network Hop 2 — API Gateway to Order Service (`:50052` via gRPC)

The generated client `h.orderClient` in `proto-schemas/orderpb/order_grpc.pb.go` invokes:
```go
err := c.cc.Invoke(ctx, "/order.OrderService/GetOrder", in, out, cOpts...)
```

An HTTP/2 binary frame travels across the persistent TCP socket between API Gateway and Order Service:

```http
POST /order.OrderService/GetOrder HTTP/2
Host: localhost:50052
Content-Type: application/grpc

[Protobuf Binary Payload: id="427e35ad-dada-4c13-acf7-7a017aa964a7"]
```

---

### Step 11: Order Service Execution (`services/order/`)

1. **gRPC Server Handler** (`services/order/internal/handler/grpc.go:Lines 46-61`):
   ```go
   func (h *OrderHandler) GetOrder(ctx context.Context, req *pb.GetOrderRequest) (*pb.OrderResponse, error) {
       order, err := h.orderService.GetOrder(ctx, req.GetId())
       ...
       return &pb.OrderResponse{
           Id:        order.ID,
           UserId:    order.UserID,
           ProductId: order.ProductID,
           Quantity:  order.Quantity,
           Status:    order.Status,
       }, nil
   }
   ```

2. **Service Layer** (`services/order/internal/service/order_service.go:Lines 74-79`):
   ```go
   func (s *orderService) GetOrder(ctx context.Context, id string) (*repository.Order, error) {
       return s.orderRepo.GetByID(ctx, id)
   }
   ```

3. **Database Repository Layer** (`services/order/internal/repository/postgres_order_repository.go:Lines 26-36`):
   ```go
   func (r *postgresOrderRepository) GetByID(ctx context.Context, id string) (*Order, error) {
       var order Order
       err := r.db.WithContext(ctx).Where("id = ?", id).First(&order).Error
       return &order, nil
   }
   ```

4. **PostgreSQL Database**:
   GORM executes:
   ```sql
   SELECT * FROM orders WHERE id = '427e35ad-dada-4c13-acf7-7a017aa964a7' LIMIT 1;
   ```
   Found row: `status = 'PENDING'`, `quantity = 2`, etc.

---

### Step 12: Returning Down the Chain (Order Service $\to$ Gateway $\to$ AI Service)

1. **Order Service** serializes `*orderpb.OrderResponse` and returns over HTTP/2.
2. **API Gateway** formats the result into a JSON string:
   ```go
   resMap := map[string]interface{}{
       "id":         resp.GetId(),
       "user_id":    resp.GetUserId(),
       "product_id": resp.GetProductId(),
       "quantity":   resp.GetQuantity(),
       "status":     resp.GetStatus(), // "PENDING"
   }
   ```
   And writes the MCP JSON-RPC response:
   ```json
   {
     "jsonrpc": "2.0",
     "result": {
       "content": [
         {
           "type": "text",
           "text": "{\"id\":\"427e35ad-dada-4c13-acf7-7a017aa964a7\",\"product_id\":\"5a6af266-4232-426b-8e20-193812043241\",\"quantity\":2,\"status\":\"PENDING\",\"user_id\":\"5a6af266-4232-426b-8e20-193812042952\"}"
         }
       ]
     },
     "id": 2
   }
   ```
3. **AI Service** (`mcp_client.py`) extracts `content[0].text`.
4. LangGraph automatically wraps this into a `ToolMessage` and appends it to the conversation state.

---

### Step 13: Second LLM Pass (Answer Synthesis)

The edge `workflow.add_edge("safe_tools", "llm")` loops back to `llm_node`.

`llm_node` is called with all 3 messages in state:
1. `HumanMessage("What is the status of order 427e35ad-dada-4c13-acf7-7a017aa964a7?")`
2. `AIMessage(tool_calls=[get_order_details])`
3. `ToolMessage("{\"id\":\"...\", \"status\":\"PENDING\", ...}")`

Ollama reads the `ToolMessage` result and generates natural language output:
```
"The status of order 427e35ad-dada-4c13-acf7-7a017aa964a7 is PENDING."
```

Next, `should_continue` runs:
- `final_message` has no new `tool_calls`.
- Returns `"end"`.
- LangGraph completes execution.

---

### Step 14: Checkpointing & Semantic Caching (`main.py`)

1. **Postgres Checkpointer** (`checkpointer.py`):
   Serializes the complete conversation state (`HumanMessage`, `AIMessage`, `ToolMessage`, final response) and writes to PostgreSQL `checkpoints` table.
2. **Redis Semantic Caching** (`cache.py`):
   ```python
   # services/ai/app/main.py (Lines 119-121)
   if response_text and response_text.strip():
       set_cached_answer(req.message, response_text, thread_id=req.thread_id)
   ```
   Stores the query embedding vector and answer in Redis with a 1-hour TTL.

---

### Step 15: HTTP Response Sent to User

FastAPI returns the final JSON:

```json
{
  "response": "The status of order 427e35ad-dada-4c13-acf7-7a017aa964a7 is PENDING.",
  "thread_id": "t5",
  "role": "ai",
  "cache_hit": false
}
```

---

## ⚡ Summary Table: Component Responsibility Matrix

| Step | Component | Technology | File / Location | Responsibility |
| :--- | :--- | :--- | :--- | :--- |
| **1** | HTTP Ingress | FastAPI / Uvicorn | `services/ai/app/main.py:49` | Accepts incoming JSON payload |
| **2** | Guardrails | Python Regex | `services/ai/app/agent/guardrails.py:53` | Verifies no API key / secret leak attacks |
| **3** | Semantic Cache | Redis + Ollama | `services/ai/app/db/cache.py:73` | Checks for cached response (Miss on turn 1) |
| **4** | Entry Router | LangGraph | `services/ai/app/agent/graph.py:80` | Detects order UUID $\to$ routes to LLM |
| **5** | LLM Engine | Ollama `llama3.1:8b` | `services/ai/app/agent/graph.py:54` | Emits `get_order_details` tool call |
| **6** | Criticality Router | LangGraph | `services/ai/app/agent/graph.py:102` | Classifies tool as safe $\to$ routes to `safe_tools` |
| **7** | MCP Client | Python Requests | `services/ai/app/agent/mcp_client.py:50` | Sends JSON-RPC 2.0 payload |
| **8** | API Gateway | Gin (Go) | `api-gateway/handler/mcp.go:38` | MCP Server translates tool to gRPC |
| **9** | Order Service | gRPC (Go) | `services/order/internal/handler/grpc.go:46` | Handles RPC and delegates to business logic |
| **10**| Database | GORM + PostgreSQL | `services/order/internal/repository/...` | Executes SQL query on `orders` table |
| **11**| LLM Synthesis | Ollama `llama3.1:8b` | `services/ai/app/agent/graph.py:54` | Turns raw JSON into human response |
| **12**| Persistence | Postgres + Redis | `checkpointer.py` & `cache.py` | Saves state and updates semantic cache |

---

## 🧩 Advanced Architectural Q&A: Multi-Node Orchestration & Complex Queries

### Question 1: In scenarios where multiple nodes must run (e.g. Tool Call + RAG + LLM), who decides whether to execute another node or prepare the final answer?

In an Agentic State Graph, there are **two distinct patterns** for who controls the execution loop:

#### Pattern A: The LLM as the Autonomous Controller (ReAct Loop)
In this pattern, the graph relies on the LLM's own reasoning to decide what to do next:
1. The graph gives the LLM access to **Tools** for all external data sources (e.g., `get_order_details`, `lookup_knowledge_base`, `cancel_order`).
2. When the LLM outputs a message:
   - If `hasattr(message, "tool_calls") and message.tool_calls`: The conditional edge `should_continue` routes to the tool node.
   - If `not message.tool_calls`: The LLM has concluded it has enough context to answer $\implies$ routes to `END`.
3. **Who decides?** The LLM autonomously decides at each turn:
   - Turn 1: *"I need the order details."* $\to$ calls `get_order_details`.
   - Turn 2: *"Now I have order placed date, but I need the refund policy."* $\to$ calls `lookup_knowledge_base("cancellation refund policy")`.
   - Turn 3: *"I have both order date and policy. I can now evaluate eligibility."* $\to$ outputs plain text final answer $\to$ loops ends!

#### Pattern B: The Graph Router as the Controller (Deterministic State Machine)
In this pattern, Python functions inspect state variables and determine the next step programmatically:
- A router function (e.g. `evaluator_router(state)`) checks:
  - Does the user query contain policy keywords (`refund`, `policy`)?
  - Has `rag` already executed?
  - Have order details been retrieved?
- If conditions aren't met, the router routes to the missing node (`rag` or `tools`).
- Once all required data is in state, the router routes to `llm` to produce the final synthesis.

---

### Question 2: Why did the system fail on:
> `"This is my order id 427e35ad-dada-4c13-acf7-7a017aa964a7, am I eligible for refund if I cancel the order"`

And why did it awkwardly output:
> *"I can call the `cancel_order` tool on your behalf. Would you like me to do that?"*

This query failed due to **4 distinct architectural disconnects** in the current system:

#### 1. The Entry Router Completely Cut Off RAG (`graph.py`)
In `graph.py`:
```python
def route_question(state: AgentState):
    ...
    # Rule: If UUID is present, bypass RAG and route directly to LLM
    if re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}', last_message) ...:
        return "llm"
```
Because the message contained the order UUID `427e35ad-...`, `route_question` sent the query straight to `llm`. 
In our current graph topology:
```
route_question ──> llm ──> safe_tools ──> llm ──> END
```
There is **no edge connecting `llm` or `safe_tools` to `rag`**. Once `route_question` picked `"llm"`, the `rag` node became completely unreachable. The LLM was left completely unaware of the 24-hour cancellation rule!

#### 2. Missing `created_at` in the Order Contract (`order.proto` & `mcp.go`)
Even if the LLM knew the "24-hour rule", it could not evaluate eligibility because `get_order_details` didn't return the order date:
- In `order.proto`, `OrderResponse` only defines: `id, user_id, product_id, quantity, status`.
- In `api-gateway/handler/mcp.go`, `get_order_details` outputs:
  ```json
  {"id": "...", "status": "PENDING", "quantity": 2, "product_id": "...", "user_id": "..."}
  ```
The database table `orders` has a `created_at` timestamp column, but it was **never included in the Protobuf message or MCP tool output**. The LLM literally had no date to check!

#### 3. RAG is a Fixed Upfront Node, Not an On-Demand Tool
Currently, RAG is implemented as an upfront node (`rag_node`) that runs before the LLM, rather than an MCP/LangChain **Tool** (`lookup_knowledge_base(query)`).
- When a query needs **both** an Order lookup **and** Knowledge Base lookup, a static node cannot adapt.
- Making RAG a callable tool empowers the LLM to search policies whenever it encounters a policy question in the middle of a workflow.

#### 4. Prompt Leakage & Hallucinated Action
Because the LLM:
1. Did not have the 24-hour refund policy in context,
2. Did not have the order creation date,
3. Saw that it possessed a tool named `cancel_order`,
It defaulted to asking the user if they wanted it to call the `cancel_order` tool, exposing internal tool names to the end user.

---

---

## 🧠 Deep Dive Q&A: LangGraph Edge Routing & Execution Decision Mechanics

### Question 1: Where is the sequence `route_question ──> llm ──> safe_tools ──> llm ──> END` defined? Is this where it is defined?
```python
# Register Nodes
workflow.add_node("rag", rag_node)
workflow.add_node("llm", llm_node)
workflow.add_node("safe_tools", ToolNode(mcp_tools))
workflow.add_node("sensitive_tools", ToolNode(mcp_tools))
```

**Answer:**
**No.** `workflow.add_node(...)` only registers the **rooms (vertices)** in the building. It does **not** define the **hallways (edges)** connecting them.

In LangGraph:
- **`workflow.add_node("name", fn)`** specifies: *"Here is a worker function and its name."* (No sequence or order).
- **`workflow.set_conditional_entry_point(...)`** and **`workflow.add_edge(...)` / `workflow.add_conditional_edges(...)`** define the **actual execution sequence and transitions**:

```python
# 1. Entry Edge: Decides WHERE to start when a request enters the graph
workflow.set_conditional_entry_point(
    route_question,
    {
        "rag": "rag",
        "llm": "llm"
    }
)

# 2. Static Edge: After rag_node completes, always transition to llm_node
workflow.add_edge("rag", "llm")

# 3. Conditional Edge: After llm_node completes, should_continue decides where to go
workflow.add_conditional_edges(
    "llm",
    should_continue,
    {
        "safe_tools": "safe_tools",           # If LLM emits low-risk tool call (e.g. get_order_details)
        "sensitive_tools": "sensitive_tools", # If LLM emits high-risk tool call (e.g. cancel_order)
        "end": END                            # If LLM output text with no tool calls -> Done!
    }
)

# 4. Loop-back Edges: After executing tools, feed results back to the LLM
workflow.add_edge("safe_tools", "llm")
workflow.add_edge("sensitive_tools", "llm")
```

---

### Question 2: Why did it seem fixed if different scenarios need different paths?
> *"Why is it fixed, because it can be different for different scenarios?"*

**Answer:**
The sequence **is NOT fixed**! It is a **dynamic state machine (ReAct loop)** that traverses different sub-paths depending on runtime conditions:

| User Scenario | Execution Path Traversed | Why? |
| :--- | :--- | :--- |
| **"What is your return policy?"** | `route_question` $\to$ `rag` $\to$ `llm` $\to$ `END` | General policy $\to$ RAG loads docs $\to$ LLM answers $\to$ No tools needed. |
| **"What is the status of order X?"** | `route_question` $\to$ `llm` $\to$ `safe_tools` $\to$ `llm` $\to$ `END` | UUID detected $\to$ LLM calls `get_order_details` $\to$ `safe_tools` runs $\to$ LLM summarizes $\to$ `END`. |
| **"Cancel my order X"** | `route_question` $\to$ `llm` $\to$ `sensitive_tools` *(PAUSE - HITL)* | High-stakes action $\to$ Pauses before `sensitive_tools` awaiting supervisor approval. |
| **"Am I eligible for refund for order X?"** | `route_question` $\to$ `llm` $\to$ `safe_tools` $\to$ `llm` $\to$ `END` | LLM calls `get_order_details` $\to$ checks `created_at` against 24h refund policy $\to$ answers. |

It only *appeared* fixed because:
1. `route_question` had a hardcoded regex that routed straight to `llm` whenever a UUID was present.
2. In our previous configuration, `rag` was only an entry node, not available as an on-demand tool during the ReAct loop.

---

### Question 3: `route_question(state)` vs `should_continue(state)` — What is the difference?

| Dimension | `route_question(state)` | `should_continue(state)` |
| :--- | :--- | :--- |
| **Role** | **Entry Router** (Initial Dispatcher) | **In-Flight Tool Router** (ReAct Loop Decider) |
| **When it runs** | **Exactly once** at step 0 (when request first enters graph). | **After every `llm_node` invocation** (can run 1, 2, 3+ times). |
| **What it inspects** | Raw incoming user message text (`state["messages"][-1].content`). | The LLM's structured output object (`state["messages"][-1].tool_calls`). |
| **Decisions made** | Does this user need Knowledge Base context (`rag`) or direct reasoning (`llm`)? | Did the LLM request a tool? Is it safe (`safe_tools`), sensitive (`sensitive_tools`), or is it done (`END`)? |

---

### Question 4: After executing a node, who decides the next step?

**Answer:**
The **LangGraph StateGraph Engine** decides by looking up the edge table for the node that just completed:

1. **If connected by a normal edge (`workflow.add_edge("A", "B")`)**:
   The engine **unconditionally transitions** to node `B`.
   *(Example: `workflow.add_edge("safe_tools", "llm")` means after any safe tool finishes, control always returns to `llm`)*.

2. **If connected by a conditional edge (`workflow.add_conditional_edges("A", router_fn, mapping)`)**:
   The engine invokes `router_fn(state)`. The returned string key is matched against `mapping` to determine the next destination.
   *(Example: `should_continue` looks at `state["messages"][-1].tool_calls`)*.

---

## ✅ Applied Fix & Live Verification

To solve the refund eligibility issue cleanly and comprehensively, four coordinated changes were made across the stack:

### 1. Protobuf Contract & Order Microservice (`proto-schemas/order.proto` & `services/order`)
- Added `string created_at = 6;` to `OrderResponse` message in `order.proto`.
- Recompiled protobufs with `protoc`.
- Updated `services/order/internal/handler/grpc.go` to return `CreatedAt: order.CreatedAt.Format(time.RFC3339)` across `GetOrder`, `CreateOrder`, and `CancelOrder`.

### 2. API Gateway MCP Tool (`api-gateway/handler/mcp.go`)
- Updated `get_order_details` tool handler to serialize `created_at: resp.GetCreatedAt()` into the MCP JSON-RPC tool response.

### 3. AI Service Knowledge Tool & Consolidated System Prompt (`services/ai/app/agent/graph.py`)
- Added `@tool def lookup_knowledge_base(query: str) -> str` to make RAG callable on-demand as a standard tool in `all_tools`.
- Consolidated system prompt injection in `llm_node` so that any RAG context messages are cleanly merged into the primary root system message before the user message (preventing chat template token confusion in `llama3.1:8b`).
- Enforced strict execution rules in `get_system_prompt()`:
  - If an order ID is provided, immediately call `get_order_details` without asking permission or emitting conversational filler.
  - Compare `created_at` against the current timestamp and company 24-hour refund window.
  - Never reveal internal tool names (`get_order_details`, `cancel_order`, etc.) to the user.

---

### 🧪 Live Verification Results

#### Test 1: Complex Refund Eligibility Query
**Request:**
```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "This is my order id 427e35ad-dada-4c13-acf7-7a017aa964a7, am I eligible for refund if I cancel the order",
    "thread_id": "test-refund-live-verification",
    "user_id": "user1"
  }'
```

**Actual Response:**
```json
{
  "response": "Your order was placed on 2026-10-13 01:08:00. Since you're asking about refund eligibility and this is your order ID, I've looked up the details directly.\n\nConsidering our company's 24-hour refund policy, since over 6 days have passed since purchase, unfortunately, you are no longer eligible for a full refund if you cancel the order.",
  "thread_id": "test-refund-live-verification",
  "role": "ai",
  "cache_hit": false
}
```
**Outcome:**
1. LLM autonomously called `get_order_details` tool via MCP.
2. Retrieved `created_at: "2026-10-13T01:08:00+05:30"`.
3. Compared against current date (`2026-10-19`).
4. Correctly calculated >6 days elapsed (>24h window) and informed user they are not eligible for a full refund.
5. Zero leakage of internal tool names!

#### Test 2: High-Stakes Mutation (Tier 3 Human-in-the-Loop Interrupt)
**Request:**
```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Please cancel order 427e35ad-dada-4c13-acf7-7a017aa964a7 for me",
    "thread_id": "test-hitl-cancel-verify"
  }'
```
**Response:**
```json
{
  "status": "interrupted",
  "message": "Action requires human supervisor approval to execute tool(s): cancel_order",
  "thread_id": "test-hitl-cancel-verify",
  "tool_calls": [{"name": "cancel_order", "args": {"id": "427e35ad-dada-4c13-acf7-7a017aa964a7"}}],
  "role": "ai"
}
```

#### Test 3: Supervisor Approval & Database Mutation
**Request:**
```bash
curl -s -X POST http://localhost:8000/api/v1/agent/approve \
  -H "Content-Type: application/json" \
  -d '{"thread_id": "test-hitl-cancel-verify", "approved": true}'
```
**Response:**
```json
{
  "status": "resumed",
  "thread_id": "test-hitl-cancel-verify",
  "response": "Your order, 427e35ad-dada-4c13-acf7-7a017aa964a7, has been cancelled. A full refund will be processed within the next few business days.",
  "role": "ai"
}
```
**PostgreSQL Verification:**
```sql
SELECT id, status, updated_at FROM orders WHERE id = '427e35ad-dada-4c13-acf7-7a017aa964a7';
-- Status: CANCELLED
```

#### Test 4: Automated Evaluation Suite
```bash
./venv/bin/python evals/eval_suite.py
```
**Result:** `4/4 PASSED` (Tier 1 Security Guardrail, Prompt Injection, PII Redaction, Semantic Cache Invalidation).

---

## 🔄 Multi-Turn Memory & State Checkpointing: End-to-End Code Flow (Connected APIs)

This section demonstrates how multi-turn conversation memory works across two separate, sequential HTTP requests sharing the same `thread_id`.

### Example Test Scenario

#### Call 1: User establishes context
```bash
curl --location 'http://localhost:8000/api/v1/chat' \
--header 'Content-Type: application/json' \
--data '{
    "message": "My preferred language is English.",
    "thread_id": "thread-ollama-1",
    "user_id": "user1"
}'
```

#### Call 2: User queries context set in Call 1
```bash
curl --location 'http://localhost:8000/api/v1/chat' \
--header 'Content-Type: application/json' \
--data '{
    "message": "What is my preferred language?",
    "thread_id": "thread-ollama-1",
    "user_id": "user1"
}'
```

---

### 1. Underlying Architecture & Persistence Mechanisms

#### A. The Reducer Pattern in State Definition
In [`services/ai/app/agent/state.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/agent/state.py):
```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: str
    thread_id: str
```
- The `add_messages` annotation acts as an immutable reducer function. When a new turn starts, rather than replacing the previous messages array, it **appends** new user/AI messages to the existing list or updates existing messages by ID.

#### B. The PostgreSQL Checkpoints Table
In [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py):
```sql
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id     VARCHAR(255) NOT NULL,
    checkpoint_id VARCHAR(255) NOT NULL,
    parent_id     VARCHAR(255),
    checkpoint    BYTEA NOT NULL,
    metadata      BYTEA,
    PRIMARY KEY (thread_id, checkpoint_id)
);
```
- Each record represents a discrete graph state snapshot serialized via Python `pickle`.
- `parent_id` points to the preceding checkpoint snapshot, forming a Merkle DAG of conversation history.

---

### 2. End-to-End Code Flow: How Both APIs Are Connected

```text
API 1: "My preferred language is English."
────────────────────────────────────────────────────────────────────────────────────────────
1. Client sends HTTP POST /api/v1/chat with thread_id: "thread-ollama-1"
   │
2. services/ai/app/main.py:L109
   compiled_graph.astream(inputs, config={"configurable": {"thread_id": "thread-ollama-1"}})
   │
3. PostgresCheckpointSaver.aget_tuple() ──> get_tuple() (app/db/checkpointer.py:L14)
   └── Executes SQL:
       SELECT checkpoint, metadata, parent_id, checkpoint_id 
       FROM checkpoints 
       WHERE thread_id = 'thread-ollama-1' 
       ORDER BY checkpoint_id DESC LIMIT 1;
   └── Result: None (First message in this thread).
   │
4. State is initialized:
   state["messages"] = [HumanMessage("My preferred language is English.")]
   │
5. route_question(state) (app/agent/graph.py:L140)
   └── No order UUID or policy keywords found ──> returns "llm"
   │
6. llm_node(state) (app/agent/graph.py:L102)
   └── Model input: [SystemMessage, HumanMessage("My preferred language is English.")]
   └── LLM generates: AIMessage("Got it! I will remember that your preferred language is English.")
   │
7. should_continue(state) (app/agent/graph.py:L167)
   └── No tool calls requested ──> returns "end" (END)
   │
8. PostgresCheckpointSaver.aput() ──> put() (app/db/checkpointer.py:L70)
   └── Serializes state dict: {'messages': [HumanMessage, AIMessage], ...} via pickle.dumps()
   └── Inserts row into `checkpoints` table:
       thread_id: "thread-ollama-1"
       checkpoint_id: "1f1cd815-..."
       parent_id: None
       checkpoint: <binary blob>
   │
9. Return HTTP 200 {"response": "Got it! I will remember that your preferred language is English."}


API 2: "What is my preferred language?" (Same thread_id: "thread-ollama-1")
────────────────────────────────────────────────────────────────────────────────────────────
1. Client sends HTTP POST /api/v1/chat with thread_id: "thread-ollama-1"
   │
2. services/ai/app/main.py:L109
   compiled_graph.astream(inputs, config={"configurable": {"thread_id": "thread-ollama-1"}})
   │
3. PostgresCheckpointSaver.aget_tuple() ──> get_tuple() (app/db/checkpointer.py:L14)
   └── Executes SQL:
       SELECT checkpoint, metadata, parent_id, checkpoint_id 
       FROM checkpoints 
       WHERE thread_id = 'thread-ollama-1' 
       ORDER BY checkpoint_id DESC LIMIT 1;
   └── Result: Found previous checkpoint ("1f1cd815-...")
   └── Deserializes pickle blob:
       [HumanMessage("My preferred language is English."), AIMessage("Got it! ...")]
   │
4. add_messages reducer (app/agent/state.py:L10)
   └── Merges restored history with new input:
       state["messages"] = [
           HumanMessage("My preferred language is English."),
           AIMessage("Got it! I will remember that your preferred language is English."),
           HumanMessage("What is my preferred language?")
       ]
   │
5. route_question(state) (app/agent/graph.py:L140) ──> returns "llm"
   │
6. llm_node(state) (app/agent/graph.py:L119)
   └── Passes full conversational sequence to model:
       model_input_msgs = [
           SystemMessage(...),
           HumanMessage("My preferred language is English."),
           AIMessage("Got it! I will remember that your preferred language is English."),
           HumanMessage("What is my preferred language?")
       ]
   └── LLM reads earlier turn, resolves context, and generates:
       AIMessage("Your preferred language is English.")
   │
7. should_continue(state) ──> returns "end"
   │
8. PostgresCheckpointSaver.aput() ──> put() (app/db/checkpointer.py:L70)
   └── Saves updated 4-message state snapshot into PostgreSQL checkpoints table
       with parent_id pointing to "1f1cd815-...".
   │
9. Return HTTP 200 {"response": "Your preferred language is English."}
```

---

### 3. Key Purposes of the `checkpoints` Table Beyond Chat Memory

1. **Human-in-the-Loop (HITL) Interrupt & Resume**:
   - Compiling the graph with `interrupt_before=["sensitive_tools"]` pauses graph execution before high-stakes mutations (e.g., `cancel_order`).
   - The paused state is saved in `checkpoints`. When the operator calls `/api/v1/chat/approve`, LangGraph rehydrates from the checkpoint and resumes execution seamlessly.
2. **Stateless Microservice Scaling & Crash Recovery**:
   - Because all memory lives in PostgreSQL, the Python AI container is completely stateless. Replicas can be restarted, scaled, or load-balanced without session loss.
3. **Time-Travel Debugging & State Auditing**:
   - The `(checkpoint_id, parent_id)` relationship creates an immutable directed acyclic graph (DAG) of state history, enabling rollback, replay, and regulatory compliance audits.

---

## 🛡️ High-Stakes Mutation (Tier 3): End-to-End Code Flow & Human-in-the-Loop Breakpoint Interrupt

This section provides the complete code-level execution walkthrough for a destructive state mutation request (order cancellation) protected by **LangGraph State Machine Breakpoints**.

### Scenario Request
```bash
curl --location 'http://localhost:8000/api/v1/chat' \
--header 'Content-Type: application/json' \
--data '{
    "message": "Please cancel order 427e35ad-dada-4c13-acf7-7a017aa964a7",
    "thread_id": "t6"
}'
```

---

### Phase 1: Request Processing & Breakpoint Interruption

```text
[ USER / CLIENT ]
       │
       │ 1. HTTP POST :8000/api/v1/chat
       ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   AI SERVICE (FastAPI - Port 8000)                     │
│                                                                        │
│ 2. Guardrails Check: inspect_and_sanitize() ──> [PASSED]               │
│ 3. Semantic Cache Check (Redis) ──> [MISS]                             │
│ 4. Cache Invalidation: invalidate_cache(thread_id="t6")                │
│ 5. LangGraph Execution:                                                │
│    • route_question() detects order UUID & "cancel" ──> "llm"          │
│    • llm_node() emits ToolCall: cancel_order(id="427e35ad...")         │
│    • should_continue() detects SENSITIVE_TOOLS ──> "sensitive_tools"   │
│                                                                        │
│ 6. 🛑 BREAKPOINT HIT: interrupt_before=["sensitive_tools"]             │
│    • Execution HALTS immediately before tool runs                      │
│    • PostgresCheckpointSaver.aput() freezes state in PostgreSQL        │
│                                                                        │
│ 7. Return HTTP 200 {"status": "interrupted", "tool_calls": [...]}      │
└────────────────────────────────────────────────────────────────────────┘
```

#### Detailed Step-by-Step Code Flow (Phase 1):

1. **Ingress & Security Guardrails** ([`services/ai/app/main.py:L84-L97`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/main.py#L84-L97)):
   - Request parsed into `ChatRequest(message="Please cancel order 427e35ad-...", thread_id="t6")`.
   - `inspect_and_sanitize()` verifies no prompt injections or credential leak attempts.
   - `get_cached_answer()` checks Redis Semantic Cache $\rightarrow$ **Cache MISS**.
   - `invalidate_cache(thread_id="t6")` flushes stale cache keys for session `"t6"`.

2. **Graph Invocation & Checkpointer Setup** ([`services/ai/app/main.py:L99-L109`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/main.py#L99-L109)):
   - Config: `{"configurable": {"thread_id": "t6"}}`.
   - Input: `HumanMessage("Please cancel order 427e35ad-dada-4c13-acf7-7a017aa964a7")`.
   - `compiled_graph.astream(inputs, config=config)` initializes the step.

3. **Entry Routing** ([`services/ai/app/agent/graph.py:L140-L157`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/agent/graph.py#L140-L157)):
   ```python
   if (
       re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}', last_message)
       or "cancel order" in last_message
   ):
       return "llm"
   ```
   - Matches `"cancel order"` and the UUID pattern. Routes directly to **`"llm"`**.

4. **Model Intent & Tool Call Emission** ([`services/ai/app/agent/graph.py:L102-L136`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/agent/graph.py#L102-L136)):
   - LLM reads the cancellation request and emits a structured tool call:
     ```python
     AIMessage(
         content="",
         tool_calls=[{"name": "cancel_order", "args": {"id": "427e35ad-dada-4c13-acf7-7a017aa964a7"}}]
     )
     ```

5. **Conditional Tool-Call Router** ([`services/ai/app/agent/graph.py:L167-L178`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/agent/graph.py#L167-L178)):
   ```python
   SENSITIVE_TOOLS = {"cancel_order", "request_refund", "process_refund", "delete_account", "transfer_funds"}

   for tc in last_message.tool_calls:
       if tc["name"] in SENSITIVE_TOOLS:
           return "sensitive_tools"
   ```
   - Matches `"cancel_order"` as a high-stakes mutation. Routes to **`"sensitive_tools"`**.

6. **The Breakpoint Pause** ([`services/ai/app/agent/graph.py:L215-L218`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/agent/graph.py#L215-L218)):
   ```python
   compiled_graph = workflow.compile(
       checkpointer=memory_saver,
       interrupt_before=["sensitive_tools"]
   )
   ```
   - LangGraph intercepts execution **before** entering `sensitive_tools`.
   - The mutation is **NOT executed**.
   - `PostgresCheckpointSaver.aput()` writes the suspended snapshot into PostgreSQL `checkpoints`.

7. **API Response to Client** ([`services/ai/app/main.py:L117-L129`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/main.py#L117-L129)):
   ```json
   {
     "status": "interrupted",
     "message": "Action requires human supervisor approval to execute tool(s): cancel_order",
     "thread_id": "t6",
     "tool_calls": [
       {
         "name": "cancel_order",
         "args": { "id": "427e35ad-dada-4c13-acf7-7a017aa964a7" }
       }
     ],
     "role": "ai",
     "cache_hit": false
   }
   ```

---

### Phase 2: Supervisor Approval & Live Execution

When a supervisor authorizes the action:
```bash
curl --location 'http://localhost:8000/api/v1/agent/approve' \
--header 'Content-Type: application/json' \
--data '{
    "thread_id": "t6",
    "approved": true
}'
```

```text
[ HUMAN SUPERVISOR ]
         │
         │ 1. HTTP POST :8000/api/v1/agent/approve (approved: true)
         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   AI SERVICE (FastAPI - Port 8000)                     │
│                                                                        │
│ 2. approve_tool_execution() loads state from PostgreSQL checkpoints    │
│ 3. compiled_graph.astream(None, config=config) resumes execution       │
│ 4. Node: sensitive_tools executes ToolNode: cancel_order               │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     │ 5. Network Hop 1: HTTP POST :8080/api/v1/mcp
                                     │    (JSON-RPC 2.0 tools/call: cancel_order)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   API GATEWAY (Gin - Port 8080)                        │
│                                                                        │
│ 6. handleCallTool() dispatches tool: "cancel_order"                    │
│ 7. Invokes gRPC Client: h.orderClient.CancelOrder(ctx, req)            │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     │ 8. Network Hop 2: HTTP/2 gRPC :50052
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   ORDER SERVICE (gRPC - Port 50052)                    │
│                                                                        │
│ 9. OrderHandler.CancelOrder() in internal/handler/grpc.go              │
│ 10. GORM: UPDATE orders SET status = 'CANCELLED' WHERE id = '427e...'  │
│ 11. Kafka Producer: publishes ORDER_CANCELLED event to "order-events"  │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     │ 12. gRPC Response (*orderpb.CancelOrderResponse)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   AI SERVICE (FastAPI - Port 8000)                     │
│                                                                        │
│ 13. ToolMessage appended: "Order 427e35ad... cancelled successfully"  │
│ 14. Edge: sensitive_tools ──> llm_node                                │
│ 15. LLM generates final customer message                              │
│ 16. should_continue() ──> END                                          │
│ 17. PostgresCheckpointSaver saves completed state                      │
│ 18. Return HTTP 200 {"status": "resumed", "response": "..."}           │
└────────────────────────────────────────────────────────────────────────┘
```

#### Verification After Approval:
- **Response Received:**
  ```json
  {
    "status": "resumed",
    "thread_id": "t6",
    "response": "Your order 427e35ad-dada-4c13-acf7-7a017aa964a7 has been successfully cancelled. A full refund has been initiated.",
    "role": "ai"
  }
  ```
- **PostgreSQL Database Verification:**
  ```sql
  SELECT id, status, updated_at FROM orders WHERE id = '427e35ad-dada-4c13-acf7-7a017aa964a7';
  -- Result: status = 'CANCELLED'
  ```
- **Kafka Event Broadcast:**
  Topic `order-events` receives:
  ```json
  {
    "event_type": "ORDER_CANCELLED",
    "order_id": "427e35ad-dada-4c13-acf7-7a017aa964a7",
    "timestamp": "2026-10-22T01:10:00Z"
  }
  ```



