package domain

// EventType defines lifecycle events handled by Inventory Service.
type EventType string

const (
	EventTypeOrderCancellationRequested EventType = "OrderCancellationRequested"
	EventTypeInventoryRestocked         EventType = "InventoryRestocked"
)

func (e EventType) String() string {
	return string(e)
}

// Kafka configuration defaults for Inventory Service
const (
	DefaultConsumerGroup = "inventory-service-group"
	DefaultKafkaBroker   = "localhost:9092"
	TopicOrderEvents     = "order-events"
	TopicOrderDLQ        = "order-dlq"
)
