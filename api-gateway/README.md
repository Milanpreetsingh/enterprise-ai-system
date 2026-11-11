# API Gateway Service

The **API Gateway** is the central edge entry point for public clients (web, mobile). Built with Go and Gin, it handles HTTP REST requests, enforces JWT authentication, and proxies requests to backend Go microservices over high-performance gRPC. It also acts as the unified **Model Context Protocol (MCP) Server** for the Python AI service.

---

## 🚀 Key Responsibilities

1. **Protocol Translation (BFF):** Translates incoming HTTP/JSON REST requests into binary gRPC requests for downstream microservices.
2. **JWT Authentication:** Intercepts requests, validates JWT access tokens in the `Authorization` header, and passes claims downstream.
3. **MCP Tool Provider:** Exposes internal microservice capabilities via standard MCP JSON-RPC (`/api/v1/mcp`) for AI agents.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8080` | Port for the HTTP REST Gateway server. |
| `USER_SERVICE_ADDR` | `localhost:50051` | gRPC address of the User Microservice. |
| `ORDER_SERVICE_ADDR` | `localhost:50052` | gRPC address of the Order Microservice. |
| `JWT_SECRET` | `super-secret-key-change-in-production` | Secret key for signing and verifying JWT tokens. |

---

## 🏃 How to Run Locally

```bash
# From the api-gateway directory:
go run main.go
```

---

## 🧪 Testing API Endpoints

### 1. User Signup
```bash
curl -X POST http://localhost:8080/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "testuser@example.com",
    "password": "password123",
    "full_name": "Test User"
  }'
```

### 2. User Login (Obtain JWT)
```bash
curl -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "testuser@example.com",
    "password": "password123"
  }'
```
*(Save the `access_token` returned in the response for protected routes!)*

### 3. Token Refresh
```bash
curl -X POST http://localhost:8080/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "<YOUR_REFRESH_TOKEN>"
  }'
```

### 4. Create Order (JWT Protected)
```bash
curl -X POST http://localhost:8080/api/v1/orders \
  -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "quantity": 2
  }'
```

### 5. Fetch Order Details (JWT Protected)
```bash
curl -X GET http://localhost:8080/api/v1/orders/<ORDER_UUID> \
  -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>"
```

### 6. Test Model Context Protocol (MCP) JSON-RPC Endpoint

#### List Tools (`tools/list`)
```bash
curl -X POST http://localhost:8080/api/v1/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1
  }'
```

#### Call Tool (`tools/call`)
```bash
curl -X POST http://localhost:8080/api/v1/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "get_order_details",
      "arguments": {
        "id": "<ORDER_UUID>"
      }
    },
    "id": 2
  }'
```
