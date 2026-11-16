# SDE-3 Infrastructure, Docker & Kubernetes Masterclass
## Production Containerization, Orchestration & Resilience for the Enterprise AI System

---

## 1. Executive Overview & The SDE-3 Infra Mandate

At the **SDE-3 / Senior Staff Backend & Infrastructure** level, you are not simply expected to write application logic; you are expected to own the **resilience, deployment lifecycle, scalability, and operational security** of distributed systems.

In distributed microservices, application code (Go, Python, gRPC, Kafka) and infrastructure code (Docker, Kubernetes, Networking, CNI, Linux Cgroups) are two halves of the same coin:
* **SDE-1 / SDE-2 Perspective:** *"I wrote the Go code and it works on my machine. Here is a single-line Dockerfile."*
* **SDE-3 Perspective:** *"I have containerized each service with multi-stage non-root builds (<20MB), eliminated attack vectors, decoupled stateful and stateless workloads using Kubernetes Deployments and StatefulSets, configured startup/readiness/liveness probes to guarantee zero-downtime rolling deployments, isolated inter-service gRPC communication via internal ClusterIP CoreDNS, and provisioned Horizontal Pod Autoscalers (HPA) to dynamically handle traffic spikes."*

This document serves as both:
1. **The Comprehensive Learning Guide**: Deep architectural explanations of Docker, Linux kernel primitives (namespaces/cgroups), Kubernetes control-plane components, and cluster networking.
2. **The End-to-End Implementation Plan**: Step-by-step instructions to containerize our polyglot system, deploy it onto a local multi-node Kubernetes cluster (**Kind** / **Minikube**), and expose it to the internet via **Cloudflare Tunnel** for portfolio and interview demonstrations.

---

## 2. System Topology & Infrastructure Architecture

Our enterprise architecture consists of **7 distinct distributed components** with very different operational characteristics:

```
                                [ Public Internet / Cloudflare Tunnel ]
                                                   │
                                                   ▼ (HTTPS :443 / :80)
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                               KUBERNETES CLUSTER (Kind / EKS)                               │
│                                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                        Ingress Controller (Nginx Ingress / Traefik)                   │  │
│  └───────────────────┬─────────────────────────────────────────────────┬─────────────────┘  │
│                      │ Path: /                                         │ Path: /api/*       │
│                      ▼                                                 ▼                    │
│     ┌─────────────────────────────────┐               ┌─────────────────────────────────┐   │
│     │   frontend-app (Deployment)     │               │     api-gateway (Deployment)    │   │
│     │   • Replicas: 2                 │               │     • Replicas: 3 (Auto-scaling)│   │
│     │   • Nginx Alpine (<15MB)        │               │     • Go Gin HTTP / SSE Engine  │   │
│     └─────────────────────────────────┘               └────────────────┬────────────────┘   │
│                                                                        │                    │
│                             ┌──────────────────────────────────────────┴───────────────┐    │
│                             │ Internal gRPC Mesh (ClusterIP DNS Discovery)             │    │
│                             ▼                                          ▼               │    │
│              ┌─────────────────────────────┐            ┌─────────────────────────────┐│    │
│              │   order-service (Deployment)│            │ inventory-service (Deploy)  ││    │
│              │   • Replicas: 2             │            │ • Replicas: 2               ││    │
│              │   • Go gRPC Server (:50051) │            │ • Go gRPC Server (:50052)   ││    │
│              └──────────────┬──────────────┘            └──────────────┬──────────────┘│    │
│                             │                                          │               │    │
│                             └─────────────────────┬────────────────────┘               │    │
│                                                   │                                    │    │
│                                                   ▼                                    ▼    │
│                                    ┌─────────────────────────────┐      ┌──────────────────┐│
│                                    │      ai-service (Deploy)    │      │ redis (Stateful) ││
│                                    │      • Replicas: 2          │◄────►│ • Port: 6379     ││
│                                    │      • Python gRPC (:50053) │      │ • Semantic Cache ││
│                                    │      • PyTorch & LangGraph  │      └──────────────────┘│
│                                    └──────────────┬──────────────┘                          │
│                                                   │                                         │
│               ┌───────────────────────────────────┴───────────────────────────────────┐     │
│               ▼                                                                       ▼     │
│┌─────────────────────────────┐                                         ┌───────────────────┐│
││    postgres (StatefulSet)   │                                         │ kafka (StatefulSet││
││ • Port: 5432                │                                         │ • Port: 9092      ││
││ • pgvector extension        │                                         │ • KRaft mode      ││
││ • Dedicated PVC (10Gi disk) │                                         │ • Dedicated PVC   ││
│└─────────────────────────────┘                                         └───────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Concepts Masterclass: The SDE-3 Infra Curriculum

### 3.1 Docker & Containerization Primitives

Containers are **not** virtual machines. A container is simply a standard Linux process isolated using two Linux kernel features:
1. **Namespaces (Visibility Isolation)**:
   * `pid`: Isolates process IDs (PID 1 inside the container is not PID 1 on the host).
   * `net`: Isolates network interfaces, routing tables, and IP addresses.
   * `mnt`: Isolates filesystem mount points.
   * `ipc`: Isolates inter-process shared memory.
2. **Control Groups (cgroups - Resource Enforcement)**:
   * Sets strict bounds on CPU, memory, disk I/O, and thread count.
   * If a container attempts to use more RAM than its `limits.memory`, the Linux kernel triggers the **OOM Killer (Out Of Memory Killer)** and sends `SIGKILL` (`Exit Code 137`).

#### The SDE-3 Production Dockerfile Standard:
* **Multi-Stage Builds**: Compile code in a heavy build environment (containing compilers, Git, build tools), and copy **only the final compiled static binary** into a bare runtime image (such as `scratch` or `alpine`).
  * *Result:* Go images drop from **850 MB** down to **~18 MB**. Attack surface drops by 99% (no bash, no curl, no package managers).
* **Layer Caching Optimization**: Docker builds execute top-to-bottom. If a layer hasn't changed, Docker reuses the cached layer.
  * *Rule:* Copy dependency files (`go.mod`, `go.sum`, `requirements.txt`) and run package downloads *before* copying the application source code. Code changes will then build in **<2 seconds** instead of re-downloading modules every build.
* **Non-Root Execution**:
  * By default, containers run as `root` (UID 0). If a vulnerability allows container breakout, the attacker has root privileges on the host kernel!
  * Production containers must define `USER 10001:10001` or `USER nonroot`.

---

### 3.2 Kubernetes: The Declarative Orchestrator

Kubernetes is a declarative state machine. You declare your **Desired State** in YAML, and Kubernetes constantly runs **Reconciliation Loops** to drive the **Actual State** towards the Desired State.

#### Key Kubernetes Components:
* **Kube-Apiserver**: The central REST API entry point for all operations (`kubectl`).
* **etcd**: Consistent, distributed key-value store holding the entire cluster state.
* **Kube-Scheduler**: Watches for newly created Pods without assigned nodes and assigns them based on resource availability, affinities, and taints.
* **Kube-Controller-Manager**: Runs core reconciliation loops (Deployment controller, Node controller, ReplicaSet controller).
* **Kubelet**: Node agent running on every worker node. Ensures that containers described in `PodSpecs` are running and healthy.
* **Kube-Proxy**: Maintains network rules on nodes to route traffic to Service IP addresses (using `iptables` or `IPVS`).

---

### 3.3 Stateless vs. Stateful Workloads: Deployments vs. StatefulSets

One of the most important architectural decisions an SDE-3 makes is choosing between a **Deployment** and a **StatefulSet**:

| Characteristic | Deployment (Stateless) | StatefulSet (Stateful) |
| :--- | :--- | :--- |
| **Used For** | `api-gateway`, `order`, `inventory`, `ai-service` | `postgres`, `kafka`, `redis` |
| **Pod Identity** | Random, ephemeral hashes (e.g. `order-7b89f-k9x2m`) | Deterministic, stable ordinal indexes (`kafka-0`, `kafka-1`) |
| **Storage (Volumes)** | Ephemeral or shared read-only mounts | Dedicated **PersistentVolumeClaim (PVC)** per ordinal index |
| **Scaling & Rollouts** | Pods created/killed simultaneously in parallel | Ordered, sequential creation (`0` &rarr; `1` &rarr; `2`) and reverse deletion |
| **Network Identity** | Shared round-robin VIP (ClusterIP) | Dedicated **Headless Service** (`clusterIP: None`) providing stable DNS per pod |

---

### 3.4 Zero-Downtime Resilience: The 3 Kubernetes Probes

In production, rolling deployments fail if traffic is routed to pods that are not ready, or if deadlocked pods are not restarted. SDE-3s configure three distinct probes:

```
[ Container Boot ]
        │
        ▼
┌──────────────────────────────┐
│ 1. startupProbe              │ ──► Has the heavy app (e.g. PyTorch) loaded weights into memory?
└──────────────┬───────────────┘     Failure: Kubelet kills container and retries.
               │ Passes
               ▼
┌──────────────────────────────┐
│ 2. readinessProbe            │ ──► Is the DB connection pool active & Kafka consumer connected?
└──────────────┬───────────────┘     Failure: Temporarily removes pod from Service load balancer!
               │ Passes              (Zero 502/503 errors during deployments!)
               ▼
┌──────────────────────────────┐
│ 3. livenessProbe             │ ──► Is the process event loop alive, or is it deadlocked?
└──────────────────────────────┘     Failure: Kubelet terminates pod and spawns a fresh replacement.
```

1. **`startupProbe` (Crucial for AI Service)**:
   * Loading PyTorch CPU wheels and the HuggingFace Cross-Encoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) takes **15–30 seconds**.
   * Without a startup probe, an aggressive liveness probe would kill the Python process repeatedly before it finishes initializing!
2. **`readinessProbe` (Zero 500s during deployment)**:
   * When deploying a new version of `order-service`, the pod is "running" before it connects to PostgreSQL and Kafka.
   * The readiness probe gates traffic until `/healthz/ready` returns `200 OK`.
3. **`livenessProbe` (Self-Healing)**:
   * Checks `/healthz/live`. If a Go goroutine leaks or Python event loop hangs, Kubelet restarts the container.

---

### 3.5 Inter-Service Networking & CoreDNS Service Discovery

In Kubernetes, every pod gets its own private IP address, but pods are ephemeral. SDE-3s **never hardcode IP addresses**. Instead, we use Kubernetes **Services** and **CoreDNS**:

* **ClusterIP**: A stable internal virtual IP (VIP) backed by CoreDNS.
* When `api-gateway` calls `order-service` via gRPC, it connects to:
  ```
  order-service.enterprise-ai.svc.cluster.local:50051
  ```
* CoreDNS resolves this domain to the ClusterIP, and `kube-proxy` (via `iptables`) automatically load-balances the gRPC TCP connections across healthy pods.

---

### 3.6 Horizontal Pod Autoscaling (HPA)

Kubernetes includes an automated scaling engine called **HorizontalPodAutoscaler (HPA)**:
* Evaluates pod metrics (CPU, Memory, or custom metrics like Kafka consumer lag) every 15 seconds.
* Scaling Formula:
  $$\text{Desired Replicas} = \left\lceil \text{Current Replicas} \times \frac{\text{Current Metric Value}}{\text{Target Metric Value}} \right\rceil$$
* If `api-gateway` is running 2 pods and average CPU hits **80%** (target: **50%**), HPA calculates:
  $$\text{Desired Replicas} = \lceil 2 \times (80 / 50) \rceil = \lceil 3.2 \rceil = 4 \text{ pods}$$
* HPA scales the deployment up to 4 pods automatically. When traffic subsides, a **stabilization window** (default: 5 minutes) prevents rapid scale-down flapping.

---

## 4. End-to-End Implementation Plan

The implementation is broken into **5 progressive phases**:

```
Phase 1: Production Multi-Stage Dockerfiles (Go, Python, Nginx)
Phase 2: Local Multi-Node Kubernetes Cluster Setup (Kind / Minikube)
Phase 3: Stateful Infrastructure Manifests (Postgres pgvector, Kafka KRaft, Redis)
Phase 4: Stateless Microservices & Ingress Manifests (Deployments, Services, Ingress, HPA)
Phase 5: Public Exposure via Cloudflare Tunnel (Live Portfolio URL)
```

---

### Phase 1: Multi-Stage Production Dockerfiles

We will construct production Dockerfiles for each component:

#### 1.1 `api-gateway/Dockerfile`
* **Stage 1 (Builder)**: `golang:1.24-alpine` compiles `main.go` with CGO disabled (`CGO_ENABLED=0`) and stripped debug symbols (`-ldflags="-s -w"`).
* **Stage 2 (Runtime)**: `alpine:3.21` with `ca-certificates` and non-root user. Final size: **~18 MB**.

#### 1.2 `services/order/Dockerfile` & `services/inventory/Dockerfile`
* Multi-stage Go builds with internal proto dependencies. Final size: **~18 MB**.

#### 1.3 `services/ai/Dockerfile`
* Base: `python:3.11-slim` (or `3.13-slim`).
* Installs PyTorch CPU wheels (`--extra-index-url https://download.pytorch.org/whl/cpu`) to avoid downloading 2GB+ of unnecessary CUDA/NVIDIA GPU libraries.
* Pre-downloads HuggingFace Cross-Encoder models during `docker build` so cold starts take **<2 seconds** instead of downloading weights on container start!

#### 1.4 `frontend-app/Dockerfile`
* Base: `nginx:alpine`.
* Injects custom `nginx.conf` that serves static files and proxies `/api/*` to the API Gateway. Final size: **~12 MB**.

---

### Phase 2: Local Kubernetes Cluster Setup (`Kind`)

Instead of single-node Docker Desktop, SDE-3s use **Kind (Kubernetes in Docker)** to simulate real multi-node cloud environments (1 Control Plane + 2 Worker nodes):

```yaml
# kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
  - role: worker
  - role: worker
```

**Commands to provision:**
```bash
brew install kind kubectl
kind create cluster --name enterprise-ai --config kind-config.yaml
kubectl get nodes
```

---

### Phase 3: Stateful Kubernetes Manifests (`k8s/stateful/`)

1. **Namespace & Configurations**:
   * `k8s/00-namespace.yaml`: Defines `namespace: enterprise-ai`.
   * `k8s/01-configmaps.yaml`: Environment variables (`KAFKA_BROKERS`, `DB_PORT`, `GROQ_MODEL`).
   * `k8s/02-secrets.yaml`: Base64 secrets (`POSTGRES_PASSWORD`, `GROQ_API_KEY`, `JWT_SECRET`).
2. **PostgreSQL with `pgvector`**:
   * `k8s/stateful/postgres.yaml`: `StatefulSet` + `PersistentVolumeClaim` (5Gi) + `Service: postgres`.
3. **Apache Kafka (KRaft mode)**:
   * `k8s/stateful/kafka.yaml`: Single-node or 3-node KRaft `StatefulSet` + PVC + `Service: kafka`.
4. **Redis**:
   * `k8s/stateful/redis.yaml`: `StatefulSet` + `Service: redis`.

---

### Phase 4: Stateless Microservices & Ingress (`k8s/deployments/`)

1. **Deployments**:
   * `k8s/deployments/order-service.yaml` (2 replicas, gRPC port 50051).
   * `k8s/deployments/inventory-service.yaml` (2 replicas, gRPC port 50052).
   * `k8s/deployments/ai-service.yaml` (2 replicas, gRPC port 50053, HTTP 8000, startup probe).
   * `k8s/deployments/api-gateway.yaml` (3 replicas, HTTP port 8080).
   * `k8s/deployments/frontend.yaml` (2 replicas, HTTP port 80).
2. **Ingress Controller & Routing**:
   * Install Nginx Ingress:
     ```bash
     kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
     ```
   * `k8s/ingress.yaml`: Routes traffic:
     * `/api/*` &rarr; `api-gateway:8080`
     * `/chat/stream` &rarr; `api-gateway:8080` (with SSE chunked streaming headers)
     * `/` &rarr; `frontend-app:80`
3. **Autoscaling (HPA)**:
   * `k8s/hpa/gateway-hpa.yaml`: Scales `api-gateway` from 2 to 10 pods when CPU > 70%.

---

### Phase 5: Public Exposure via Cloudflare Tunnel

To showcase your live cluster to recruiters from anywhere:
```bash
brew install cloudflared
# Expose the Kubernetes Ingress controller running on port 80
cloudflared tunnel --url http://localhost:80
```
Recruiters receive a public HTTPS link (e.g. `https://enterprise-support-demo.trycloudflare.com`) where every request hits your **multi-node Kubernetes cluster**!

---

## 5. SDE-3 Interview Defense & System Design Questions

When interviewing for Senior/Staff roles, expect these infrastructure questions based on this architecture:

### Q1: "Why did you use a StatefulSet for Kafka and Postgres instead of a regular Deployment?"
> **Answer:** *"Deployments treat pods as anonymous, ephemeral entities with non-deterministic hostnames (e.g., `pod-7b8x-k2m`). If a pod dies, the replacement pod receives a completely new identity and cannot reclaim the previous pod's storage. Databases and Kafka require deterministic network identities (e.g., `kafka-0`, `kafka-1`) and dedicated PersistentVolumeClaims (PVCs) that automatically reattach to the exact same ordinal pod upon restart. Furthermore, StatefulSets provide ordered graceful shutdown (`N-1` before `N-2`), which prevents split-brain and raft quorum corruption in KRaft and database replication."*

### Q2: "How do you guarantee zero downtime during rolling deployments of your Go and AI microservices?"
> **Answer:** *"We configure three layers of protection:*
> 1. *`readinessProbe`: The Kubernetes Service load balancer does not route a single user request to a new pod until its internal health check passes (database pool initialized, Kafka consumers joined the group).*
> 2. *`startupProbe`: Specifically for the Python AI service, PyTorch model weights take ~20 seconds to load. A startup probe grants a 45-second failure window before liveness checks start, preventing premature crash-loop kills.*
> 3. *`preStop` hook & graceful shutdown: When Kubernetes terminates a pod, it sends `SIGTERM`. Our Go services catch `SIGTERM`, stop accepting new connections, finish inflight gRPC requests, and commit active Kafka offsets within a 15-second grace period before `SIGKILL`."*

### Q3: "What happens if the Python AI service hits an Out-Of-Memory (OOM) condition?"
> **Answer:** *"We enforce explicit `resources.requests` and `resources.limits`. For `ai-service`, we set a memory request of `1Gi` and a hard limit of `2.5Gi`. If LangGraph state explosion or PyTorch tensor allocation exceeds 2.5Gi, the Linux cgroup triggers an OOM event (`Exit Code 137`). Because the deployment has 2 replicas behind a ClusterIP service, the surviving pod absorbs incoming traffic with zero dropped connections while Kubernetes immediately restarts the failed pod on a healthy worker node."*

### Q4: "How does inter-service gRPC communication work inside Kubernetes?"
> **Answer:** *"We use Kubernetes ClusterIP Services with CoreDNS. When `api-gateway` makes a gRPC call to `order-service`, it dials `dns:///order-service.enterprise-ai.svc.cluster.local:50051`. Because gRPC uses HTTP/2 with persistent multiplexed TCP connections, standard L4 transport-level load balancing can lead to uneven traffic. To ensure balanced distribution, we either configure gRPC client-side round-robin balancing using `grpc.WithDefaultServiceConfig('{\"loadBalancingConfig\": [{\"round_robin\":{}}]}')` or deploy a lightweight Service Mesh (like Envoy/Linkerd)."*

---

## 6. SDE-3 Competency Checklist

Use this checklist to track your mastery as we build out this infrastructure:

- [ ] **Docker Multi-Stage Builds**: Go binary compressed to <20MB scratch/alpine container.
- [ ] **Docker Layer Caching**: Dependency downloads separated from source code copying.
- [ ] **Docker Security**: Non-root container execution (`USER 10001:10001`).
- [ ] **Kind Multi-Node Cluster**: 1 Control-Plane + 2 Worker nodes running locally.
- [ ] **StatefulSets & Storage**: Postgres (pgvector) and Kafka (KRaft) provisioned with PVCs.
- [ ] **Probes**: Configured `startupProbe`, `readinessProbe`, and `livenessProbe` on all deployments.
- [ ] **Internal DNS Service Discovery**: Gateway dialing microservices via ClusterIP DNS.
- [ ] **Ingress Controller**: Path-based routing for static frontend and SSE chat streams.
- [ ] **Horizontal Pod Autoscaling**: HPA auto-scaling Go microservices under synthetic load.
- [ ] **Cloudflare Tunnel**: Public HTTPS access to the local Kubernetes Ingress.

