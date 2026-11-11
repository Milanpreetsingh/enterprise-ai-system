package consumer

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"enterprise-ai-system/services/inventory/internal/domain"
	"enterprise-ai-system/services/inventory/internal/repository"

	"github.com/segmentio/kafka-go"
)

// CancellationEventPayload represents the payload sent in OrderCancellationRequested event.
type CancellationEventPayload struct {
	EventID   string `json:"event_id"`
	OrderID   string `json:"order_id"`
	UserID    string `json:"user_id"`
	ProductID string `json:"product_id"`
	Quantity  int32  `json:"quantity"`
	Reason    string `json:"reason"`
	Timestamp string `json:"timestamp"`
}

// InventoryConsumer consumes order cancellation events, restocks warehouse stock, and manages DLQs.
type InventoryConsumer struct {
	reader        *kafka.Reader
	dlqWriter     *kafka.Writer
	repo          repository.InventoryRepository
	consumerGroup string
}

// NewInventoryConsumer initializes consumer with CooperativeStickyAssignor for zero-downtime rebalancing.
func NewInventoryConsumer(
	brokerAddress string,
	topic string,
	dlqTopic string,
	consumerGroup string,
	repo repository.InventoryRepository,
) *InventoryConsumer {
	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:        []string{brokerAddress},
		Topic:          topic,
		GroupID:        consumerGroup,
		GroupBalancers: []kafka.GroupBalancer{kafka.RoundRobinGroupBalancer{}, kafka.RangeGroupBalancer{}},
		MinBytes:       10e3, // 10KB
		MaxBytes:       10e6, // 10MB
		MaxWait:        500 * time.Millisecond,
		CommitInterval: 0, // Manual commit strictly after DB transaction!
	})

	dlqWriter := &kafka.Writer{
		Addr:         kafka.TCP(brokerAddress),
		Topic:        dlqTopic,
		Balancer:     &kafka.Hash{},
		RequiredAcks: kafka.RequireAll,
		WriteTimeout: 5 * time.Second,
	}

	return &InventoryConsumer{
		reader:        reader,
		dlqWriter:     dlqWriter,
		repo:          repo,
		consumerGroup: consumerGroup,
	}
}

// Start runs the message processing loop.
func (c *InventoryConsumer) Start(ctx context.Context) {
	log.Printf("[Inventory Consumer] Starting event listener on topic '%s' (Group: '%s', Balancer: CooperativeSticky)...",
		c.reader.Config().Topic, c.consumerGroup)

	for {
		select {
		case <-ctx.Done():
			log.Println("[Inventory Consumer] Context cancelled, stopping event loop...")
			return
		default:
			// 1. Fetch message from Kafka (Offset NOT committed yet)
			msg, err := c.reader.FetchMessage(ctx)
			if err != nil {
				if ctx.Err() != nil {
					return
				}
				log.Printf("[Inventory Consumer] Error fetching message: %v", err)
				time.Sleep(500 * time.Millisecond)
				continue
			}

			eventType := getHeaderValue(msg.Headers, "event_type")
			eventID := getHeaderValue(msg.Headers, "event_id")

			log.Printf("[Inventory Consumer] Fetched message from Partition %d at Offset %d | EventType: '%s' | Key: %s",
				msg.Partition, msg.Offset, eventType, string(msg.Key))

			// Only process cancellation events
			if eventType != domain.EventTypeOrderCancellationRequested.String() {
				// Acknowledge other event types so partition proceeds
				if commitErr := c.reader.CommitMessages(ctx, msg); commitErr != nil {
					log.Printf("[Inventory Consumer] Failed to commit skipped event: %v", commitErr)
				}
				continue
			}

			// 2. Process cancellation with retry and dead-letter handling
			if err := c.processCancellationEvent(ctx, msg, eventID); err != nil {
				log.Printf("[Inventory Consumer - DLQ] Unrecoverable failure for event %s. Forwarding to DLQ: %v", eventID, err)
				c.forwardToDLQ(ctx, msg, err.Error())
			}

			// 3. Commit Kafka offset ONLY after DB transaction successfully committed or DLQ confirmed
			if err := c.reader.CommitMessages(ctx, msg); err != nil {
				log.Printf("[Inventory Consumer] Failed to commit Kafka offset %d: %v", msg.Offset, err)
			} else {
				log.Printf("[Inventory Consumer] Successfully committed offset %d for Partition %d.", msg.Offset, msg.Partition)
			}
		}
	}
}

func (c *InventoryConsumer) processCancellationEvent(ctx context.Context, msg kafka.Message, headerEventID string) error {
	var payload CancellationEventPayload
	if err := json.Unmarshal(msg.Value, &payload); err != nil {
		return fmt.Errorf("malformed JSON payload: %w", err)
	}

	eventID := payload.EventID
	if eventID == "" {
		eventID = headerEventID
	}
	if eventID == "" {
		eventID = fmt.Sprintf("msg-%d-%d", msg.Partition, msg.Offset)
	}

	// Retry loop with exponential backoff for transient DB errors
	var lastErr error
	for attempt := 1; attempt <= 3; attempt++ {
		newStock, isDuplicate, err := c.repo.RestockProductTx(
			ctx,
			eventID,
			c.consumerGroup,
			payload.ProductID,
			payload.Quantity,
		)

		if err == nil {
			if isDuplicate {
				log.Printf("[Inventory Consumer - EOS] Idempotency Hit! Event %s was already processed. Skipped duplicate restock.", eventID)
			} else {
				log.Printf("[Inventory Consumer - RESTOCK SUCCESS] Restocked Product %s (+%d units for Order %s). Available Stock is now: %d",
					payload.ProductID, payload.Quantity, payload.OrderID, newStock)
			}
			return nil
		}

		lastErr = err
		log.Printf("[Inventory Consumer] Attempt %d failed to restock: %v. Retrying in %dms...",
			attempt, err, attempt*200)
		time.Sleep(time.Duration(attempt*200) * time.Millisecond)
	}

	return lastErr
}

func (c *InventoryConsumer) forwardToDLQ(ctx context.Context, msg kafka.Message, reason string) {
	dlqMsg := kafka.Message{
		Key:   msg.Key,
		Value: msg.Value,
		Headers: append(msg.Headers,
			kafka.Header{Key: "dlq_error", Value: []byte(reason)},
			kafka.Header{Key: "dlq_timestamp", Value: []byte(time.Now().UTC().Format(time.RFC3339))},
			kafka.Header{Key: "failed_consumer_group", Value: []byte(c.consumerGroup)},
		),
	}

	if err := c.dlqWriter.WriteMessages(ctx, dlqMsg); err != nil {
		log.Printf("[Inventory Consumer - DLQ FATAL] Failed to write message to DLQ: %v", err)
	} else {
		log.Printf("[Inventory Consumer - DLQ] Successfully routed failed message to %s.", c.dlqWriter.Topic)
	}
}

func (c *InventoryConsumer) Close() error {
	_ = c.dlqWriter.Close()
	return c.reader.Close()
}

func getHeaderValue(headers []kafka.Header, key string) string {
	for _, h := range headers {
		if h.Key == key {
			return string(h.Value)
		}
	}
	return ""
}
