# Microservices gRPC Architecture & Schema Management FAQ

A comprehensive architectural reference guide covering gRPC service-to-service communication, Protobuf schema management in Monorepo vs. Polyrepo, code generation, serialization, versioning, and Docker container deployment.

---

## 📌 Table of Contents

- [1. Context Code Reference](#1-context-code-reference)
- [2. Polyrepo Architecture (Multi-Repo Setup)](#2-polyrepo-architecture-multi-repo-setup)
  - [Q2.1: How does Order Service call User Service across different repositories?](#q21-how-does-order-service-call-user-service-across-different-repositories)
- [3. Protobuf Code Generation & Serialization Deep-Dive](#3-protobuf-code-generation--serialization-deep-dive)
  - [Q3.1: Why is generated Go code (`.pb.go`) required in `proto-schemas`?](#q31-why-is-generated-go-code-pbgo-required-in-proto-schemas)
  - [Q3.2: How does `.pb.go` handle Marshaling/Unmarshaling on Client vs Server?](#q32-how-does-pbgo-handle-marshalingunmarshaling-on-client-vs-server)
  - [Q3.3: What "version mismatch" exists if Go compilers are backward compatible?](#q33-what-version-mismatch-exists-if-go-compilers-are-backward-compatible)
  - [Q3.4: What happens if services use different `protoc` versions locally without committing generated code?](#q34-what-happens-if-services-use-different-protoc-versions-locally-without-committing-generated-code)
- [4. Buf Schema Registry (BSR)](#4-buf-schema-registry-bsr)
  - [Q4.1: Do we push `.proto` files or generated Go code to Buf?](#q41-do-we-push-proto-files-or-generated-go-code-to-buf)
  - [Q4.2: How does Buf avoid version mismatches if we only push `.proto` files?](#q42-how-does-buf-avoid-version-mismatches-if-we-only-push-proto-files)
  - [Q4.3: How does Buf choose the Go version for generated code?](#q43-how-does-buf-choose-the-go-version-for-generated-code)
- [5. Monorepo Docker Builds & Deployment](#5-monorepo-docker-builds--deployment)
  - [Q5.1: How do Docker builds work in a Monorepo using `go.work`?](#q51-how-do-docker-builds-work-in-a-monorepo-using-gowork)
- [6. Architecture Summary Cheat Sheet](#6-architecture-summary-cheat-sheet)

---

## 1. Context Code Reference

In our application (`services/order/internal/service/order_service.go`), the **Order Service** makes a gRPC call to verify a user via the **User Service**:

```go
// 1. Importing protobuf package
import userpb "enterprise-ai-system/proto-schemas/userpb"

// 2. Struct definition in Order Service
type orderService struct {
    userClient userpb.UserServiceClient
}

// 3. gRPC Client Call inside Order Service
_, err := s.userClient.GetUser(ctx, &userpb.GetUserRequest{Id: userID})
```

---

## 2. Polyrepo Architecture (Multi-Repo Setup)

### Q2.1: How does Order Service call User Service across different repositories?

> **Question**: In our local setup both services live in the same project directory (`go.work`). But if both services live in completely separate Git repositories (Polyrepo), how does Order Service import and call User Service?

#### Answer

In a **Polyrepo** architecture, microservices **never import application source code directly from another microservice's repository**. Instead, gRPC communication relies on sharing **Protobuf contracts and generated client stubs**.

There are 3 standard industry approaches:

#### 🏆 Approach A: Dedicated Proto/Contracts Repository (Recommended)
Create a central Git repository solely for Protobuf schemas (e.g., `github.com/your-org/proto-schemas`).

```text
github.com/your-org/proto-schemas/
├── user/v1/user.proto
├── order/v1/order.proto
└── gen/go/userpb/      <-- Generated Go client stubs committed via CI/CD
```

1. **CI/CD Automation**: Whenever `.proto` files change, CI compiles them and pushes generated Go stubs with a git tag (e.g. `v1.2.0`).
2. **Go Module Import**: Order Service pulls the client contract in `go.mod`:
   ```bash
   go get github.com/your-org/proto-schemas/gen/go/userpb@v1.2.0
   ```
3. **Usage in Code**:
   ```go
   import userpb "github.com/your-org/proto-schemas/gen/go/userpb"

   _, err := s.userClient.GetUser(ctx, &userpb.GetUserRequest{Id: userID})
   ```

#### ⚡ Approach B: Buf Schema Registry (BSR)
Modern gRPC teams use [Buf](https://buf.build). 
- Push `.proto` definitions to Buf Registry (`buf.build/your-org/user-service`).
- Buf dynamically generates language stubs on demand:
  ```bash
  go get buf.build/gen/go/your-org/user-service/protocolbuffers/go@v1.2.0
  ```

#### 📦 Approach C: Exported Protos inside User Service Repo
User Service exports generated code in a public folder inside its own repo (`github.com/your-org/user-service/pkg/userpb`).
> [!NOTE]
> *Drawback*: Order Service has to pull the entire User Service repository as a Go module dependency just to access its generated Protobuf types.

---

## 3. Protobuf Code Generation & Serialization Deep-Dive

### Q3.1: Why is generated Go code (`.pb.go`) required in `proto-schemas`?

> **Question**: Why is generated Go code (`grpc.pb.go`, `pb.go`) required in the shared repository or for integrating other gRPC services? Isn't generated code only required in the server service itself to handle incoming requests?

#### Answer

Go is a **statically typed, compiled language**. It cannot parse or execute raw `.proto` text files at runtime or compile time.

> [!IMPORTANT]
> When `protoc` compiles `user.proto`, it generates **two separate pieces** of Go code:
> 1. **`user.pb.go` (Data Types & Serialization)**: Contains Go `struct` definitions (`GetUserRequest`, `GetUserResponse`) and binary marshaling/unmarshaling functions.
> 2. **`user_grpc.pb.go` (Server Interface AND Client Stubs)**: Contains **`UserServiceServer`** (implemented by User Service to receive calls) **AND** **`UserServiceClient`** (used by Order Service to make calls).

Without the generated Go code, Order Service cannot compile:
- `&userpb.GetUserRequest{Id: userID}` fails because the Go `struct` definition does not exist.
- `s.userClient.GetUser(...)` fails because the client interface and networking stub do not exist.

---

### Q3.1b: Why do we have two interfaces (`UserServiceClient` vs. `UserServiceServer`)?

> **Question**: In `user_grpc.pb.go`, why are there two distinct interfaces generated: `UserServiceClient` and `UserServiceServer`? What is the difference between them and who implements which?

#### Answer

gRPC generates two separate interfaces because **calling a service (Client)** and **providing a service (Server)** have completely different roles, method signatures, and implementations.

#### 1. Quick Comparison Matrix

| Property | `UserServiceClient` | `UserServiceServer` |
| :--- | :--- | :--- |
| **Role** | **Consumer / Caller** (Makes outgoing calls) | **Provider / Handler** (Answers incoming calls) |
| **Who Implements It?** | **gRPC Framework automatically** (`userServiceClient` struct) | **You (The Developer)** in `UserHandler` |
| **Where is it Used?** | In **Order Service** & **API Gateway** | In **User Service** |
| **Method Signature** | Includes `opts ...grpc.CallOption` | Standard `(context.Context, *Request)` |
| **Under the Hood** | Marshals Go struct $\rightarrow$ Sends binary HTTP/2 request | Unmarshals incoming binary $\rightarrow$ Runs DB logic |

#### 2. Method Signature Differences

Notice the difference in the generated signatures:

```go
// 1. Client Interface: accepts CallOptions (timeouts, retries, headers)
type UserServiceClient interface {
    GetUser(ctx context.Context, in *GetUserRequest, opts ...grpc.CallOption) (*UserResponse, error)
}

// 2. Server Interface: pure business logic contract (no client options!)
type UserServiceServer interface {
    GetUser(context.Context, *GetUserRequest) (*UserResponse, error)
    mustEmbedUnimplementedUserServiceServer()
}
```

#### 3. How They Are Used in Our Project

- **In Order Service (`services/order/internal/service/order_service.go`)**:
  Order Service holds the **Client interface** because it needs to *call* User Service:
  ```go
  type orderService struct {
      userClient userpb.UserServiceClient // 👈 CLIENT INTERFACE
  }
  // Order Service calls:
  _, err := s.userClient.GetUser(ctx, &userpb.GetUserRequest{Id: userID})
  ```

- **In User Service (`services/user/internal/handler/grpc.go`)**:
  The developer implements the **Server interface** to *handle* the call:
  ```go
  type UserHandler struct {
      userpb.UnimplementedUserServiceServer // 👈 SERVER INTERFACE
      userService service.UserService
  }
  // User Service implements the logic:
  func (h *UserHandler) GetUser(ctx context.Context, req *pb.GetUserRequest) (*pb.UserResponse, error) {
      // Query PostgreSQL database, return UserResponse
  }
  ```

---

### Q3.2: How does `.pb.go` handle Marshaling/Unmarshaling on Client vs Server?

> **Question**: In Order Service (Client), `user.pb.go` marshals the Go request struct to Protobuf binary and unmarshals the response binary back into a Go struct. Does it work in reverse inside User Service (Server)?

#### Answer

**Yes, exactly!** 🎯

Both client and server import the **exact same `user.pb.go` generated package**. The functions inside `user.pb.go` provide bidirectional serialization.

#### End-to-End gRPC Call Lifecycle:

```text
[ Order Service (Client) ]                                      [ User Service (Server) ]
---------------------------                                      -------------------------
1. Create Go Struct:                                            
   req := &GetUserRequest{Id: "123"}                           
                                                                
2. Marshal (user.pb.go):                                        
   Go Struct  ──►  Protobuf Binary                                
                                                                
3. Send over Wire (HTTP/2)  ────── Protobuf Binary ────────►  4. Receive from Wire (HTTP/2)
                                                                
                                                               5. Unmarshal (user.pb.go):
                                                                  Protobuf Binary  ──►  Go Struct
                                                                
                                                               6. Execute Handler & Query DB
                                                                
                                                               7. Create Response Go Struct:
                                                                  resp := &GetUserResponse{...}
                                                                
                                                               8. Marshal (user.pb.go):
                                                                  Go Struct  ──►  Protobuf Binary
                                                                
9. Receive from Wire (HTTP/2) ◄───── Protobuf Binary ────────── 9. Send Response over Wire
                                                                
10. Unmarshal (user.pb.go):                                     
    Protobuf Binary  ──►  Go Struct                             
```

- **Order Service (Client)**: **Marshals** the request $\rightarrow$ **Unmarshals** the response.
- **User Service (Server)**: **Unmarshals** the request $\rightarrow$ **Marshals** the response.

---

### Q3.3: What "version mismatch" exists if Go compilers are backward compatible?

> **Question**: Go language compiler versions (`go 1.18`, `go 1.25`) are backward compatible. So what version mismatch does Buf or Approach A prevent when locking in generated Go code?

#### Answer

There is a critical distinction between **Go Language Compiler Version** vs **Protobuf Generator Plugin & Runtime Library Versions**:

| Component | What It Is | Compatibility Behavior |
| :--- | :--- | :--- |
| **Go Compiler Version** (`go 1.18`, `go 1.25`) | Official Go compiler & standard library (`fmt`, `context`, `net/http`). | **100% Backward Compatible** (Go 1 promise). |
| **Protobuf Plugin & Library** (`protoc-gen-go`, `google.golang.org/protobuf`) | Third-party tools used to generate `.go` source code from `.proto`. | **Breaking Changes & API Shifts Exist** across major plugin versions. |

#### What happens if developers compile `.proto` locally (No Buf / No Committed `gen/go`)?
- **Developer A** has `protoc-gen-go v1.20` installed (legacy Protobuf API v1 `github.com/golang/protobuf`).
- **Developer B** has `protoc-gen-go v1.33` installed (modern Protobuf API v2 `google.golang.org/protobuf`).

When Developer A compiles locally, it generates code using `proto.RegisterType(...)`. When Developer B compiles locally, it generates code using `protoimpl`. 

Combining these in Order Service causes compilation errors or runtime panics:
```text
panic: proto: file "user.proto" has a name conflict with ...
undefined: proto.RegisterType
```

> [!TIP]
> **Solution**: Approach A (CI/CD committed code) and Buf (BSR) lock down the **`protoc-gen-go` plugin version** centrally so every service uses the exact same generator version.

---

### Q3.4: What happens if services use different `protoc` versions locally without committing generated code?

> **Question**: If Order Service and User Service compile `.proto` locally using different `protoc` versions (e.g. `v3.12` vs `v28.0`), will it break runtime communication?

#### Answer

#### 1. At Network Runtime: NO Problem! 🟢
gRPC services **do not send Go code over the network**. They communicate strictly over TCP/HTTP2 using the **standardized Protobuf Binary Wire Format**.
- The binary wire format (varints, field tags, byte lengths) is universal.
- User Service compiled with `protoc v3.12` can seamlessly communicate with Order Service compiled with `protoc v28.0` (or Java/Rust).

#### 2. Inside Order Service Binary & Build Pipeline: YES, Problems Exist! 🔴
- **Internal Registry Conflicts**: If Order Service imports `User Service` (compiled with old `protoc-gen-go`) and `Payment Service` (compiled with new `protoc-gen-go`), the Order Service binary will fail to build or crash at startup.
- **Tooling Overhead**: Every developer laptop and CI runner must install `protoc`, `protoc-gen-go`, and `protoc-gen-go-grpc` binaries locally.
- **Inconsistent API Features**: Developers miss out on newer Protobuf Go features (like `protojson` or `optional` getters) if locked to an older local `protoc`.

---

## 4. Buf Schema Registry (BSR)

### Q4.1: Do we push `.proto` files or generated Go code to Buf?

> **Question**: When using Buf Schema Registry (`buf.build`), do we push generated Go code into it, or `.proto` files only?

#### Answer

**Only `.proto` files!** 🚀

1. **Developer Workflow**: Developers run `buf push` to upload raw `.proto` files. No generated code is committed to Git.
2. **Cloud Generation**: Buf compiles `.proto` files in the cloud using pinned plugin versions.
3. **Synthetic Language Proxies**: Buf acts as a native module registry for all languages:
   ```bash
   # Go
   go get buf.build/gen/go/your-org/user-service/protocolbuffers/go@v1.2.0

   # Node.js
   npm install @buf/your-org_user-service.bufbuild_es
   ```

---

### Q4.2: How does Buf avoid version mismatches if we only push `.proto` files?

#### Answer

Buf Schema Registry enforces consistency via 4 mechanisms:

1. **Immutable Version Tags**: `buf push` assigns immutable semantic version tags (`v1.2.0`) and commit hashes. `go get` downloads deterministic build outputs.
2. **Automated Breaking Change Checks (`buf breaking`)**: CI runs `buf breaking` against `main`. Deleting fields or changing types fails the build before code can be pushed.
3. **Centralized Plugin Versions**: Compiler plugin versions (`protoc-gen-go v1.32.0`) are pinned centrally in `buf.gen.yaml`.
4. **API Package Namespacing**: Major breaking changes use new package versions (`package user.v1;` vs `package user.v2;`).

---

### Q4.3: How does Buf choose the Go version for generated code?

#### Answer

1. **Source Text Generation**: Buf generates plain Go source code (`.go`), not compiled binaries.
2. **Conservative `go.mod` Target**: Buf's synthetic module sets a conservative baseline (e.g. `go 1.18` or `go 1.20`).
3. **Cross-Version Compatibility**: Because Go compilers are backward compatible:
   - `User Service` (compiled with Go 1.20)
   - `Order Service` (compiled with Go 1.25)
   
   Both seamlessly compile the shared proto package and communicate over the network without any conflicts.

---

## 5. Monorepo Docker Builds & Deployment

### Q5.1: How do Docker builds work in a Monorepo using `go.work`?

> **Question**: Locally we use a monorepo workspace (`go.work`). But when deploying to the cloud, each Docker container is built for a single service (e.g., Order Service). How do imports work during Docker builds?

#### Answer

> [!IMPORTANT]
> **The Golden Rule of Monorepo Docker Builds**:
> Always set the **Docker Build Context to the root of the Monorepo**, NOT inside `services/order/`.

#### Step 1: Run Docker Build from Repository Root
```bash
# Execute from repository root (/enterprise-ai-system):
docker build -t order-service:latest -f services/order/Dockerfile .
```

#### Step 2: Multi-Stage `Dockerfile` (`services/order/Dockerfile`)

```dockerfile
# --- Stage 1: Build Binary ---
FROM golang:1.25-alpine AS builder

WORKDIR /workspace

# 1. Copy workspace & module files from monorepo root
COPY go.work go.work.sum ./
COPY proto-schemas/go.mod proto-schemas/go.sum ./proto-schemas/
COPY services/order/go.mod services/order/go.sum ./services/order/

# 2. Download dependencies
WORKDIR /workspace/services/order
RUN go mod download

# 3. Copy source code for proto-schemas and order service
WORKDIR /workspace
COPY proto-schemas/ ./proto-schemas/
COPY services/order/ ./services/order/

# 4. Compile the binary using go.work context
WORKDIR /workspace/services/order
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/order-service ./cmd/main.go

# --- Stage 2: Minimal Runtime Image ---
FROM alpine:latest
WORKDIR /app
COPY --from=builder /app/order-service /app/order-service

EXPOSE 50052
ENTRYPOINT ["/app/order-service"]
```

---

## 6. Architecture Summary Cheat Sheet

| Scenario | Code Sharing Strategy | Build Mechanism |
| :--- | :--- | :--- |
| **Monorepo (Local Dev)** | `go.work` linking local folders (`./proto-schemas`) | `go run ./cmd/main.go` from `services/order` |
| **Monorepo (Cloud Docker)** | Copy `proto-schemas` & `services/order` into build context | `docker build -f services/order/Dockerfile .` from root |
| **Polyrepo (Central Proto Repo)** | Tagged Git Go module (`gen/go/userpb`) | `go get github.com/your-org/proto-schemas/gen/go/userpb` |
| **Polyrepo (Buf BSR)** | Remote synthetic module via `buf.build` | `go get buf.build/gen/go/your-org/user-service/...` |
