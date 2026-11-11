# Infrastructure Stack (`infra`)

This directory manages containerized infrastructure configurations, environment settings, and local Docker deployment manifests for the **Enterprise Omnichannel AI Support Hub**.

---

## 🐳 Docker Services Overview

The local infrastructure stack is managed via the root `docker-compose.yml` file and includes:

1. **PostgreSQL 16 (`pgvector/pgvector:pg16`):**
   * **Port:** `5432`
   * **Credentials:** `user=user`, `password=password`, `database=supporthub` *(Default local fallback: `user=postgres`, `password=postgres`)*
   * **Extensions:** `pgvector` enabled for vector RAG embeddings.
2. **Redis (`redis:7-alpine`):**
   * **Port:** `6379`
   * **Usage:** High-speed semantic cache and session storage.
3. **Kafka (`apache/kafka:latest`):**
   * **Port:** `9092`
   * **Mode:** **KRaft Mode** (Zookeeper-less self-managed metadata controller).

---

## 🛠️ Infrastructure Commands

```bash
# Start all infrastructure containers in detached mode
docker compose up -d

# Check status of containers
docker compose ps

# View container logs (e.g. Kafka logs)
docker compose logs -f kafka

# Stop all infrastructure containers
docker compose down
```
