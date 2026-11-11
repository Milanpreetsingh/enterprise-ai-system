# Enterprise Omnichannel AI Support Hub - Learning Guide

This document maps out what you will learn, master, and experience at each step of implementing the [implementation_plan.md](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/docs/implementation_plan.md). It is structured to help you track not just *what* code to write, but the *engineering philosophy*, *architectural patterns*, and *technical competencies* you are acquiring along the journey.

---

## 🏗️ Phase 1: Foundation & Infrastructure Setup
*Goal: Scaffold the monorepo structure and establish a robust local development environment.*

| Step | Technical Focus | Core Learning Takeaways |
| :--- | :--- | :--- |
| **1. Initialize Monorepo** | Monorepo Architecture | <ul><li>**Monorepo Strategy:** Master how to organize multiple languages (Go, Python, TypeScript) in a single repository.</li><li>**Dependency Isolation:** Learn to isolate dependencies across service boundaries using Go Workspaces (`go.work`), npm workspaces, and Python virtual environment management.</li><li>**Shared Tooling:** Understand path resolution, build caching, and common script structures inside a monorepo setup.</li></ul> |
| **2. Docker Compose Stack** | Infrastructure as Code | <ul><li>**Advanced Docker Compose:** Master container networking, dependency ordering (`depends_on` with health checks), volume mounts, and custom environment injection.</li><li>**KRaft Mode Kafka:** Run Kafka without Zookeeper. Learn how KRaft coordinates metadata, processes controller roles, and manages cluster consensus directly within Kafka.</li><li>**pgvector & Semantic Stores:** Learn how database extensions work in Docker and configure Redis to serve as a low-latency cache.</li></ul> |
| **3. Validation** | Diagnostics & Diagnostics | <ul><li>**Networking Diagnostics:** Learn how to troubleshoot container-to-container communication issues, resolve port conflicts, and check service-readiness programmatically.</li></ul> |

---

## 🚀 Phase 2: Go Microservices & API Gateway
*Goal: Build the core business logic, database integration, and high-performance gRPC communication.*

| Step | Technical Focus | Core Learning Takeaways |
| :--- | :--- | :--- |
| **1. Define Proto Schemas** | Schema-First Development | <ul><li>**Protocol Buffers (Proto3):** Master writing clean, backward-compatible API schemas. Learn the rules of field tags, deprecations, and package namespacing.</li><li>**Codegen Pipelines:** Build automated compilation tasks using `protoc` or `buf` to generate Go and Python client/server stubs.</li></ul> |
| **2. User Service (Go)** | Clean Architecture in Go | <ul><li>**Go gRPC Implementation:** Implement a high-performance gRPC server, mapping generated stubs to domain handlers.</li><li>**Database Connection Lifecycle:** Master connection pooling (`pgx`), transactional operations, and migrations using ORMs or raw SQL.</li><li>**Go Concurrency & Patterns:** Write idiomatic, highly concurrent Go code using context propagation, goroutines, and robust error-handling patterns.</li></ul> |
| **3. Order Service (Go)** | Distributed Data Boundaries | <ul><li>**Database per Service:** Understand why microservices must own their databases to prevent tight coupling and schema contamination.</li><li>**State Management:** Learn how to model order lifecycles and enforce state transitions safely under concurrent requests.</li></ul> |
| **4. API Gateway (Go)** | API Gateway Pattern | <ul><li>**Reverse Proxying:** Route HTTP REST traffic to downstream gRPC services via client pools and multiplexed connections.</li><li>**Middleware Architecture:** Write lightweight middleware in Go (using Fiber/Gin) to intercept, validate, and extract claims from JWTs.</li><li>**gRPC Metadata Context:** Propagate security context (e.g., authenticated UserID) down to gRPC services using gRPC Metadata.</li></ul> |
| **5. Validation** | Microservices Integration | <ul><li>**HTTP-to-gRPC Mapping:** Learn to translate HTTP verbs/status codes to gRPC status codes (e.g., mapping gRPC `Unauthenticated` to HTTP `401 Unauthorized`).</li></ul> |

---

## 📨 Phase 3: Event-Driven Architecture (Kafka)
*Goal: Decouple system logic through asynchronous event streaming.*

| Step | Technical Focus | Core Learning Takeaways |
| :--- | :--- | :--- |
| **1. Kafka Producers (Go)** | Event Sourcing & Publishing | <ul><li>**Producer Guarantees:** Configure `acks=all`, retry counts, and idempotent producers to ensure zero message loss.</li><li>**Message Ordering:** Learn how Kafka partitions messages using keys (e.g., partitioning by `OrderID` to guarantee order of state changes).</li><li>**Non-Blocking Concurrency:** Implement thread-safe producer pipelines in Go using channels.</li></ul> |
| **2. Kafka Consumers (Go)** | Stream Processing | <ul><li>**Consumer Groups:** Learn how Kafka scales message consumption by distributing partitions among instances in a consumer group.</li><li>**Offset Commit Strategies:** Understand the trade-offs of auto-commit vs. manual commit to guarantee *at-least-once* delivery.</li><li>**Idempotent Consumers:** Write consumer code that handles duplicate event processing safely without side effects.</li></ul> |
| **3. Validation** | Fault Tolerance | <ul><li>**Resilience Testing:** Learn to simulate consumer failures, debug consumer lag, and verify partition rebalancing.</li></ul> |

---

## 🧠 Phase 4: AI Service Foundation & Memory
*Goal: Introduce the Python AI microservice, build agentic graph flows, and manage LLM memory.*

| Step | Technical Focus | Core Learning Takeaways |
| :--- | :--- | :--- |
| **1. FastAPI Setup** | Asynchronous Python | <ul><li>**ASGI Lifecycle:** Master asynchronous request processing in Python using FastAPI.</li><li>**Pydantic Data Validation:** Use type hinting and Pydantic models to parse incoming JSON payloads with strict validation.</li></ul> |
| **2. LangGraph Setup** | Agentic Orchestration | <ul><li>**Stateful Agent Graphs:** Learn how to model LLM execution flows as cyclical graphs (nodes as actions, edges as control decisions).</li><li>**Supervisor Agent Pattern:** Design a routing system where a central coordinator delegates tasks to specialized sub-agents.</li></ul> |
| **3. Persistent Memory** | State Persistence | <ul><li>**LangGraph Checkpointers:** Master persisting agent state dynamically using PostgreSQL to maintain seamless short-term and long-term conversation memory.</li><li>**Session Hydration:** Retrieve and restore conversational state instantly across multiple network sessions.</li></ul> |
| **4. Advanced RAG (pgvector)** | Vector Databases & Retrieval | <ul><li>**Dense Embeddings:** Learn to chunk texts, generate vector embeddings, and save them.</li><li>**pgvector indexing:** Master the differences between `HNSW` and `IVFFlat` indexes, and use cosine/L2 distance calculations.</li><li>**Hybrid Search:** Combine traditional text indexes (lexical search) with semantic vector search for state-of-the-art context retrieval.</li></ul> |
| **5. Validation** | Retrieval Evaluation | <ul><li>**RAG Diagnostics:** Inspect retrieved documents for relevance, verify memory recall, and analyze context-window usage.</li></ul> |

---

## 🔌 Phase 5: Model Context Protocol (MCP) Integration
*Goal: Enable the LLM service to dynamically discover and securely call internal microservice APIs.*

| Step | Technical Focus | Core Learning Takeaways |
| :--- | :--- | :--- |
| **1. Go Services as MCP Servers** | Extensible Tooling APIs | <ul><li>**MCP Specification:** Implement Anthropic's Model Context Protocol to format Go gRPC schemas into standardized tool metadata.</li><li>**Secure Encapsulation:** Expose system capability parameters without giving agents raw access to database engines or file systems.</li></ul> |
| **2. Python AI as MCP Client** | Dynamic Capabilities | <ul><li>**Dynamic Tool Loading:** Build a client in Python that queries the MCP servers, auto-detecting available tools.</li><li>**Tool Execution loops:** Enable the LLM agent to intelligently determine *when* and *how* to call these microservice tools based on user inputs.</li></ul> |
| **3. Validation** | Agentic Tool Calling | <ul><li>**Tool Call Tracing:** Debug communication hops (Agent -> MCP Client -> MCP Server -> gRPC Server) and handle schema mismatches.</li></ul> |

---

## ⚡ Phase 6: Performance & Real-Time Streaming
*Goal: Address LLM latency using semantic caching and push real-time updates via streaming.*

| Step | Technical Focus | Core Learning Takeaways |
| :--- | :--- | :--- |
| **1. Semantic Caching (Redis)** | High-Performance Caching | <ul><li>**Semantic Similarity Search:** Store embeddings of user queries in Redis and perform vector similarity queries.</li><li>**Distance Thresholds:** Learn how to balance cache hit-rates against response accuracy by tuning cosine distance thresholds.</li></ul> |
| **2. SSE Streaming** | Reactive Data Pipelines | <ul><li>**Server-Sent Events (SSE):** Build a token streaming pipeline from Python (yield generators) -> gRPC streaming -> Go API Gateway -> Frontend clients.</li><li>**Connection Lifecycle Management:** Handle sudden client disconnections gracefully in streaming contexts without leaking resources.</li></ul> |
| **3. Validation** | Performance Profiling | <ul><li>**Latency Benchmarking:** Measure the latency difference between cache hits (<15ms) and LLM execution (~2000ms), and audit Time-To-First-Token (TTFT).</li></ul> |

---

## 🤝 Phase 7: Advanced AI: Human-in-the-Loop & Guardrails
*Goal: Add manual approvals for sensitive operations and configure safety constraints.*

| Step | Technical Focus | Core Learning Takeaways |
| :--- | :--- | :--- |
| **1. Human-in-the-Loop (HITL)** | Interrupted Workflows | <ul><li>**State Machine Breakpoints:** Interrupt the execution of an agent graph before a destructive action (e.g., executing refunds).</li><li>**Approval Verification:** Store state, accept external authorization payloads, and resume the graph execution with updated contexts.</li></ul> |
| **2. Guardrails** | AI Safety & Integrity | <ul><li>**Input & Output Moderation:** Set up classifiers (such as Llama Guard) to filter out toxic, irrelevant, or malicious requests.</li><li>**PII Sanitization:** Automatically detect and scrub sensitive user info (credit cards, social security numbers) from prompt contexts.</li></ul> |
| **3. Validation** | Edge-Case Diagnostics | <ul><li>**Evasion Testing:** Try to bypass the system via prompt injection and check if boundaries hold. Confirm graph execution resumes correctly after human inputs.</li></ul> |

---

## 🌐 Phase 8: Frontend Chatbot Application
*Goal: Design the frontend interface to provide a responsive, real-time user experience.*

| Step | Technical Focus | Core Learning Takeaways |
| :--- | :--- | :--- |
| **1. Frontend Setup** | Next.js Architecture | <ul><li>**Modern React Structure:** Build responsive page routing and clean layout templates in Next.js/Vite.</li><li>**CSS Design Systems:** Build visual tokens, standard theme variables, and flexbox/grid layouts without relying on heavy utility wrappers.</li></ul> |
| **2. Authentication UI** | Identity Integration | <ul><li>**Secure Session Management:** Store JWTs securely (HttpOnly cookies vs memory) and refresh expired user sessions.</li><li>**Route Protection:** Block unauthorized access to specific dashboard pages using React Hooks or middleware.</li></ul> |
| **3. Chat Interface** | UX Streaming & Rich UI | <ul><li>**SSE client consumption:** Parse text streams in real-time, handling incomplete markdown tokens.</li><li>**Rich UI Rendering:** Render interactive widgets (like clickable order status tracking or item lists) embedded inside chat bubbles.</li></ul> |
| **4. Validation** | Web Vitals Auditing | <ul><li>**Response UX Audits:** Measure layout shifts (CLS), first input delays, and connection recovery behaviors during network drops.</li></ul> |

---

## 🛡️ Phase 9: Observability & Automated Evals
*Goal: Monitor distributed architectures and evaluate LLM responses in production.*

| Step | Technical Focus | Core Learning Takeaways |
| :--- | :--- | :--- |
| **1. Distributed Tracing** | OpenTelemetry Integration | <ul><li>**Distributed Context Propagation:** Trace requests across network boundaries. Correlate Gateway calls to gRPC calls to Python AI outputs using matching TraceIDs.</li><li>**Tracing Backends:** Export trace data to systems like Jaeger to isolate database or LLM performance bottlenecks.</li></ul> |
| **2. LangSmith Integration** | LLM Tracing & Debugging | <ul><li>**Prompt Execution Visualizers:** Trace intermediate agent steps, variable inputs, system prompts, and costs in real-time.</li><li>**Dataset Curation:** Build test suites from production conversations to evaluate agent behavioral updates.</li></ul> |
| **3. Automated Evals (Ragas)** | AI Output Quantification | <ul><li>**Metric-Driven Evals:** Run batch test evaluations checking Retrieval Precision, Retrieval Recall, Answer Relevance, and Faithfulness.</li><li>**CI Eval Integration:** Learn to block prompt regressions before code changes get deployed.</li></ul> |

---

## 💡 Core SDE3 Architectural Insights You Will Master

1. **System Topology & Communication:** You will learn when to choose **gRPC** (for low-latency synchronous microservice calls), **Kafka** (for reliable asynchronous event distribution), and **HTTP/SSE** (for real-time streaming interfaces client-side).
2. **Deterministic Agent Frameworks:** Move away from unpredictable "zero-constraint" prompt loops. Master structured routing graphs using **LangGraph** where AI behavior is predictable, testable, and subject to human oversight.
3. **Database Specialization:** Learn how to leverage single-database engines (like PostgreSQL) for hybrid tasks (relational storage, vectors via `pgvector`, and graph checkpointer histories) before introducing multiple complex database platforms.
4. **Context Propagation & Security:** Understand trace propagation (OpenTelemetry) and credentials authorization (JWT) as distributed variables that flow cleanly across multi-language microservice boundaries.
