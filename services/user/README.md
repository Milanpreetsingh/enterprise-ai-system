# User Microservice

The **User Service** is a Go gRPC microservice responsible for user identity management, authentication credentials, bcrypt password hashing, and user profile persistence. It also hosts an asynchronous **Kafka Consumer** that listens for order events to update user statistics in real-time.

---

## 🚀 Key Responsibilities

1. **gRPC Identity Endpoints:** Exposes `CreateUser`, `GetUser`, `LoginUser`, and `RefreshToken` via high-performance gRPC.
2. **Security & Cryptography:** Performs secure password hashing using `bcrypt` and signs/verifies JWT access and refresh tokens.
3. **Event Consumer (Kafka):** Runs a background loop attached to the `user-service-group` consumer group. When an `OrderCreated` event is emitted by the Order Service, the consumer increments the user's `order_count` in PostgreSQL atomically using **At-Least-Once** manual offset commits.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `50051` | gRPC server listening port. |
| `DB_DSN` | `host=localhost user=postgres password=postgres dbname=postgres port=5432 sslmode=disable TimeZone=UTC` | PostgreSQL database DSN. |
| `JWT_SECRET` | `super-secret-key-change-in-production` | Key used for JWT signing. |
| `KAFKA_BROKERS` | `localhost:9092` | Kafka broker connection string. |
| `KAFKA_ORDER_TOPIC` | `order-events` | Target Kafka topic for order lifecycle events. |
| `KAFKA_USER_GROUP` | `user-service-group` | Kafka consumer group ID for load balancing. |

---

## 🏃 How to Run Locally

Make sure PostgreSQL and Kafka are running via Docker Compose (`docker compose up -d`).

```bash
# From the services/user directory:
go run cmd/server/main.go
```

---

## 🧪 Testing gRPC Methods via `grpcurl`

If you have `grpcurl` installed, you can query the User Service gRPC server directly:

### 1. List Available gRPC Services
```bash
grpcurl -plaintext localhost:50051 list
```

### 2. Create User via gRPC
```bash
grpcurl -plaintext -d '{
  "email": "user@example.com",
  "password": "secretpassword",
  "full_name": "Jane Doe"
}' localhost:50051 user.UserService/CreateUser
```

### 3. Get User Profile via gRPC
```bash
grpcurl -plaintext -d '{
  "id": "<USER_UUID>"
}' localhost:50051 user.UserService/GetUser
```

### 4. Authenticate User via gRPC
```bash
grpcurl -plaintext -d '{
  "email": "user@example.com",
  "password": "secretpassword"
}' localhost:50051 user.UserService/LoginUser
```
