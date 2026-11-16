# -------------------------------------------------------------
# Enterprise AI System - API Gateway Production Multi-Stage Dockerfile
# Production Standard: Non-root user, stripped static binary, <20MB
# -------------------------------------------------------------

# Stage 1: Build binary
FROM golang:alpine AS builder

WORKDIR /workspace

# Copy required module definitions
COPY proto-schemas/go.mod proto-schemas/go.sum* ./proto-schemas/
COPY api-gateway/go.mod api-gateway/go.sum* ./api-gateway/

# Initialize isolated go workspace for layer caching
RUN go work init ./proto-schemas ./api-gateway && \
    cd api-gateway && go mod download

# Copy source code
COPY proto-schemas ./proto-schemas
COPY api-gateway ./api-gateway

# Compile static binary with optimizations
WORKDIR /workspace/api-gateway
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /bin/api-gateway main.go

# Stage 2: Minimal Runtime Environment
FROM alpine:3.21

RUN apk --no-cache add ca-certificates tzdata && \
    addgroup -g 10001 appgroup && \
    adduser -u 10001 -G appgroup -D -H appuser

USER 10001:10001
WORKDIR /app

COPY --from=builder /bin/api-gateway /app/api-gateway

EXPOSE 8080

ENTRYPOINT ["/app/api-gateway"]
