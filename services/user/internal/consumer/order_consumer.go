package consumer

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"enterprise-ai-system/services/user/internal/repository"

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

// OrderConsumer processes order events asynchronously from Kafka.
type OrderConsumer struct {
	reader   *kafka.Reader
	userRepo repository.UserRepository
}

// NewOrderConsumer instantiates an OrderConsumer.
func NewOrderConsumer(brokerAddress, topic, groupID string, userRepo repository.UserRepository) *OrderConsumer {
	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:   []string{brokerAddress},
		Topic:     topic,
		GroupID:   groupID, // Join consumer group
		MinBytes:  10e3,    // 10KB
		MaxBytes:  10e6,    // 10MB
		MaxWait:   1 * time.Second,
	})

	return &OrderConsumer{
		reader:   reader,
		userRepo: userRepo,
	}
}

// Start runs the message processing loop in a blocking call (run in a goroutine).
func (c *OrderConsumer) Start(ctx context.Context) {
	log.Printf("[Kafka Consumer] Starting listener on topic '%s' (Group: '%s')...", c.reader.Config().Topic, c.reader.Config().GroupID)

	for {
		select {
		case <-ctx.Done():
			log.Println("[Kafka Consumer] Shutting down message loop...")
			return
		default:
			// 1. Fetch the message from Kafka (At-Least-Once: Offset NOT committed yet)
			msg, err := c.reader.FetchMessage(ctx)
			if err != nil {
				if ctx.Err() != nil {
					return
				}
				log.Printf("[Kafka Consumer] Error fetching message: %v", err)
				time.Sleep(1 * time.Second)
				continue
			}

			log.Printf("[Kafka Consumer] Fetched message from Partition %d at Offset %d (Key: %s)", msg.Partition, msg.Offset, string(msg.Key))

			// 2. Deserialize payload
			var event OrderCreatedEvent
			if err := json.Unmarshal(msg.Value, &event); err != nil {
				log.Printf("[Kafka Consumer] Parse failed: %v. Message skipped.", err)
				// Commit to skip poison pill message
				if commitErr := c.reader.CommitMessages(ctx, msg); commitErr != nil {
					log.Printf("[Kafka Consumer] Failed to commit offset for skipped message: %v", commitErr)
				}
				continue
			}

			log.Printf("[Kafka Consumer] Processing event. UserID: %s, OrderID: %s", event.UserID, event.OrderID)

			// 3. Process DB Action: Increment user's order stats atomically
			err = c.userRepo.IncrementOrderCount(ctx, event.UserID)
			if err != nil {
				log.Printf("[Kafka Consumer] Database update failed: %v. Event will retry.", err)
				// Do NOT commit the offset, letting it retry or wait for rebalance
				time.Sleep(2 * time.Second)
				continue
			}

			// 4. Commit offset to Kafka only after successful processing
			if err := c.reader.CommitMessages(ctx, msg); err != nil {
				log.Printf("[Kafka Consumer] Failed to commit message offset: %v", err)
				continue
			}

			log.Printf("[Kafka Consumer] Successfully processed event. Committed offset %d.", msg.Offset)
		}
	}
}

// Close gracefully closes the Kafka reader.
func (c *OrderConsumer) Close() error {
	return c.reader.Close()
}
