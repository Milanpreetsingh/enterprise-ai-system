from enum import StrEnum

class OrderStatus(StrEnum):
    """OrderStatus defines the lifecycle state of orders."""
    PENDING = "PENDING"
    PENDING_CANCELLATION = "PENDING_CANCELLATION"
    CANCELLED = "CANCELLED"

class EventType(StrEnum):
    """EventType defines Kafka event header signatures."""
    ORDER_CREATED = "OrderCreated"
    ORDER_CANCELLATION_REQUESTED = "OrderCancellationRequested"
    ORDER_REFUND_PROCESSED = "OrderRefundProcessed"
    INVENTORY_RESTOCKED = "InventoryRestocked"

class KafkaConfig:
    """Default Kafka topic, broker, and consumer group configurations."""
    DEFAULT_BROKERS = "localhost:9092"
    DEFAULT_TOPIC = "order-events"
    DEFAULT_DLQ_TOPIC = "order-dlq"
    DEFAULT_CONSUMER_GROUP = "notification-service-group"
