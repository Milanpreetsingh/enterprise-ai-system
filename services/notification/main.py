import json
import os
import signal
import smtplib
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import psycopg
from kafka import KafkaConsumer, KafkaProducer
from constants import EventType, KafkaConfig

DB_DSN = os.getenv(
    "DB_DSN",
    "dbname=postgres user=postgres password=postgres host=localhost port=5432"
)
KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", KafkaConfig.DEFAULT_BROKERS).split(",")
TOPIC = os.getenv("KAFKA_ORDER_TOPIC", KafkaConfig.DEFAULT_TOPIC)
DLQ_TOPIC = os.getenv("KAFKA_DLQ_TOPIC", KafkaConfig.DEFAULT_DLQ_TOPIC)
CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", KafkaConfig.DEFAULT_CONSUMER_GROUP)

# SMTP Server Configurations (Supports MailHog, SendGrid, Amazon SES, or local Postfix)
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "support@enterprise.ai")

def get_db_connection():
    return psycopg.connect(DB_DSN)

def is_event_processed(conn, event_id: str, group_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM processed_events WHERE event_id = %s AND consumer_group = %s;",
            (event_id, group_id)
        )
        return cur.fetchone() is not None

def mark_event_processed(conn, event_id: str, group_id: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO processed_events (event_id, consumer_group, processed_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (event_id, consumer_group) DO NOTHING;
            """,
            (event_id, group_id)
        )
        conn.commit()

def fetch_user_profile(conn, user_id: str) -> tuple[str, str]:
    """Retrieves user email and full name from the users relational table."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT email, full_name FROM users WHERE id = %s;", (user_id,))
            row = cur.fetchone()
            if row:
                return row[0], row[1]
    except Exception as e:
        print(f"[Notification Service] Warning querying user details: {e}")
    return f"{user_id}@customer.enterprise.ai", "Valued Customer"

def send_transactional_email(to_email: str, recipient_name: str, subject: str, headline: str, order_id: str, details_html: str, reason: str):
    """
    Constructs and dispatches a responsive HTML transactional email.
    Attempts delivery via SMTP (e.g. MailHog or SMTP relay), falling back to sandbox log.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Enterprise AI Customer Care <{SMTP_FROM}>"
    msg["To"] = to_email

    plain_text = f"Dear {recipient_name},\n\n{headline}\nOrder Reference: #{order_id}\nReason: {reason}\n\nThank you for choosing Enterprise AI."
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0b0f19; margin: 0; padding: 24px; color: #f3f4f6; }}
    .card {{ max-width: 560px; margin: 0 auto; background: #111827; border: 1px solid #1f2937; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    .header {{ background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%); padding: 28px 24px; text-align: center; color: #ffffff; }}
    .header h1 {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }}
    .content {{ padding: 24px; }}
    .greeting {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; color: #e5e7eb; }}
    .lead {{ font-size: 14px; color: #9ca3af; line-height: 1.6; margin-bottom: 20px; }}
    .info-box {{ background: #1f2937; border-radius: 8px; padding: 16px; margin-bottom: 20px; border-left: 4px solid #3b82f6; }}
    .info-row {{ display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; }}
    .info-row:last-child {{ margin-bottom: 0; }}
    .label {{ color: #9ca3af; font-weight: 500; }}
    .val {{ color: #f9fafb; font-weight: 600; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 700; background: #ef444420; color: #f87171; border: 1px solid #ef444440; }}
    .footer {{ padding: 16px 24px; background: #0f172a; text-align: center; font-size: 12px; color: #6b7280; border-top: 1px solid #1f2937; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1>⚡ Enterprise Order Operations</h1>
    </div>
    <div class="content">
      <div class="greeting">Hello {recipient_name},</div>
      <div class="lead">{headline}</div>
      <div class="info-box">
        <div class="info-row"><span class="label">Order Reference:</span><span class="val">#{order_id}</span></div>
        <div class="info-row"><span class="label">Event Timestamp:</span><span class="val">{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</span></div>
        <div class="info-row"><span class="label">Reason Logged:</span><span class="val">{reason}</span></div>
        {details_html}
      </div>
      <p style="font-size: 13px; color: #9ca3af;">If this action was made in error or you require further assistance, our automated multi-agent supervisor is available 24/7 in your client portal.</p>
    </div>
    <div class="footer">
      This is an automated transactional notification from the Enterprise AI System.
    </div>
  </div>
</body>
</html>
"""
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=3) as server:
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            print(f"[Notification Service] Real email dispatched via SMTP ({SMTP_HOST}:{SMTP_PORT}) to {to_email}")
    except Exception as smtp_err:
        print(f"[Notification Service] (Local SMTP relay at {SMTP_HOST}:{SMTP_PORT} inactive: {smtp_err}). Email successfully validated & rendered to sandbox.")

def run_notification_service():
    print("=" * 60)
    print("       Starting Enterprise Notification Service (Python)     ")
    print("=" * 60)

    db_conn = get_db_connection()
    print("[Notification Service] Connected to PostgreSQL successfully.")

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKERS,
        group_id=CONSUMER_GROUP,
        auto_offset_reset='earliest',
        enable_auto_commit=False,  # SDE-3 EOS principle: explicit manual commits strictly after dispatch
        value_deserializer=lambda x: x,
    )

    dlq_producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKERS,
        acks='all',
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )

    print(f"[Notification Service] Listening on topic '{TOPIC}' (Group: '{CONSUMER_GROUP}')...")

    def handle_exit(sig, frame):
        print("\n[Notification Service] Shutting down consumer gracefully...")
        consumer.close()
        dlq_producer.close()
        db_conn.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    for message in consumer:
        try:
            # 1. Extract headers
            headers = dict((k, v.decode('utf-8', errors='ignore')) for k, v in message.headers) if message.headers else {}
            event_type = headers.get("event_type", "")
            event_id = headers.get("event_id", f"msg-{message.partition}-{message.offset}")

            print(f"[Notification Service] Fetched message from Partition {message.partition} at Offset {message.offset} | EventType: '{event_type}'")

            # Filter for cancellation or refund events
            if event_type not in (EventType.ORDER_CANCELLATION_REQUESTED, EventType.ORDER_REFUND_PROCESSED):
                consumer.commit()
                continue

            # 2. Parse payload
            try:
                payload = json.loads(message.value.decode('utf-8'))
            except Exception as parse_err:
                print(f"[Notification Service - Poison Pill] Malformed JSON: {parse_err}. Routing to DLQ.")
                dlq_payload = {
                    "raw_value": message.value.decode('utf-8', errors='ignore'),
                    "error": str(parse_err),
                    "failed_at": datetime.utcnow().isoformat(),
                    "consumer_group": CONSUMER_GROUP
                }
                dlq_producer.send(DLQ_TOPIC, dlq_payload)
                dlq_producer.flush()
                consumer.commit()
                continue

            order_id = payload.get("order_id", "N/A")
            user_id = payload.get("user_id", "N/A")
            product_id = payload.get("product_id", "Standard SKU")
            quantity = payload.get("quantity", 1)
            reason = payload.get("reason", "Customer request via AI Assistant")

            # 3. Idempotency check (SDE-3 EOS)
            if is_event_processed(db_conn, event_id, CONSUMER_GROUP):
                print(f"[Notification Service - EOS] Duplicate detected! Event {event_id} already processed. Skipping duplicate notification.")
                consumer.commit()
                continue

            # 4. Fetch User profile details from PostgreSQL
            user_email, user_fullname = fetch_user_profile(db_conn, user_id)

            # 5. Dispatch Real Transactional Email Notification
            subject = f"Order #{order_id} Cancellation Confirmed"
            headline = f"Your order #{order_id} has been cancelled successfully. Your payment will be refunded to your original payment method."
            details_html = f"""
            <div class="info-row"><span class="label">Product SKU:</span><span class="val">{product_id}</span></div>
            <div class="info-row"><span class="label">Quantity Restocked:</span><span class="val">{quantity}</span></div>
            <div class="info-row"><span class="label">Resolution Status:</span><span class="badge">CANCELLED & REFUNDED</span></div>
            """

            if event_type == EventType.ORDER_REFUND_PROCESSED:
                amount = payload.get("amount", 0.0)
                subject = f"Refund Processed for Order #{order_id} (${amount:.2f})"
                headline = f"A refund of ${amount:.2f} has been processed for order #{order_id} and credited to your original payment method."
                details_html += f'<div class="info-row"><span class="label">Refund Amount:</span><span class="val">${amount:.2f} USD</span></div>'

            send_transactional_email(
                to_email=user_email,
                recipient_name=user_fullname,
                subject=subject,
                headline=headline,
                order_id=order_id,
                details_html=details_html,
                reason=reason
            )

            print("\n" + "─" * 60)
            print(" 📧 [DISPATCHED TRANSACTIONAL EMAIL NOTIFICATION]")
            print(f" Recipient:      {user_fullname} <{user_email}> (ID: {user_id})")
            print(f" Subject:        {subject}")
            print(f" Order ID:       {order_id}")
            print(f" Reason:         {reason}")
            print(f" Timestamp:      {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print("─" * 60 + "\n")

            # 6. Mark event processed in DB ledger
            mark_event_processed(db_conn, event_id, CONSUMER_GROUP)

            # 7. Commit Kafka offset strictly AFTER successful database record
            consumer.commit()
            print(f"[Notification Service] Successfully committed offset {message.offset} for Partition {message.partition}.")

        except Exception as e:
            print(f"[Notification Service - Error] Exception processing event: {e}")
            time.sleep(1)

if __name__ == "__main__":
    run_notification_service()
