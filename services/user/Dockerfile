# -------------------------------------------------------------
# Enterprise AI System - User Service Production Multi-Stage Dockerfile
# Production Standard: Non-root user, stripped static binary, <20MB
# -------------------------------------------------------------

# Stage 1: Build binary
FROM golang:alpine AS builder

WORKDIR /workspace

# Copy required module definitions
COPY proto-schemas/go.mod proto-schemas/go.sum* ./proto-schemas/
COPY services/user/go.mod services/user/go.sum* ./services/user/

# Initialize isolated go workspace for layer caching
RUN go work init ./proto-schemas ./services/user && \
    cd services/user && go mod download

# Copy source code
COPY proto-schemas ./proto-schemas
COPY services/user ./services/user

# Compile static binary with optimizations
WORKDIR /workspace/services/user
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /bin/user-service ./cmd/server/main.go

# Stage 2: Minimal Runtime Environment
FROM alpine:3.21

RUN apk --no-cache add ca-certificates tzdata && \
    addgroup -g 10001 appgroup && \
    adduser -u 10001 -G appgroup -D -H appuser

USER 10001:10001
WORKDIR /app

COPY --from=builder /bin/user-service /app/user-service

EXPOSE 50051

ENTRYPOINT ["/app/user-service"]
