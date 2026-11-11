package outbox

import (
	"context"
	"log"
	"time"

	"enterprise-ai-system/services/order/internal/repository"

	"github.com/segmentio/kafka-go"
)

// Poller polls PostgreSQL for pending outbox events and publishes them to Kafka.
type Poller struct {
	repo         repository.OrderRepository
	writer       *kafka.Writer
	pollInterval time.Duration
	stopCh       chan struct{}
}

// NewPoller initializes an outbox poller with an idempotent, compressed Kafka writer.
func NewPoller(repo repository.OrderRepository, brokerAddress, topic string, pollInterval time.Duration) *Poller {
	writer := &kafka.Writer{
		Addr:         kafka.TCP(brokerAddress),
		Topic:        topic,
		Balancer:     &kafka.Hash{},
		RequiredAcks: kafka.RequireAll, // acks=all
		WriteTimeout: 10 * time.Second,
		Compression:  kafka.Snappy,
	}

	return &Poller{
		repo:         repo,
		writer:       writer,
		pollInterval: pollInterval,
		stopCh:       make(chan struct{}),
	}
}

// Start launches the background polling loop.
func (p *Poller) Start(ctx context.Context) {
	log.Printf("[Outbox Poller] Starting transactional outbox engine (polling every %v)...", p.pollInterval)
	ticker := time.NewTicker(p.pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Println("[Outbox Poller] Context cancelled, shutting down...")
			return
		case <-p.stopCh:
			log.Println("[Outbox Poller] Stop signal received, shutting down...")
			return
		case <-ticker.C:
			p.processPendingEvents(ctx)
		}
	}
}

func (p *Poller) processPendingEvents(ctx context.Context) {
	events, err := p.repo.GetPendingOutboxEvents(ctx, 20)
	if err != nil {
		log.Printf("[Outbox Poller] Error fetching pending outbox events: %v", err)
		return
	}

	if len(events) == 0 {
		return
	}

	log.Printf("[Outbox Poller] Found %d pending outbox events to publish...", len(events))

	for _, event := range events {
		msg := kafka.Message{
			Key:   []byte(event.AggregateID),
			Value: []byte(event.Payload),
			Time:  time.Now(),
			Headers: []kafka.Header{
				{Key: "event_id", Value: []byte(event.ID)},
				{Key: "event_type", Value: []byte(event.EventType)},
				{Key: "aggregate_type", Value: []byte(event.AggregateType)},
			},
		}

		publishCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		err := p.writer.WriteMessages(publishCtx, msg)
		cancel()

		if err != nil {
			log.Printf("[Outbox Poller] Failed to publish event %s (AggregateID: %s) to Kafka: %v", event.ID, event.AggregateID, err)
			if failErr := p.repo.MarkOutboxEventFailed(ctx, event.ID); failErr != nil {
				log.Printf("[Outbox Poller] Error marking event %s as failed: %v", event.ID, failErr)
			}
			continue
		}

		if err := p.repo.MarkOutboxEventPublished(ctx, event.ID); err != nil {
			log.Printf("[Outbox Poller] Error marking event %s as published: %v", event.ID, err)
		} else {
			log.Printf("[Outbox Poller] Successfully published event %s (Type: %s, AggregateID: %s) to Kafka", event.ID, event.EventType, event.AggregateID)
		}
	}
}

// Stop stops the poller loop and closes the Kafka writer.
func (p *Poller) Stop() error {
	close(p.stopCh)
	return p.writer.Close()
}
