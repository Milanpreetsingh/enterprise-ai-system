# Shared Protocol Buffer Schemas (`proto-schemas`)

This module houses the centralized **Protocol Buffer (Proto3)** contracts for the enterprise microservices. By defining API contracts in `.proto` files, we enforce strict type safety, backward compatibility, and language-agnostic service boundaries.

---

## 📁 Directory Structure

```
proto-schemas/
├── user.proto      # Schema contract for User Service RPCs and messages
├── order.proto     # Schema contract for Order Service RPCs and messages
├── ai.proto        # Schema contract for AI Service RPCs and streaming
├── userpb/         # Generated Go package for user.proto
│   ├── user.pb.go
│   └── user_grpc.pb.go
├── orderpb/        # Generated Go package for order.proto
│   ├── order.pb.go
│   └── order_grpc.pb.go
└── aipb/           # Generated Go package for ai.proto
    ├── ai.pb.go
    └── ai_grpc.pb.go
```

---

## ⚙️ How to Re-generate Go Code from `.proto` Files

If you modify `user.proto`, `order.proto`, or `ai.proto`, compile the updated Go code by running `protoc`:

### Prerequisites
Make sure `protoc` and the Go gRPC plugins are installed:
```bash
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
```

### Generation Command
Run the compilation from the repository root:

```bash
# From workspace root:
protoc --proto_path=. \
       --go_out=. --go_opt=module=enterprise-ai-system/proto-schemas \
       --go-grpc_out=. --go-grpc_opt=module=enterprise-ai-system/proto-schemas \
       proto-schemas/user.proto proto-schemas/order.proto proto-schemas/ai.proto
```

This properly compiles each `.proto` file into its declared subpackage (`userpb/`, `orderpb/`, and `aipb/`) as configured by `option go_package`, avoiding duplicate root files or multi-package directory conflicts.
