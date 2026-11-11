# Comprehensive gRPC Request Execution Flow Guide

This document explains the step-by-step internal execution flow of a gRPC call between microservices (e.g., when the **Order Service** calls `s.userClient.GetUser(...)` on the **User Service**).

---

## 🏛️ High-Level Architecture Flow

```
┌────────────────────────────────────────────────────────┐
│                   CLIENT (Caller)                      │
│   e.g., Order Service / API Gateway (Process A)        │
│                                                        │
│   s.userClient.GetUser(ctx, &GetUserRequest{Id: "123"}) │
└───────────────────────────┬────────────────────────────┘
                            │
                            │ 1. Marshal Go Struct ➔ Binary Bytes
                            │ 2. Construct HTTP/2 Path: "/user.UserService/GetUser"
                            │
                            ▼
          ====================================
               HTTP/2 POST over TCP Socket
                    Target: :50051
          ====================================
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                   SERVER (Receiver)                    │
│             User Microservice (Process B)              │
│                                                        │
│ 3. Match Path "/user.UserService/GetUser" in ServiceDesc│
│ 4. Execute Wrapper: _UserService_GetUser_Handler      │
│ 5. Unmarshal Binary Bytes ➔ *userpb.GetUserRequest    │
│ 6. Delegate ➔ userGRPCHandler.GetUser(...)             │
│ 7. Delegate ➔ user_service.go (Business Logic & DB)    │
└────────────────────────────────────────────────────────┘
```

---

## 🔍 Detailed Step-by-Step Execution Journey

### Step 1: The Client Makes the Call (Caller Side)
In the Order Service or API Gateway, you invoke the gRPC method via the generated client interface:

```go
resp, err := s.userClient.GetUser(ctx, &userpb.GetUserRequest{Id: userID})
```

#### What happens under the hood?
`userClient` is an instance of `userServiceClient` generated in `proto-schemas/userpb/user_grpc.pb.go`:

```go
// Inside user_grpc.pb.go (Lines 64-71)
func (c *userServiceClient) GetUser(ctx context.Context, in *GetUserRequest, opts ...grpc.CallOption) (*UserResponse, error) {
    cOpts := append([]grpc.CallOption{grpc.StaticMethod()}, opts...)
    out := new(UserResponse)
    
    // Executes HTTP/2 RPC call over client connection (c.cc)
    err := c.cc.Invoke(ctx, UserService_GetUser_FullMethodName, in, out, cOpts...)
    if err != nil {
        return nil, err
    }
    return out, nil
}
```

1. **Full Method Name Lookup:** The generated code accesses the string constant `UserService_GetUser_FullMethodName`, which is defined as:
   ```go
   const UserService_GetUser_FullMethodName = "/user.UserService/GetUser"
   ```
2. **Binary Marshaling:** The client framework serializes (marshals) the `GetUserRequest` Go struct into raw Protobuf binary bytes.
3. **HTTP/2 Transport:** It transmits an HTTP/2 POST request over the TCP socket (`userConn`) connected to `localhost:50051`.

---

### Step 2: Network Transmission (HTTP/2 Frame)

The network request travels across the socket as a standard HTTP/2 frame:

```http
POST /user.UserService/GetUser HTTP/2
Host: localhost:50051
Content-Type: application/grpc

[Binary Protobuf Bytes Payload]
```

---

### Step 3: Server Registration & Path Matching (Receiver Side)

When the User Microservice starts in `cmd/server/main.go`, it registers its gRPC handler:

```go
userpb.RegisterUserServiceServer(grpcServer, userGRPCHandler)
```

#### The Registration Table (`UserService_ServiceDesc`):
Inside `proto-schemas/userpb/user_grpc.pb.go` (Lines 226–246), `protoc` generated a routing lookup map:

```go
var UserService_ServiceDesc = grpc.ServiceDesc{
    ServiceName: "user.UserService",
    Methods: []grpc.MethodDesc{
        {
            MethodName: "GetUser",
            Handler:    _UserService_GetUser_Handler, // Wrapper function pointer
        },
        ...
    },
}
```

The gRPC server stores an in-memory routing map:
👉 **Map Key:** `"/user.UserService/GetUser"` ➔ **Map Value:** `_UserService_GetUser_Handler`

When the HTTP/2 POST request arrives at port `:50051`:
1. The server inspects the HTTP path header: `"/user.UserService/GetUser"`.
2. It looks up the key in its hash map and matches it to `_UserService_GetUser_Handler`.

---

### Step 4: Server Wrapper Execution & Unmarshaling

The gRPC server executes `_UserService_GetUser_Handler` (found in `user_grpc.pb.go`, lines 169–185):

```go
// Inside user_grpc.pb.go (Lines 169-185)
func _UserService_GetUser_Handler(srv interface{}, ctx context.Context, dec func(interface{}) error, ...) (interface{}, error) {
    in := new(GetUserRequest)
    
    // 1. Unmarshal incoming binary payload into Go struct 'in'
    if err := dec(in); err != nil {
        return nil, err
    }
    
    // 2. Cast 'srv' to UserServiceServer interface and invoke your handler!
    return srv.(UserServiceServer).GetUser(ctx, in)
}
```

1. **Unmarshaling:** `dec(in)` converts the incoming binary bytes into a Go `GetUserRequest` struct.
2. **Method Forwarding:** `srv.(UserServiceServer).GetUser(ctx, in)` calls your concrete `UserGRPCHandler` in `services/user/internal/handler/grpc.go`.

---

### Step 5: Application Business Logic & Database Execution

Your handler inside `services/user/internal/handler/grpc.go` receives the request:

```go
func (h *UserGRPCHandler) GetUser(ctx context.Context, req *userpb.GetUserRequest) (*userpb.UserResponse, error) {
    // 1. Delegate to business logic in user_service.go
    user, err := h.userService.GetUser(ctx, req.GetId())
    if err != nil {
        return nil, status.Errorf(codes.NotFound, "user not found: %v", err)
    }

    // 2. Return Protobuf Response struct
    return &userpb.UserResponse{
        Id:       user.ID,
        Email:    user.Email,
        FullName: user.FullName,
    }, nil
}
```

1. `h.userService.GetUser(...)` in `services/user/internal/service/user_service.go` executes.
2. It queries PostgreSQL via the `userRepo` repository layer.
3. The database record is retrieved, mapped to `UserResponse`, and returned.

---

### Step 6: The Return Trip (Server ➔ Client)

1. **Server Marshaling:** The server framework takes `UserResponse`, serializes it to binary bytes, and sends it back over the HTTP/2 response stream.
2. **Client Unmarshaling:** `userServiceClient.GetUser(...)` on the caller side receives the response bytes, unmarshals them into `*userpb.UserResponse`, and returns it to your caller variable (`resp`).

---

## 💡 Summary Comparison: Client vs. Server Operations

| Action | Client (Caller) Side | Server (Receiver) Side |
| :--- | :--- | :--- |
| **Request Payload** | **Marshals (Serializes)** Go Struct $\rightarrow$ Binary Bytes | **Unmarshals (Deserializes)** Binary Bytes $\rightarrow$ Go Struct |
| **URL Path** | Supplies `UserService_GetUser_FullMethodName` | Matches path in `ServiceDesc` lookup map |
| **Response Payload** | **Unmarshals (Deserializes)** Binary Bytes $\rightarrow$ Go Struct | **Marshals (Serializes)** Go Struct $\rightarrow$ Binary Bytes |

---

## 🌊 Unary vs. Streaming gRPC & Browser Ingress Architecture

### Core Architecture: TCP Connection vs. HTTP/2 Streams

A fundamental concept in gRPC and HTTP/2 is the difference between the **Underlying Physical Transport (TCP Socket)** and the **Logical Channels (HTTP/2 Streams)**:

```
                      ONE PERSISTENT HTTP/2 TCP CONNECTION (Never Closes)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                        │
│   Stream 1 [Unary: GetOrder]         ──HEADERS+DATA──>   <──HEADERS+DATA+TRAILER(END)─ (Stream 1 Closes)
│                                                                                        │
│   Stream 3 [Streaming: StreamChat]   ──HEADERS+DATA──>   <──DATA──DATA──DATA────────── (Stream 3 Open)
│                                                                                        │
│   Stream 5 [Unary: GetUser]          ──HEADERS+DATA──>   <──HEADERS+DATA+TRAILER(END)─ (Stream 5 Closes)
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **The TCP Connection (L4 Socket)**:
   - Established **once** via a 3-way handshake during service startup (e.g. `grpc.NewClient("localhost:50051", ...)` in `api-gateway/main.go`).
   - Remains **open indefinitely** and is reused across all calls.
2. **The HTTP/2 Stream (L7 Logical Channel)**:
   - Every single RPC call is allocated a unique integer `Stream ID` (e.g., Stream `1`, `3`, `5`).
   - Multiplexed concurrently over the single TCP socket without blocking each other.

---

### Q1: Does gRPC keep the HTTP/2 connection open for both Unary and Streaming?

**Yes.** In gRPC, the underlying **TCP connection is kept open for both Unary and Streaming calls**.

#### What actually "closes" in a Unary RPC?
Only the **specific HTTP/2 Stream ID** closes, **not** the underlying TCP connection!

- **In a Unary RPC (`GetOrder` in `order.proto`)**:
  1. The client sends a `HEADERS` frame and a `DATA` frame.
  2. The server responds with `HEADERS`, a single `DATA` frame, and a `TRAILERS` frame containing the `END_STREAM` flag.
  3. That individual **Stream ID is closed and marked finished**.
  4. The **TCP socket remains alive**, waiting to multiplex the next RPC.

- **In a Server-Streaming RPC (`StreamChat` in `ai.proto`)**:
  1. The client sends a `HEADERS` and a `DATA` frame.
  2. The server sends `HEADERS`, and then keeps pushing **multiple `DATA` frames over time** on that same Stream ID (each token: *"I've"*, *"checked"*, *"your"*, *"order"*...).
  3. The server only attaches the `END_STREAM` flag on the final frame. Until then, that **logical stream remains active**.

---

### Q2: Why does the frontend send a new request on every "Send" click? What is the difference between REST and Streaming?

Every time a user clicks **Send 🚀** in the web frontend, the browser initiates a **new HTTP request** regardless of protocol:

- **When "Standard REST" is selected**:
  ```javascript
  const res = await fetch(`${AI_SERVICE_URL}/chat`, { method: 'POST', body: JSON.stringify({...}) });
  const data = await res.json();
  ```
  The browser sends a POST request and waits until the AI service completes the full graph execution. All tokens arrive at once in **one single buffered JSON response**.

- **When "Server-Sent Events (SSE)" is selected**:
  ```javascript
  const eventSource = new EventSource(`${GATEWAY_URL}/chat/stream?message=...`);
  eventSource.onmessage = (event) => {
      assistantBubble.textContent += JSON.parse(event.data).token;
  };
  ```
  The browser sends a GET request to open an SSE stream. The server flushes each token chunk over HTTP chunked transfer encoding as it is produced by the LLM (`data: {"token": "..."}\n\n`), creating the real-time typewriter effect.

| Dimension | Standard REST (`POST /api/v1/chat`) | Streaming SSE (`GET /api/v1/chat/stream`) |
| :--- | :--- | :--- |
| **Request Count** | 1 HTTP request per user message | 1 HTTP request per user message |
| **Response Model** | **Buffered**: 1 single complete JSON response | **Streaming**: Continuous real-time event chunks |
| **Latency to First Token** | High (waits for full generation, ~3–5s) | Ultra-low (sub-200ms first token) |
| **Transport** | Standard HTTP JSON body | HTTP Server-Sent Events (`text/event-stream`) |

---

### Q3: Is the browser secretly reusing the same connection for every "Send" click?

**Yes.** Under the hood, the browser maintains a connection pool and reuses the same TCP socket:

1. **In Local Development (over HTTP: `http://localhost:3000` / `http://localhost:8080`)**:
   - Modern browsers use **HTTP/1.1 with `Connection: keep-alive`**.
   - On the first button click, the browser executes the TCP 3-way handshake to `:8080`.
   - On subsequent clicks, Chrome/Safari reuses the **exact same idle TCP socket**, avoiding handshake latency.

2. **In Production (over HTTPS / TLS)**:
   - Browsers negotiate **HTTP/2** via TLS ALPN (`h2`).
   - The browser opens **exactly 1 physical TCP connection** to the backend domain.
   - Every click on "Send" — whether a REST `fetch()` or an SSE `EventSource` — opens a **multiplexed HTTP/2 stream** inside that single connection.

---

### 🏛️ Complete End-to-End Connection Architecture

```
[ BROWSER ]
    │
    │  HTTP/1.1 (Keep-Alive) or HTTP/2 (Multiplexed)
    │  • Same TCP connection reused across clicks
    │  • Each click sends a new HTTP request
    ▼
[ API GATEWAY (:8080) ]
    │
    ├─── Long-lived HTTP/2 TCP Connection 1 ───> [ USER SERVICE (:50051) ]  (Unary RPCs multiplexed)
    │
    ├─── Long-lived HTTP/2 TCP Connection 2 ───> [ ORDER SERVICE (:50052) ] (Unary RPCs multiplexed)
    │
    └─── Long-lived HTTP/2 TCP Connection 3 ───> [ AI SERVICE (:50053) ]    (Streaming RPCs multiplexed)
```

---

### 📝 Contract Differences in `.proto` Definitions

| Aspect | Unary Contract (`order.proto` / `user.proto`) | Server-Streaming Contract (`ai.proto`) |
| :--- | :--- | :--- |
| **Syntax** | `rpc GetOrder(GetOrderRequest) returns (OrderResponse);` | `rpc StreamChat(ChatStreamRequest) returns (stream ChatStreamResponse);` |
| **Keyword** | Standard `returns (Type)` | **`returns (stream Type)`** |
| **Client Method** | `GetOrder(ctx, req) (*OrderResponse, error)` | `StreamChat(ctx, req) (AIService_StreamChatClient, error)` |
| **Client Reading** | Single variable return `resp` | Dedicated stream with **`.Recv()`** method in a loop |
| **Server Handler** | Single `return &OrderResponse{...}, nil` in Go | Generator using **`yield`** in Python or `stream.Send()` in Go |

