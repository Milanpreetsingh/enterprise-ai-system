# -------------------------------------------------------------
# Enterprise AI System - Notification Service Dockerfile
# Production Standard: Python slim, non-root user
# -------------------------------------------------------------

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create non-root system user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/false -m appuser

# Copy requirements and install
COPY services/notification/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY services/notification/ ./

USER 10001:10001

CMD ["python", "main.py"]

