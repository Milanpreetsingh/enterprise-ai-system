# -------------------------------------------------------------
# Enterprise AI System - AI Service Production Multi-Stage Dockerfile
# Production Standard: PyTorch CPU wheels, pre-cached HuggingFace weights
# -------------------------------------------------------------

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/cache/huggingface \
    TRANSFORMERS_CACHE=/app/cache/huggingface

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Pre-install PyTorch CPU-only wheel (avoids 2.5GB CUDA bloat)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy dependencies and install Python packages
COPY services/ai/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Cross-Encoder model into Docker image layer
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# Copy AI service codebase and entrypoint
COPY services/ai/ ./

# Fix permissions
RUN chown -R appuser:appgroup /app

USER 10001:10001

EXPOSE 8000 50053

ENTRYPOINT ["./entrypoint.sh"]

