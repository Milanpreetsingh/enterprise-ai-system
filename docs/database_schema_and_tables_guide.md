# Enterprise Database Architecture & Comprehensive Tables Guide

This document serves as the authoritative, code-level reference for all database tables across the **Enterprise Multi-Agent AI System**. It details each table's architectural owner, schema definition, migration mechanics, business purpose, insertion lifecycle, and query patterns.

---

<a id="document-navigation"></a>
## 📌 Table of Contents

- [🏛️ Global Database Architecture & Ownership Matrix](#global-database-architecture)
- [1. Core Domain Tables (Golang Microservices & GORM)](#core-domain-tables)
  - [1.1 `users` Table (User Service)](#table-users)
  - [1.2 `orders` Table (Order Service)](#table-orders)
  - [1.3 `inventory` Table (Inventory Service)](#table-inventory)
- [2. Event-Driven & SAGA Outbox Tables (Asynchronous Messaging)](#event-driven-tables)
  - [2.1 `outbox_events` Table (Order Service Transactional Outbox)](#table-outbox-events)
  - [2.2 `processed_events` Table (Idempotency Store: Inventory & Notification)](#table-processed-events)
- [3. AI Subsystem & State Persistence Tables (Python AI Service)](#ai-subsystem-tables)
  - [3.1 `checkpoints` Table (Short-Term Conversational State & HITL)](#table-checkpoints)
  - [3.2 `user_memories` Table (Long-Term Episodic Memory & Customer Profiles)](#table-user-memories)
  - [3.3 `knowledge_base` Table (Legacy Phase 1 Naive RAG)](#table-knowledge-base)
  - [3.4 `parent_documents` Table (Phase 2 Hierarchical Macro-Context)](#table-parent-documents)
  - [3.5 `knowledge_base_chunks` Table (Phase 2 Micro-Index for Hybrid RRF)](#table-knowledge-base-chunks)
- [🎯 In-Depth Architectural Q&A](#architectural-qa)
  - [Q1: Why do we have both `knowledge_base` and `knowledge_base_chunks`?](#qa-kb-vs-chunks)
  - [Q2: `knowledge_base_chunks` vs `parent_documents`: Why separate them if they relate to the same text?](#qa-chunks-vs-parents)
  - [Q3: When is data inserted into `user_memories`, and why have `memory_type` when queries filter by `user_id`?](#qa-user-memories)

---

<a id="global-database-architecture"></a>
## 🏛️ Global Database Architecture & Ownership Matrix

The enterprise architecture uses a single shared PostgreSQL cluster (`postgres:5432`) operating with multi-service schema isolation, combining **GORM Auto-Migrations** for Golang domain services with **Raw SQL DDL & pgvector HNSW indexing** for the Python AI service.

| Table Name | Owning Service | Schema Location | Migration Mechanism | Primary Key | Key Storage Engine |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`users`** | Go User Service | [`services/user/internal/repository/user_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/user/internal/repository/user_repository.go#L16) | GORM `AutoMigrate` | `id` (UUID) | Relational B-Tree |
| **`orders`** | Go Order Service | [`services/order/internal/repository/postgres_order_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/order/internal/repository/postgres_order_repository.go#L14) | GORM `AutoMigrate` | `id` (UUID) | Relational B-Tree |
| **`inventory`** | Go Inventory Service | [`services/inventory/internal/repository/postgres_inventory_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/inventory/internal/repository/postgres_inventory_repository.go#L14) | GORM `AutoMigrate` | `product_id` (UUID) | Relational B-Tree |
| **`outbox_events`** | Go Order Service | [`services/order/internal/repository/postgres_order_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/order/internal/repository/postgres_order_repository.go#L24) | GORM `AutoMigrate` | `id` (UUID) | Poller Queue B-Tree |
| **`processed_events`** | Go Inventory & Python Notification | [`services/inventory/internal/repository/postgres_inventory_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/inventory/internal/repository/postgres_inventory_repository.go#L22) | GORM `AutoMigrate` | `(event_id, consumer_group)` | Idempotency Index |
| **`checkpoints`** | Python AI Service | [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L43) | SQL DDL `init_db()` | `(thread_id, checkpoint_id)` | Bytea Pickle Blobs |
| **`user_memories`** | Python AI Service | [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L55) | SQL DDL `init_db()` | `id` (UUID) | pgvector HNSW Cosine |
| **`knowledge_base`** | Python AI Service | [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L29) | SQL DDL `init_db()` | `id` (UUID) | pgvector HNSW Cosine (Legacy) |
| **`parent_documents`** | Python AI Service | [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L76) | SQL DDL `init_db()` | `id` (UUID) | Text Storage (Un-indexed) |
| **`knowledge_base_chunks`** | Python AI Service | [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L88) | SQL DDL `init_db()` | `id` (UUID) | HNSW Cosine + GIN `tsvector` |

---

<a id="core-domain-tables"></a>
## 1. Core Domain Tables (Golang Microservices & GORM)

<a id="table-users"></a>
### 1.1 `users` Table (User Service)
* **Owning Service:** User Service (`services/user`, gRPC `:50051`).
* **Schema Definition:** [`services/user/internal/repository/user_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/user/internal/repository/user_repository.go#L16-L25).
* **Creation Mechanism:** Auto-created on startup in [`services/user/cmd/server/main.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/user/cmd/server/main.go#L52) via:
  ```go
  db.AutoMigrate(&repository.User{})
  ```
* **DDL Representation:**
  ```sql
  CREATE TABLE users (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      email TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL,
      full_name TEXT NOT NULL,
      order_count BIGINT DEFAULT 0,
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
  ```
* **Purpose:** Stores core user authentication credentials, customer profile details, and running purchase counters.
* **Insertion Lifecycle:** Inserted when a customer registers via Go API Gateway (`POST /api/v1/auth/register`) or seeded by test suites.
* **Query Patterns:** Looked up by `id` during JWT validation and order creation, and updated atomically when `order_count` increments.

---

<a id="table-orders"></a>
### 1.2 `orders` Table (Order Service)
* **Owning Service:** Order Service (`services/order`, gRPC `:50052`).
* **Schema Definition:** [`services/order/internal/repository/postgres_order_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/order/internal/repository/postgres_order_repository.go#L14-L22).
* **Creation Mechanism:** Auto-created on startup in [`services/order/cmd/server/main.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/order/cmd/server/main.go#L55) via:
  ```go
  db.AutoMigrate(&repository.Order{}, &repository.OutboxEvent{})
  ```
* **DDL Representation:**
  ```sql
  CREATE TABLE orders (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL,
      product_id UUID NOT NULL,
      quantity INT NOT NULL,
      status TEXT NOT NULL, -- "PENDING", "PENDING_CANCELLATION", "CANCELLED", "COMPLETED"
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
  ```
* **Purpose:** Serves as the source of truth for purchase lifecycle states, quantities, and customer ownership.
* **Insertion Lifecycle:** Inserted when a customer checks out (`POST /api/v1/orders`).
* **Two-Phase SAGA Mutation:** When an AI agent or user initiates cancellation, the service locks the row via `SELECT * FROM orders WHERE id = $1 FOR UPDATE` and transitions `status` to `'PENDING_CANCELLATION'`.

---

<a id="table-inventory"></a>
### 1.3 `inventory` Table (Inventory Service)
* **Owning Service:** Inventory Service (`services/inventory`, gRPC `:50054`).
* **Schema Definition:** [`services/inventory/internal/repository/postgres_inventory_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/inventory/internal/repository/postgres_inventory_repository.go#L14-L20).
* **Creation Mechanism:** Auto-created on startup in [`services/inventory/cmd/server/main.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/inventory/cmd/server/main.go#L46) via:
  ```go
  db.AutoMigrate(&repository.Inventory{}, &repository.ProcessedEvent{})
  ```
* **DDL Representation:**
  ```sql
  CREATE TABLE inventory (
      product_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      product_name VARCHAR(255) NOT NULL,
      stock_quantity INT NOT NULL DEFAULT 0,
      reserved_quantity INT NOT NULL DEFAULT 0,
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
  ```
* **Purpose:** Manages available and reserved physical warehouse stock for every SKU.
* **Insertion Lifecycle:** Initialized by catalog onboarding scripts.
* **Compensating Mutation:** When the Go Inventory Kafka consumer processes an `ORDER_CANCELLED` event, it executes:
  ```sql
  UPDATE inventory 
  SET stock_quantity = stock_quantity + $1, updated_at = NOW() 
  WHERE product_id = $2;
  ```

---

<a id="event-driven-tables"></a>
## 2. Event-Driven & SAGA Outbox Tables (Asynchronous Messaging)

<a id="table-outbox-events"></a>
### 2.1 `outbox_events` Table (Order Service Transactional Outbox)
* **Owning Service:** Order Service (`services/order`).
* **Schema Definition:** [`services/order/internal/repository/postgres_order_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/order/internal/repository/postgres_order_repository.go#L24-L35).
* **Creation Mechanism:** Auto-created in [`services/order/cmd/server/main.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/order/cmd/server/main.go#L55).
* **DDL Representation:**
  ```sql
  CREATE TABLE outbox_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      aggregate_type VARCHAR(64) NOT NULL, -- e.g. "ORDER"
      aggregate_id VARCHAR(64) NOT NULL,   -- e.g. Order ID
      event_type VARCHAR(64) NOT NULL,       -- e.g. "ORDER_CANCELLED"
      payload JSONB NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'PENDING', -- "PENDING", "PUBLISHED", "FAILED"
      retry_count INT NOT NULL DEFAULT 0,
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      published_at TIMESTAMP WITH TIME ZONE
  );
  CREATE INDEX idx_outbox_status_created ON outbox_events(status, created_at);
  ```
* **Purpose:** Implements the **Transactional Outbox Pattern**. Guarantees that the database update (`PENDING_CANCELLATION`) and event emission occur in a single, atomic ACID transaction—eliminating the dual-write hazard.
* **Insertion Lifecycle:** Inserted inside `RequestCancellationTx`:
  ```go
  tx.Create(&OutboxEvent{
      ID: uuid.New().String(), AggregateType: "ORDER", AggregateID: order.ID,
      EventType: "ORDER_CANCELLED", Payload: payload, Status: "PENDING",
  })
  ```
* **Poller Query & Update:** The background Goroutine in [`services/order/internal/publisher/publisher.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/order/internal/publisher/publisher.go) polls:
  ```sql
  SELECT * FROM outbox_events WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT 50 FOR UPDATE;
  ```
  Once Kafka acknowledges receipt (`acks=all`), updates `status = 'PUBLISHED', published_at = NOW()`.

---

<a id="table-processed-events"></a>
### 2.2 `processed_events` Table (Idempotency Store)
* **Owning Services:** Shared between Go Inventory Service and Python Notification Service.
* **Schema Definition:** [`services/inventory/internal/repository/postgres_inventory_repository.go`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/inventory/internal/repository/postgres_inventory_repository.go#L22-L26) and [`services/notification/main.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/notification/main.py#L33-L41).
* **DDL Representation:**
  ```sql
  CREATE TABLE processed_events (
      event_id VARCHAR(255) NOT NULL,
      consumer_group VARCHAR(255) NOT NULL,
      processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      PRIMARY KEY (event_id, consumer_group)
  );
  ```
* **Purpose:** Provides **Exactly-Once Semantics (EOS)** at the consumer boundary. Because Kafka delivers messages with "at-least-once" guarantees, network reconnects could cause re-delivery. This table prevents double-restocking inventory or duplicate email dispatches.
* **Consumer Check & Insert:**
  ```python
  # Notification Service (Python)
  SELECT 1 FROM processed_events WHERE event_id = %s AND consumer_group = %s;
  -- If not present, execute email dispatch, then:
  INSERT INTO processed_events (event_id, consumer_group, processed_at) VALUES (%s, %s, NOW());
  ```

---

<a id="ai-subsystem-tables"></a>
## 3. AI Subsystem & State Persistence Tables (Python AI Service)

<a id="table-checkpoints"></a>
### 3.1 `checkpoints` Table (Short-Term Conversational State)
* **Owning Service:** AI Service (`services/ai`, gRPC `:50053`).
* **Schema Definition:** [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L43-L51).
* **Creation Mechanism:** Initialized via `init_db()` in [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py).
* **DDL Representation:**
  ```sql
  CREATE TABLE checkpoints (
      thread_id VARCHAR(255) NOT NULL,
      checkpoint_id VARCHAR(255) NOT NULL,
      parent_id VARCHAR(255),
      checkpoint BYTEA NOT NULL,
      metadata BYTEA,
      PRIMARY KEY (thread_id, checkpoint_id)
  );
  CREATE INDEX idx_checkpoints_thread ON checkpoints(thread_id);
  ```
* **Purpose:** Provides durable state snapshots for the LangGraph multi-agent workflow. Enables:
  1. Multi-turn chat memory across stateless server restarts.
  2. Human-in-the-Loop (HITL) pause and resume (`interrupt_before=["sensitive_tools"]`).
  3. Merkle DAG time-travel auditing.
* **Insertion Lifecycle:** Managed by `PostgresCheckpointSaver.put()` in [`services/ai/app/db/checkpointer.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/checkpointer.py#L70-L100). At each graph node transition, the serialized binary `pickle` frame is saved with `parent_id` linking to the preceding turn.

---

<a id="table-user-memories"></a>
### 3.2 `user_memories` Table (Long-Term Episodic Memory)
* **Owning Service:** AI Service (`services/ai`).
* **Schema Definition:** [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L55-L74).
* **DDL Representation:**
  ```sql
  CREATE TABLE user_memories (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id VARCHAR(64) NOT NULL,
      memory_type VARCHAR(32) NOT NULL DEFAULT 'FACT', -- "TIER_STATUS", "PREFERENCE", "INCIDENT"
      content TEXT NOT NULL,
      metadata JSONB DEFAULT '{}'::jsonb,
      embedding VECTOR(1536),
      confidence FLOAT DEFAULT 1.0,
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
  CREATE INDEX idx_user_memories_user_id ON user_memories(user_id);
  CREATE INDEX idx_user_memories_embedding ON user_memories USING hnsw (embedding vector_cosine_ops);
  ```
* **Purpose:** Stores cross-session, long-term customer facts, preferences, loyalty tiers, and past dispute notes. Unlike `checkpoints` (which are scoped to a single conversation `thread_id`), `user_memories` follow the user across all sessions and years.
* **Insertion Lifecycle:** Seeded via [`services/ai/scripts/seed_user_memories.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/scripts/seed_user_memories.py) or saved dynamically using `store_user_memory()` in [`services/ai/app/db/memory_store.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/memory_store.py).
* **Retrieval Query:** Filtered by `user_id` and ranked via cosine distance:
  ```sql
  SELECT id, memory_type, content, 1 - (embedding <=> $1::vector) AS similarity
  FROM user_memories 
  WHERE user_id = $2
  ORDER BY embedding <=> $1::vector ASC 
  LIMIT 3;
  ```

---

<a id="table-knowledge-base"></a>
### 3.3 `knowledge_base` Table (Legacy Phase 1 Naive RAG)
* **Owning Service:** AI Service (`services/ai`).
* **Schema Definition:** [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L29-L39).
* **DDL Representation:**
  ```sql
  CREATE TABLE knowledge_base (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      content TEXT NOT NULL,
      embedding VECTOR(1536) NOT NULL,
      metadata JSONB
  );
  CREATE INDEX kb_embedding_idx ON knowledge_base USING hnsw (embedding vector_cosine_ops);
  ```
* **Purpose:** Phase 1 flat RAG storage. Used in [`services/ai/app/db/rag.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/rag.py). Stores entire policy documents as single monolithic text blobs.

---

<a id="table-parent-documents"></a>
### 3.4 `parent_documents` Table (Phase 2 Hierarchical Macro-Context)
* **Owning Service:** AI Service (`services/ai`).
* **Schema Definition:** [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L76-L86).
* **DDL Representation:**
  ```sql
  CREATE TABLE parent_documents (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      title VARCHAR(255) NOT NULL,
      full_content TEXT NOT NULL,
      category VARCHAR(64) NOT NULL, -- e.g. "cancellation_policy", "vip_policy"
      metadata JSONB DEFAULT '{}'::jsonb,
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
  ```
* **Purpose:** Stores the **full, un-fragmented, pristine policy text** (500–2,000 words). Notice that it has **no vector embedding** and **no tsvector column**. It is never searched directly; it is fetched by primary key `id` once a child chunk wins the search.

---

<a id="table-knowledge-base-chunks"></a>
### 3.5 `knowledge_base_chunks` Table (Phase 2 Micro-Index for Hybrid RRF)
* **Owning Service:** AI Service (`services/ai`).
* **Schema Definition:** [`services/ai/app/db/connection.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/connection.py#L88-L113).
* **DDL Representation:**
  ```sql
  CREATE TABLE knowledge_base_chunks (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      parent_id UUID NOT NULL REFERENCES parent_documents(id) ON DELETE CASCADE,
      chunk_content TEXT NOT NULL,
      chunk_index INT NOT NULL,
      embedding VECTOR(1536) NOT NULL,
      tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', chunk_content)) STORED,
      metadata JSONB DEFAULT '{}'::jsonb,
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
  CREATE INDEX idx_kb_chunks_parent ON knowledge_base_chunks(parent_id);
  CREATE INDEX idx_kb_chunks_embedding ON knowledge_base_chunks USING hnsw (embedding vector_cosine_ops);
  CREATE INDEX idx_kb_chunks_tsv ON knowledge_base_chunks USING gin (tsv);
  ```
* **Purpose:** The high-resolution micro-search index. Stores small, overlapping sentence chunks (~100 words). Dual-indexed with both dense HNSW cosine embeddings and sparse BM25 GIN inverted text search.
* **Insertion Lifecycle:** Inserted by `seed_hierarchical_document()` in [`services/ai/app/db/hybrid_search.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/hybrid_search.py#L51-L97).

---

<a id="architectural-qa"></a>
## 🎯 In-Depth Architectural Q&A

<a id="qa-kb-vs-chunks"></a>
### Q1: Why do we have both `knowledge_base` and `knowledge_base_chunks`?

They represent the **architectural evolution from Phase 1 to Phase 2**:

1. **`knowledge_base` (Phase 1 Naive RAG):**
   - Created initially in `services/ai/app/db/rag.py` to establish basic vector search.
   - It stores entire documents as single monolithic rows.
   - **The Problem:** Compressing an entire 800-word policy document into a single 1536-dimensional vector causes **semantic dilution**. Specific details (e.g., *"Diamond VIP members get 60 days"* or *"$500 threshold"*) get lost in the average vector.
2. **`knowledge_base_chunks` (Phase 2 Hierarchical Hybrid RAG):**
   - Introduced in the SDE-3 revamp to implement **Parent-Child Retrieval with Reciprocal Rank Fusion (RRF)**.
   - It divides documents into tightly scoped sentence chunks with a generated `tsv` column for full-text search.
   - `knowledge_base` is retained for backward compatibility with early Phase 1 integration tests, whereas `knowledge_base_chunks` powers the live production Policy Specialist.

---

<a id="qa-chunks-vs-parents"></a>
### Q2: `knowledge_base_chunks` vs. `parent_documents`: Why separate them if they relate to the same text?

They solve the foundational **RAG Trade-Off: Retrieval Precision vs. Generation Context Window (The "Lost-in-the-Middle" Problem)**.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 THE RAG PARADOX                                        │
│                                                                                        │
│  FOR RETRIEVAL (Searching):                                                            │
│  • Smaller chunks (100 words) are vastly superior.                                     │
│  • High semantic density matches user queries with pinpoint precision.                 │
│                                                                                        │
│  FOR GENERATION (LLM Answering):                                                       │
│  • Larger context (Full 1,000-word document) is essential.                             │
│  • Fragmented chunks cut off crucial qualifiers: e.g., a chunk might say "Refunds      │
│    are granted within 60 days", but the qualification "Applies ONLY to Diamond Tier"   │
│    was in the preceding paragraph! Fragmented chunks cause model hallucinations.       │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### How the Two Tables Work Together:
1. **`knowledge_base_chunks` (Micro-Index):**
   - Has dense embeddings (`embedding`) + sparse index (`tsv`).
   - The user query runs against this table via Reciprocal Rank Fusion (RRF) and Cross-Encoder re-ranking.
2. **`parent_documents` (Macro-Context):**
   - Has **NO embeddings** (saves GPU/embedding costs).
   - Once chunk #2 wins the search, the system executes:
     ```sql
     SELECT full_content FROM parent_documents WHERE id = winning_chunk.parent_id;
     ```
   - The LLM is provided with the **complete, pristine parent policy**, guaranteeing zero hallucination while maintaining micro-search accuracy.

---

<a id="qa-user-memories"></a>
### Q3: When is data inserted into `user_memories`, and why do we have `memory_type` when queries filter by `user_id`?

#### Part A: When is data inserted?
1. **Cold-Start Account Initialization:**
   When a user account is configured, background sync scripts (or [`services/ai/scripts/seed_user_memories.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/scripts/seed_user_memories.py)) persist known loyalty tiers and base account facts.
2. **Dynamic Cross-Session Memory API:**
   Any service can call `store_user_memory()` in [`services/ai/app/db/memory_store.py`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/memory_store.py).
3. **Agent Episodic Learning / Post-Turn Extraction:**
   When a user explicitly expresses an enduring preference (e.g., *"I always prefer refunds to my original credit card, never store credit"*), the agent extraction layer calls `store_user_memory()` to record the preference for all future chat threads.

#### Part B: Why do we have `memory_type` if we fetch using `user_id`?
Even though queries filter by `user_id`, `memory_type` serves three critical production needs:

1. **Semantic Prompt Formatting:**
   In [`services/ai/app/db/memory_store.py:L94-L99`](file:///Users/milanpreetsingh/Desktop/enterprise-ai-system/services/ai/app/db/memory_store.py#L94-L99), the LLM system prompt is structured with explicit type badges:
   ```text
   [Long-Term Customer Profile & Episodic History]:
   - [TIER_STATUS]: Customer is a verified Diamond VIP Loyalty Member (60-day window).
   - [PREFERENCE]: Customer strictly prefers refunds back to original credit card.
   - [INCIDENT]: Customer experienced previous shipping delays on high-value electronics.
   ```
   This teaches the LLM how to weight facts: `TIER_STATUS` is an authoritative rule; `PREFERENCE` is a personal choice; `INCIDENT` is historical context.

2. **Differentiated Lifecycle & TTL Policies:**
   - `TIER_STATUS`: Updated/overwritten when a user upgrades tiers.
   - `PREFERENCE`: Overwritten when the user changes notification or refund preferences.
   - `INCIDENT`: Expired or pruned after 90 days.

3. **Specialist-Specific Scoped Filtering:**
   Different specialist nodes can filter memory subsets when needed:
   ```sql
   -- Order Specialist only needs Tier Status and Refund Preferences
   SELECT * FROM user_memories 
   WHERE user_id = $1 AND memory_type IN ('TIER_STATUS', 'PREFERENCE');
   
   -- Escalation Specialist retrieves sentiment and past incidents
   SELECT * FROM user_memories 
   WHERE user_id = $1 AND memory_type = 'INCIDENT';
   ```

---

[Back to Top ↑](#document-navigation)
