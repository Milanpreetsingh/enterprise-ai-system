package repository

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"enterprise-ai-system/services/order/internal/domain"

	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// postgresOrderRepository is the concrete implementation of OrderRepository using GORM.
type postgresOrderRepository struct {
	db *gorm.DB
}

// NewPostgresOrderRepository creates a new PostgreSQL implementation of OrderRepository.
func NewPostgresOrderRepository(db *gorm.DB) OrderRepository {
	return &postgresOrderRepository{db: db}
}

// Create inserts a new order into the database.
func (r *postgresOrderRepository) Create(ctx context.Context, order *Order) error {
	return r.db.WithContext(ctx).Create(order).Error
}

// GetByID fetches an order by its ID.
func (r *postgresOrderRepository) GetByID(ctx context.Context, id string) (*Order, error) {
	var order Order
	err := r.db.WithContext(ctx).Where("id = ?", id).First(&order).Error
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, errors.New("order not found")
		}
		return nil, err
	}
	return &order, nil
}

// UpdateStatus updates the status of an order by its ID.
func (r *postgresOrderRepository) UpdateStatus(ctx context.Context, id string, status string) error {
	res := r.db.WithContext(ctx).Model(&Order{}).Where("id = ?", id).Update("status", status)
	if res.Error != nil {
		return res.Error
	}
	if res.RowsAffected == 0 {
		return errors.New("order not found")
	}
	return nil
}

// RequestCancellationTx performs the Two-Phase SAGA initiation and writes to the Outbox in ONE atomic ACID transaction.
func (r *postgresOrderRepository) RequestCancellationTx(ctx context.Context, id, reason string) (*Order, *OutboxEvent, error) {
	var order Order
	var outboxEvent OutboxEvent

	err := r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		// 1. Fetch order with row-level lock (FOR UPDATE)
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id = ?", id).First(&order).Error; err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				return errors.New("order not found")
			}
			return err
		}

		// Idempotent check
		if order.Status == domain.OrderStatusCancelled.String() {
			return nil
		}
		if order.Status == domain.OrderStatusPendingCancellation.String() {
			return nil
		}

		// 2. Transition status to PENDING_CANCELLATION
		order.Status = domain.OrderStatusPendingCancellation.String()
		if err := tx.Save(&order).Error; err != nil {
			return err
		}

		// 3. Construct Outbox event payload
		eventID := uuid.New().String()
		payloadData := map[string]interface{}{
			"event_id":     eventID,
			"order_id":     order.ID,
			"user_id":      order.UserID,
			"product_id":   order.ProductID,
			"quantity":     order.Quantity,
			"reason":       reason,
			"timestamp":    time.Now().UTC().Format(time.RFC3339),
		}
		payloadBytes, err := json.Marshal(payloadData)
		if err != nil {
			return err
		}

		outboxEvent = OutboxEvent{
			AggregateType: domain.AggregateTypeOrder.String(),
			AggregateID:   order.ID,
			EventType:     domain.EventTypeOrderCancellationRequested.String(),
			Payload:       string(payloadBytes),
			Status:        domain.OutboxStatusPending.String(),
			RetryCount:    0,
		}

		// 4. Insert into outbox_events in the SAME transaction
		if err := tx.Create(&outboxEvent).Error; err != nil {
			return err
		}

		return nil
	})

	if err != nil {
		return nil, nil, err
	}
	return &order, &outboxEvent, nil
}

// FinalizeCancellation confirms order cancellation once inventory restock succeeds.
func (r *postgresOrderRepository) FinalizeCancellation(ctx context.Context, id string) error {
	return r.UpdateStatus(ctx, id, domain.OrderStatusCancelled.String())
}

// RejectCancellation executes compensating transaction to revert order back to ACTIVE/PENDING.
func (r *postgresOrderRepository) RejectCancellation(ctx context.Context, id, reason string) error {
	return r.UpdateStatus(ctx, id, domain.OrderStatusPending.String())
}

// GetPendingOutboxEvents retrieves pending outbox events to publish to Kafka.
func (r *postgresOrderRepository) GetPendingOutboxEvents(ctx context.Context, limit int) ([]OutboxEvent, error) {
	var events []OutboxEvent
	err := r.db.WithContext(ctx).
		Where("status = ?", domain.OutboxStatusPending.String()).
		Order("created_at ASC").
		Limit(limit).
		Find(&events).Error
	return events, err
}

// MarkOutboxEventPublished marks an outbox event as successfully published.
func (r *postgresOrderRepository) MarkOutboxEventPublished(ctx context.Context, id string) error {
	now := time.Now().UTC()
	return r.db.WithContext(ctx).Model(&OutboxEvent{}).
		Where("id = ?", id).
		Updates(map[string]interface{}{
			"status":       domain.OutboxStatusPublished.String(),
			"published_at": &now,
		}).Error
}

// MarkOutboxEventFailed increments retry count and marks as FAILED if retry limit exceeded.
func (r *postgresOrderRepository) MarkOutboxEventFailed(ctx context.Context, id string) error {
	return r.db.WithContext(ctx).Model(&OutboxEvent{}).
		Where("id = ?", id).
		Updates(map[string]interface{}{
			"retry_count": gorm.Expr("retry_count + 1"),
			"status":      gorm.Expr("CASE WHEN retry_count + 1 >= 5 THEN ? ELSE ? END", domain.OutboxStatusFailed.String(), domain.OutboxStatusPending.String()),
		}).Error
}
