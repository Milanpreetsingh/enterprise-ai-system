package domain

// OrderStatus defines strongly-typed states in the order lifecycle state machine.
type OrderStatus string

const (
	OrderStatusPending             OrderStatus = "PENDING"
	OrderStatusPendingCancellation OrderStatus = "PENDING_CANCELLATION"
	OrderStatusCancelled           OrderStatus = "CANCELLED"
)

// String returns the string representation of OrderStatus.
func (s OrderStatus) String() string {
	return string(s)
}

// OutboxStatus defines state of outbox records awaiting publication.
type OutboxStatus string

const (
	OutboxStatusPending   OutboxStatus = "PENDING"
	OutboxStatusPublished OutboxStatus = "PUBLISHED"
	OutboxStatusFailed    OutboxStatus = "FAILED"
)

func (s OutboxStatus) String() string {
	return string(s)
}

// AggregateType defines the domain boundary for the outbox event.
type AggregateType string

const (
	AggregateTypeOrder AggregateType = "ORDER"
)

func (a AggregateType) String() string {
	return string(a)
}

// EventType defines lifecycle event types streamed across microservices.
type EventType string

const (
	EventTypeOrderCreated               EventType = "OrderCreated"
	EventTypeOrderCancellationRequested EventType = "OrderCancellationRequested"
	EventTypeInventoryRestocked         EventType = "InventoryRestocked"
)

func (e EventType) String() string {
	return string(e)
}

// Kafka Configuration Constants
const (
	DefaultKafkaBrokerAddress    = "localhost:9092"
	DefaultKafkaTopicOrderEvents = "order-events"
	DefaultKafkaTopicOrderRetry  = "order-retry-5m"
	DefaultKafkaTopicOrderDLQ    = "order-dlq"
	DefaultKafkaOrderGroupID     = "order-service-group"
)
