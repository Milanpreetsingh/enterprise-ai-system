# Order Microservice

The **Order Service** is a Go gRPC microservice that manages the order lifecycle. It verifies user existence by calling the User Microservice over gRPC, saves orders to PostgreSQL, and produces asynchronous event notifications to Kafka using an **Idempotent Producer**.

---

## 🚀 Key Responsibilities

1. **Order gRPC Endpoints:** Implements `CreateOrder` and `GetOrder` RPCs.
2. **Inter-Service Communication:** Acts as a gRPC client to the User Service (`localhost:50051`) to validate that the `UserID` exists before placing an order.
3. **Kafka Event Producer:** Publishes `OrderCreated` JSON events to the `order-events` topic. Uses the `UserID` as the **Message Key** (guaranteeing ordering per user across topic partitions) and sets `Idempotent: true` to prevent duplicate message writes.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `50052` | gRPC server listening port. |
| `DB_DSN` | `host=localhost user=postgres password=postgres dbname=postgres port=5432 sslmode=disable TimeZone=UTC` | PostgreSQL database DSN. |
| `USER_SERVICE_ADDR` | `localhost:50051` | gRPC address of the User Service for validation calls. |
| `KAFKA_BROKERS` | `localhost:9092` | Kafka broker connection string. |
| `KAFKA_ORDER_TOPIC` | `order-events` | Target Kafka topic for order events. |

---

## 🏃 How to Run Locally

Make sure PostgreSQL, Kafka, and the User Service are running.

```bash
# From the services/order directory:
go run cmd/server/main.go
```

---

## 🧪 Testing gRPC Methods via `grpcurl`

### 1. Create Order via gRPC
```bash
grpcurl -plaintext -d '{
  "user_id": "<VALID_USER_UUID>",
  "product_id": "product-uuid-999",
  "quantity": 3
}' localhost:50052 order.OrderService/CreateOrder
```

### 2. Get Order Details via gRPC
```bash
grpcurl -plaintext -d '{
  "id": "<ORDER_UUID>"
}' localhost:50052 order.OrderService/GetOrder
```
