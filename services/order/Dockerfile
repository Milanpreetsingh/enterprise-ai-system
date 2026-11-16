# -------------------------------------------------------------
# Enterprise AI System - Order Service Production Multi-Stage Dockerfile
# Production Standard: Non-root user, stripped static binary, <20MB
# -------------------------------------------------------------

# Stage 1: Build binary
FROM golang:alpine AS builder

WORKDIR /workspace

# Copy required module definitions
COPY proto-schemas/go.mod proto-schemas/go.sum* ./proto-schemas/
COPY services/order/go.mod services/order/go.sum* ./services/order/

# Initialize isolated go workspace for layer caching
RUN go work init ./proto-schemas ./services/order && \
    cd services/order && go mod download

# Copy source code
COPY proto-schemas ./proto-schemas
COPY services/order ./services/order

# Compile static binary with optimizations
WORKDIR /workspace/services/order
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /bin/order-service ./cmd/server/main.go

# Stage 2: Minimal Runtime Environment
FROM alpine:3.21

RUN apk --no-cache add ca-certificates tzdata && \
    addgroup -g 10001 appgroup && \
    adduser -u 10001 -G appgroup -D -H appuser

USER 10001:10001
WORKDIR /app

COPY --from=builder /bin/order-service /app/order-service

EXPOSE 50052

ENTRYPOINT ["/app/order-service"]
