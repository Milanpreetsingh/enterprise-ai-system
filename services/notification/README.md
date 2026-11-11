# Notification Microservice

The **Notification Service** is an asynchronous Python service that consumes order lifecycle events from Apache Kafka and dispatches transactional emails (e.g. order confirmations, cancellations, refund notices). It guarantees exactly-once processing per consumer group using an idempotent database ledger and handles delivery failures via a Dead Letter Queue (DLQ).

---

## 🚀 Key Responsibilities

1. **Kafka Event Consumer**: Consumes events from the `order-events` topic (`OrderCreated`, `OrderCancellationRequested`, `OrderRefundProcessed`, `InventoryRestocked`).
2. **Idempotency Guard**: Tracks event execution in the `processed_events` table in PostgreSQL to ensure no customer receives duplicate email notifications during network reconnects or partition rebalances.
3. **Multi-Provider SMTP Support**: Formats and sends HTML/plain-text transactional emails via SMTP (compatible with MailHog for local development, SendGrid, Amazon SES, or Mailgun).
4. **Dead Letter Queue (DLQ)**: Publishes poison pills and unparseable events to `order-dlq` to prevent consumer lag or halting the event loop.

---

## ⚙️ Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DB_DSN` | `dbname=postgres user=postgres password=postgres host=localhost port=5432` | PostgreSQL connection string. |
| `KAFKA_BROKERS` | `localhost:9092` | Kafka broker list (comma-separated). |
| `KAFKA_ORDER_TOPIC` | `order-events` | Inbound Kafka topic for order events. |
| `KAFKA_DLQ_TOPIC` | `order-dlq` | Kafka topic for Dead Letter Queue. |
| `KAFKA_CONSUMER_GROUP` | `notification-service-group` | Kafka consumer group name. |
| `SMTP_HOST` | `localhost` | SMTP host (e.g., `localhost` for MailHog or `smtp.sendgrid.net`). |
| `SMTP_PORT` | `1025` | SMTP port (`1025` for MailHog, `587` for standard TLS). |
| `SMTP_USER` | `""` | SMTP authentication username. |
| `SMTP_PASSWORD` | `""` | SMTP authentication password. |
| `SMTP_FROM` | `support@enterprise.ai` | From sender email address. |

---

## 🏃 How to Run Locally

Ensure PostgreSQL and Kafka are up and running:

```bash
# From services/notification:
python3 main.py
```

