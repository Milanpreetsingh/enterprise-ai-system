#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo "  Deploying Enterprise Omnichannel AI System to Kubernetes"
echo "=========================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. Apply Namespace
echo "==> [Step 1/5] Creating Namespace..."
kubectl apply -f "${SCRIPT_DIR}/00-namespace.yaml"

# 2. Apply ConfigMaps and Secrets
echo "==> [Step 2/5] Applying ConfigMaps and Secrets..."
kubectl apply -f "${SCRIPT_DIR}/01-configmaps.yaml"
kubectl apply -f "${SCRIPT_DIR}/02-secrets.yaml"

# 3. Apply Stateful Infrastructure (Postgres, Redis, Kafka)
echo "==> [Step 3/5] Provisioning Stateful Infrastructure (Postgres, Redis, Kafka)..."
kubectl apply -f "${SCRIPT_DIR}/stateful/postgres.yaml"
kubectl apply -f "${SCRIPT_DIR}/stateful/redis.yaml"
kubectl apply -f "${SCRIPT_DIR}/stateful/kafka.yaml"

# 4. Apply Stateless Microservices (Order, User, Inventory, Notification, AI, Gateway, Frontend)
echo "==> [Step 4/5] Deploying Microservices & AI Engine..."
kubectl apply -f "${SCRIPT_DIR}/deployments/order-service.yaml"
kubectl apply -f "${SCRIPT_DIR}/deployments/user-service.yaml"
kubectl apply -f "${SCRIPT_DIR}/deployments/inventory-service.yaml"
kubectl apply -f "${SCRIPT_DIR}/deployments/notification-service.yaml"
kubectl apply -f "${SCRIPT_DIR}/deployments/ai-service.yaml"
kubectl apply -f "${SCRIPT_DIR}/deployments/api-gateway.yaml"
kubectl apply -f "${SCRIPT_DIR}/deployments/frontend.yaml"

# 5. Apply Ingress & HPA
echo "==> [Step 5/5] Configuring Ingress & Horizontal Pod Autoscaling..."
kubectl apply -f "${SCRIPT_DIR}/ingress.yaml"
kubectl apply -f "${SCRIPT_DIR}/hpa/gateway-hpa.yaml"

echo "=========================================================="
echo "  Deployment Complete! Checking Pod Status in enterprise-ai..."
echo "=========================================================="
kubectl get pods,services,hpa -n enterprise-ai

