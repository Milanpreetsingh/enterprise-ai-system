# Inventory Microservice

The **Inventory Service** is an event-driven Go microservice responsible for real-time stock management and warehouse reconciliations. It listens to Kafka order cancellation events, restocks inventory, and uses an idempotent database inbox pattern with Dead Letter Queue (DLQ) support for unprocessable events.

---

## 🚀 Key Responsibilities

1. **Kafka Event Consumer**: Listens to the `order-events` Kafka topic for `OrderCancellationRequested` and related events.
2. **ACID Idempotent Inbox**: Prevents duplicate restocking by verifying each event against the `processed_events` table inside a PostgreSQL transaction before updating warehouse stock levels.
3. **Dead Letter Queue (DLQ)**: Automatically routes corrupted payloads or permanently failed events to `order-dlq` to maintain continuous stream processing.
4. **Cooperative Sticky Rebalancing**: Utilizes Kafka's RoundRobin and Range balancers for zero-downtime partition reassignment.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `50053` | Service port (if exposing gRPC/health). |
| `DB_DSN` | `host=localhost user=postgres password=postgres dbname=postgres port=5432 sslmode=disable TimeZone=UTC` | PostgreSQL connection string. |
| `KAFKA_BROKERS` | `localhost:9092` | Comma-separated Kafka broker addresses. |
| `KAFKA_ORDER_TOPIC` | `order-events` | Inbound Kafka topic for order events. |
| `KAFKA_DLQ_TOPIC` | `order-dlq` | Dead Letter Queue topic for malformed or failed messages. |
| `KAFKA_CONSUMER_GROUP` | `inventory-service-group` | Kafka consumer group name. |

---

## 🏃 How to Run Locally

Make sure PostgreSQL and Kafka are running via Docker Compose (`docker-compose up -d`).

```bash
# From the repository root or services/inventory directory:
cd services/inventory
go run cmd/server/main.go
```

