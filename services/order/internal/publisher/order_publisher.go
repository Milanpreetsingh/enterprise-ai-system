package publisher

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"github.com/segmentio/kafka-go"
)

// OrderCreatedEvent defines the JSON schema for order creation event.
type OrderCreatedEvent struct {
	OrderID   string    `json:"order_id"`
	UserID    string    `json:"user_id"`
	ProductID string    `json:"product_id"`
	Quantity  int32     `json:"quantity"`
	Timestamp time.Time `json:"timestamp"`
}

// OrderEventPublisher defines the interface to publish order lifecycle events.
type OrderEventPublisher interface {
	PublishOrderCreated(ctx context.Context, orderID, userID, productID string, quantity int32) error
	Close() error
}

type kafkaOrderPublisher struct {
	writer *kafka.Writer
}

// NewKafkaOrderPublisher creates a concrete OrderEventPublisher using segmentio/kafka-go.
func NewKafkaOrderPublisher(brokerAddress, topic string) OrderEventPublisher {
	writer := &kafka.Writer{
		Addr:         kafka.TCP(brokerAddress),
		Topic:        topic,
		Balancer:     &kafka.Hash{},    // Hashes key to select partition, ensuring key ordering
		RequiredAcks: kafka.RequireAll, // require acks from all partition replicas (acks=all)
		WriteTimeout: 10 * time.Second,
	}

	return &kafkaOrderPublisher{
		writer: writer,
	}
}

// PublishOrderCreated publishes the OrderCreated event to Kafka.
func (p *kafkaOrderPublisher) PublishOrderCreated(ctx context.Context, orderID, userID, productID string, quantity int32) error {
	event := OrderCreatedEvent{
		OrderID:   orderID,
		UserID:    userID,
		ProductID: productID,
		Quantity:  quantity,
		Timestamp: time.Now(),
	}

	payload, err := json.Marshal(event)
	if err != nil {
		return err
	}

	log.Printf("[Kafka Producer] Publishing OrderCreated event for OrderID: %s, UserID: %s", orderID, userID)

	// We set Key = userID. All orders for the same user hash to the same partition,
	// maintaining sequential delivery order for that user.
	err = p.writer.WriteMessages(ctx, kafka.Message{
		Key:   []byte(userID),
		Value: payload,
	})
	if err != nil {
		log.Printf("[Kafka Producer] Failed to publish OrderCreated event: %v", err)
		return err
	}

	log.Printf("[Kafka Producer] Successfully published OrderCreated event for OrderID: %s", orderID)
	return nil
}

// Close gracefully closes the underlying Kafka writer.
func (p *kafkaOrderPublisher) Close() error {
	return p.writer.Close()
}
