# Enterprise Omnichannel AI Support Hub - Implementation Plan

This document outlines the phased approach to building our massive, production-ready distributed system from scratch in the current workspace. This plan is designed for an SDE3/Tech Lead to progressively implement and master each component of the architecture.

## User Review Required

> [!IMPORTANT]
> Please review the updated phased approach below. We moved the Protocol Buffer creation into Phase 2 based on your suggestion, making Phase 1 strictly focused on base infrastructure.

---

## 🏗️ Phase 1: Foundation & Infrastructure Setup
*Goal: Scaffold the monorepo structure in the current workspace and set up our local development environment.*

### Steps:
1. **Initialize Monorepo:** Reorganize the current directory into a monorepo structure (e.g., `api-gateway`, `services/user`, `services/order`, `services/ai`, `proto-schemas`, `infra`, `frontend-app`).
2. **Docker Compose Stack:** Create a `docker-compose.yml` to spin up:
   - PostgreSQL (with `pgvector` extension)
   - Redis (for semantic caching)
   - Kafka (using **KRaft mode**, Zookeeper-less)
3. **Validation:** Ensure all infrastructure containers spin up correctly and can be connected to locally.

---

## 🚀 Phase 2: Go Microservices & API Gateway
*Goal: Build the core business logic and routing layers in Go, establishing gRPC communication.*

### Steps:
1. **Define Proto Schemas:** Initialize the shared `proto-schemas` directory, set up `protoc` generation tooling, and write the first `.proto` definitions for the User and Order services.
2. **User Service (Go):** Set up Go project, configure PostgreSQL connection (ORM), and implement basic user management gRPC endpoints using the generated protobuf code.
3. **Order Service (Go):** Set up Go project, configure PostgreSQL connection, and implement basic order management gRPC endpoints.
4. **API Gateway (Go):** 
   - Set up Go Fiber/Gin or standard net/http.
   - Implement routing to backend services via gRPC clients.
   - Add initial JWT Authentication middleware.
5. **Validation:** Test REST API calls to the Gateway which internally communicate with User/Order services via gRPC.

---

## 📨 Phase 3: Event-Driven Architecture (Kafka)
*Goal: Decouple services using asynchronous event streaming.*

### Steps:
1. **Kafka Producers (Go):** Implement Kafka producer logic in the Order/User services (e.g., emitting an `OrderCreated` or `RefundRequested` event).
2. **Kafka Consumers (Go):** Implement consumer logic (e.g., User service listening for order events to update user stats, or a mock notification service).
3. **Validation:** Trigger an action via API Gateway and verify events are published and consumed asynchronously.

---

## 🧠 Phase 4: AI Service Foundation & Memory
*Goal: Introduce the Python AI microservice, connect data stores, and implement persistent memory.*

### Steps:
1. **FastAPI Setup:** Initialize the Python service in `services/ai`.
2. **LangGraph Setup:** Create a basic LangGraph supervisor agent framework.
3. **Persistent Memory:** Implement a Postgres checkpointer for LangGraph to maintain conversation history (short-term and long-term memory) across sessions.
4. **Advanced RAG (pgvector):** Connect the AI service to PostgreSQL, set up embedding generation, and implement hybrid search capabilities.
5. **Validation:** Successfully route a basic query through FastAPI, retrieve documents via pgvector, and verify the AI remembers previous turns in the conversation.

---

## 🔌 Phase 5: Model Context Protocol (MCP) Integration
*Goal: Enable the AI service to securely call tools on our Go microservices.*

### Steps:
1. **Go Services as MCP Servers:** Instrument the User and Order services to expose their capabilities via standard MCP tool schemas.
2. **Python AI as MCP Client:** Configure LangGraph sub-agents to dynamically discover and execute tools on the Go services via MCP.
3. **Validation:** Ask the AI service a question like "What is the status of order #123?" and watch it securely fetch the data from the Go Order service via MCP.

---

## ⚡ Phase 6: Performance & Real-Time Streaming
*Goal: Optimize the AI experience for production-grade responsiveness.*

### Steps:
1. **Semantic Caching (Redis):** Implement caching in the AI service using Redis. If a user asks a semantically identical question, return the cached answer to bypass LLM latency.
2. **SSE Streaming:** Implement real-time token streaming from LangGraph (Python) -> gRPC Stream -> API Gateway (Go) -> Frontend Client (Server-Sent Events).
3. **Validation:** Observe real-time typewriter-effect streaming in the API response and verify cache hits on repeated queries.

---

## 🤝 Phase 7: Advanced AI: Human-in-the-Loop & Guardrails
*Goal: Make the AI system safe and capable of escalating complex issues.*

### Steps:
1. **Human-in-the-Loop (HITL):** Add interrupt breakpoints in LangGraph to pause the agent before executing sensitive actions (e.g., issuing a refund) and wait for human approval.
2. **Guardrails:** Implement safety checks to prevent toxic output or PII leakage.
3. **Validation:** Trigger a refund request and verify the graph pauses until manual intervention via an API call is made.

---

## 🌐 Phase 8: Frontend Chatbot Application
*Goal: Build the user interface that interacts with our Enterprise API Gateway.*

### Steps:
1. **Frontend Setup:** Initialize a Next.js (React) or Vite frontend app in the monorepo.
2. **Authentication UI:** Build Login/Signup pages connecting to the Go Gateway to retrieve JWTs.
3. **Chat Interface:** Build a chat UI that connects to the Gateway's SSE endpoint to render real-time streaming tokens and rich UI components.
4. **Validation:** Log in as a user, ask a question, and watch the streaming response appear in real-time.

---

## 🛡️ Phase 9: Observability & Automated Evals
*Goal: Ensure the system is monitorable and AI outputs are measurable.*

### Steps:
1. **Distributed Tracing:** Integrate OpenTelemetry across all Go and Python services to trace requests from Gateway to AI to Database.
2. **LangSmith Integration:** Connect LangGraph to LangSmith for deep visibility into agent steps and LLM interactions.
3. **Automated Evals (Ragas):** Set up an evaluation script to score RAG retrieval accuracy and answer quality on a sample dataset.

## Verification Plan
For each phase, we will manually verify functionality before proceeding to the next. No phase will be considered complete until its respective infrastructure, communication, and core logic are proven to work locally via our Docker Compose setup.
