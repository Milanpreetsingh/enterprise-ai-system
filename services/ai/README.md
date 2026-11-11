# AI Support Microservice

The **AI Service** is a Python microservice built with **FastAPI**, **LangGraph**, **LangChain**, and **PostgreSQL (`pgvector`)**. It acts as an intelligent customer support agent capable of multi-turn conversational memory, semantic context retrieval (RAG), and dynamic tool-calling via the **Model Context Protocol (MCP)**.

---

## 🚀 Key Responsibilities

1. **Stateful Agent Graph (LangGraph):** Manages conversational flow using a state machine (`StateGraph`). Supports conditional routing for RAG retrieval and a **ReAct (Reasoning & Acting)** loop for tool calling.
2. **Postgres Conversation Memory:** Uses a custom `PostgresCheckpointSaver` to serialize state checkpoints into PostgreSQL (`checkpoints` table) using pickle binary formatting. Conversations survive server restarts based on `thread_id`.
3. **Advanced Vector RAG (`pgvector`):** Generates embeddings and performs semantic similarity search against the PostgreSQL `knowledge_base` table using cosine distance (`<=>` operator) and HNSW indexing.
4. **Dynamic MCP Client:** Connects to the API Gateway's `/api/v1/mcp` endpoint on startup to dynamically import backend microservice tools as LangChain `StructuredTool` objects.
5. **Keyless Local Fallback (Mock Mode):** If no `OPENAI_API_KEY` is provided, the service runs in **Mock Mode**, simulating RAG analysis, tool-calling directives, and response generation so you can run the entire system offline without an OpenAI account!

---

## ⚙️ Environment Variables

Create a `.env` file inside `services/ai`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/supporthub
OPENAI_API_KEY=your-actual-key-here-or-leave-blank-for-mock-mode
PORT=8000
```

---

## 🏃 How to Run Locally

```bash
# 1. Navigate to the AI service directory
cd services/ai

# 2. Create and activate a Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the FastAPI server
uvicorn app.main:app --reload --port 8000
```

---

## 🧪 Testing REST API Endpoints

### 1. Health Check
```bash
curl -X GET http://localhost:8000/health
```

### 2. Seed Document into Vector Store (RAG)
Populate the PostgreSQL `pgvector` knowledge base with a custom policy or support document:
```bash
curl -X POST http://localhost:8000/api/v1/seed \
  -H "Content-Type: application/json" \
  -d '{
    "content": "All cancellation requests must be submitted within 24 hours of purchase for a 100% full refund.",
    "metadata": {"category": "cancellation_policy"}
  }'
```

### 3. Send Chat Request (RAG & Memory Test)
Send a message in a conversation thread (`thread_id`):
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is the cancellation refund policy?",
    "thread_id": "session-101",
    "user_id": "user-uuid-1"
  }'
```

### 4. Test Multi-Turn Memory (Thread Continuity)
Send a message establishing state context:
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "My account name is Alex.",
    "thread_id": "session-101",
    "user_id": "user-uuid-1"
  }'
```
Then ask the assistant to recall your name using the **same** `thread_id`:
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is my account name?",
    "thread_id": "session-101",
    "user_id": "user-uuid-1"
  }'
```
*(The Postgres checkpointer retrieves thread `session-101` from PostgreSQL and recalls "Alex"!)*
