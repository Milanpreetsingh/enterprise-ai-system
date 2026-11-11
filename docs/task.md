# Enterprise Omnichannel AI Support Hub Tasks

- [x] Phase 1: Foundation & Infrastructure Setup
  - [x] Initialize Monorepo directories (`api-gateway`, `services/user`, `services/order`, `services/ai`, `proto-schemas`, `infra`, `frontend-app`)
  - [x] Create `docker-compose.yml` for PostgreSQL (pgvector), Redis, and Kafka (KRaft mode)
  - [x] Validate infrastructure containers spin up correctly
- [x] Phase 2: Go Microservices & API Gateway
  - [x] Set up `protoc` compiler and Go plugins
  - [x] Write `user.proto` and `order.proto` defining gRPC messages and services
  - [x] Generate Go code from both `.proto` files
  - [x] Initialize Go modules (`go mod init`) for Gateway, User Service, and Order Service
  - [x] Scaffold User Service Clean Architecture (Handler, Service, Repository)
  - [x] Add `LoginUser` and `RefreshToken` (JWT logic) to `user.proto` and User Service
  - [x] Implement PostgreSQL Database connection and Repository layer for User Service
  - [x] Connect User Service Handler to Service layer, and Service layer to Repository layer
  - [x] Scaffold Order Service Clean Architecture
  - [x] Implement PostgreSQL Database connection and Repository layer for Order Service
  - [x] Connect Order Service Handler to Service layer, and Service layer to Repository layer
  - [x] Implement inter-service gRPC client: Order Service calls User Service `GetUser`
  - [x] Build API Gateway: JWT Validation Middleware
  - [x] Build API Gateway: REST endpoints (Signup, Login, Refresh, Orders) routed via gRPC
- [x] Phase 3: Event-Driven Architecture (Kafka)
  - [x] Learn core-to-advanced Kafka concepts (Broker, Topic, Partition, Consumer Group, EOS, KRaft) in [kafka_guide.md](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/docs/kafka_guide.md)
  - [x] Set up Kafka client library (`segmentio/kafka-go`) in `services/order` and `services/user`
  - [x] Implement Kafka Producer in Order Service to emit `OrderCreated` events (using Message Keys for ordering)
  - [x] Implement Kafka Consumer in User Service to listen to `OrderCreated` events and update database
  - [x] Validate end-to-end event-driven flow
- [x] Phase 4: AI Service Foundation & Memory
  - [x] Set up Python environment and dependencies (`FastAPI`, `langgraph`, `langchain`, `pgvector`, `psycopg-pool`) in `services/ai`
  - [x] Create FastAPI service with a basic health check and query POST route
  - [x] Build the LangGraph framework (State, Node functions, and routing)
  - [x] Configure Postgres Checkpointer for LangGraph conversation memory persistence
  - [x] Implement Advanced RAG using `pgvector` for context-aware customer support answers
  - [x] Validate multi-turn conversation memory and RAG retrieval
- [x] Phase 5: Model Context Protocol (MCP) Integration
  - [x] Build MCP JSON-RPC Server endpoints in API Gateway to expose `get_user_profile` and `get_order_details` tools
  - [x] Integrate MCP endpoints in API Gateway to dynamically query User and Order gRPC services
  - [x] Implement MCP Client in Python AI service to fetch available tools dynamically
  - [x] Bind MCP tools to LangGraph execution flow allowing agent tool-calling
  - [x] Validate end-to-end tool call execution
- [x] Phase 6: Performance & Real-Time Streaming
  - [x] Implement Redis Semantic Caching in Python AI service to cache responses for duplicate/semantically similar queries
  - [x] Define `ai.proto` with gRPC server streaming RPC (`StreamChat`) and compile Go/Python stubs
  - [x] Implement gRPC streaming server in Python AI service
  - [x] Implement HTTP Server-Sent Events (SSE) streaming endpoint (`GET /api/v1/chat/stream`) in API Gateway
  - [x] Validate Redis cache hits and real-time SSE token streaming
- [x] Phase 7: Advanced AI: Human-in-the-Loop & Guardrails
  - [x] Implement Input Guardrails in Python AI service to detect prompt injections and sanitize PII (passwords, credit cards)
  - [x] Implement Human-in-the-Loop (HITL) node interrupts in LangGraph state machine for high-risk tool operations
  - [x] Add `/api/v1/agent/approve` route to resume interrupted graph threads upon human approval
- [x] Phase 8: Frontend Chatbot Application
  - [x] Build responsive glassmorphism single-page frontend app in `frontend-app`
  - [x] Implement User Authentication UI (Signup/Login JWT token management)
  - [x] Implement E-Commerce Order Placement & History Dashboard
  - [x] Implement Real-Time SSE Typewriter AI Chatbot Interface with Human-in-the-Loop Approval controls
- [x] Phase 9: Observability & Automated Evals
  - [x] Build automated evaluation benchmark suite in Python (`services/ai/evals/eval_suite.py`) testing RAG retrieval accuracy, tool selection correctness, and guardrail sanitization
  - [x] Implement system metrics and latency observability logger (`services/ai/app/observability.py`)

---

# Enterprise SDE-3 Revamp Roadmap (Completed)

- [x] Phase 1: Distributed Event-Driven Core & Transactional Outbox Pattern
  - [x] Set up multi-partition Kafka topics (`order-events`, `order-retry-5m`, `order-dlq`) in KRaft mode
  - [x] Implement Transactional Outbox Pattern with `outbox_events` table in PostgreSQL
  - [x] Build atomic SAGA Two-Phase Order State Machine (`PENDING_CANCELLATION` + Outbox Event in one ACID transaction)
  - [x] Build background Outbox Poller Engine in Go (`publisher.go`) with `acks=all`, Snappy compression, and transactional state marking
  - [x] Implement Go Inventory Service with idempotent consumer group (`inventory-service-group`) & deduplication store (`processed_events`)
  - [x] Implement Python Notification Service with consumer group (`notification-service-group`), manual offset commits, and Snappy decompression support
  - [x] Refactor domain constants across Order, Inventory, Notification, and AI services

- [x] Phase 2: Advanced Hierarchical Hybrid Retrieval Engine
  - [x] Design Hierarchical Schema in PostgreSQL: `parent_documents` and `knowledge_base_chunks`
  - [x] Implement Sentence/Paragraph boundary Semantic Chunking with contextual token overlap
  - [x] Build dual indexing: HNSW vector index (`vector_cosine_ops`) + GIN inverted index on generated `tsvector`
  - [x] Implement Reciprocal Rank Fusion (RRF) SQL CTE ($k=60$) blending dense vector ranks and sparse BM25 ranks
  - [x] Implement Cross-Encoder Re-Ranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`) on Apple Silicon Metal/MPS (~16–19ms latency)
  - [x] Implement Parent-Child context expansion (returning deduplicated full parent documents to eliminate hallucinations)
  - [x] Seed and verify enterprise knowledge base policies (VIP Loyalty, Standard Cancellation, Hardware Warranty, High-Value Guardrails)

- [x] Phase 3: Multi-Agent Supervisor Router & Tiered Memory Subsystem
  - [x] Implement Tiered Memory: Short-Term Checkpointing (`checkpoints` table) + Long-Term Episodic Memory (`user_memories` table with HNSW vector + recency retrieval)
  - [x] Build Segregated Specialist Agent Subgraphs:
    - [x] `OrderSpecialist`: Scoped to order lookups, verification, and cancellations
    - [x] `PolicySpecialist`: Scoped to authoritative hierarchical RAG search
    - [x] `EscalationSpecialist`: Scoped to dispute resolution and supervisor desk handoff
    - [x] `DirectResponse`: Zero-tool fastpath for conversational greetings (reduced latency from 13s to 3.5s)
  - [x] Build Master Supervisor Router Node with deterministic intent classification
  - [x] Implement Human-in-the-Loop (HITL) interrupt on high-stakes `cancel_order` mutations

- [x] Phase 4: Dual-LLM Guardrails & Automated RAG Triad Evaluations
  - [x] Implement Tier 1 Heuristic Regex Guardrail (<5ms) for credential extraction, prompt injection, and PII redacting (Credit Cards, SSNs, Passwords, JWTs, API Keys)
  - [x] Implement Tier 2 Model-Based Semantic Guardrail for adversarial persona manipulation and jailbreak detection
  - [x] Implement Tier 3 Data Loss Prevention (DLP) Output Sanitizer (DB URIs, file system paths, stack traces)
  - [x] Build automated RAG Triad evaluation pipeline (`Context Relevance`, `Groundedness/Faithfulness`, `Answer Relevance`) with LLM-as-a-Judge
  - [x] Verify automated RAG Triad benchmark suite (all test cases passed with composite scores >= 0.73–0.83)
  - [x] Conduct Apple Silicon M4 unified memory audit (<6.8 GB total system RAM usage across all services and local LLMs)

