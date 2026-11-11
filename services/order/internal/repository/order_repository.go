package repository

import (
	"context"
	"time"
)

// Order represents the database schema for an order.
type Order struct {
	ID        string    `gorm:"type:uuid;primaryKey;default:gen_random_uuid()"`
	UserID    string    `gorm:"type:uuid;not null"`
	ProductID string    `gorm:"type:uuid;not null"`
	Quantity  int32     `gorm:"not null"`
	Status    string    `gorm:"not null;default:'PENDING'"`
	CreatedAt time.Time `gorm:"autoCreateTime"`
	UpdatedAt time.Time `gorm:"autoUpdateTime"`
}

// OutboxEvent represents the transactional outbox schema for atomic event publishing.
type OutboxEvent struct {
	ID            string     `gorm:"type:uuid;primaryKey;default:gen_random_uuid()"`
	AggregateType string     `gorm:"type:varchar(64);not null"`
	AggregateID   string     `gorm:"type:varchar(64);not null"`
	EventType     string     `gorm:"type:varchar(64);not null"`
	Payload       string     `gorm:"type:jsonb;not null"`
	Status        string     `gorm:"type:varchar(32);not null;default:'PENDING'"`
	RetryCount    int        `gorm:"not null;default:0"`
	CreatedAt     time.Time  `gorm:"autoCreateTime"`
	PublishedAt   *time.Time `gorm:""`
}

func (OutboxEvent) TableName() string {
	return "outbox_events"
}

// OrderRepository defines the contract for order data persistence and outbox operations.
type OrderRepository interface {
	Create(ctx context.Context, order *Order) error
	GetByID(ctx context.Context, id string) (*Order, error)
	UpdateStatus(ctx context.Context, id string, status string) error

	// SAGA & Outbox Atomic Operations:
	RequestCancellationTx(ctx context.Context, id, reason string) (*Order, *OutboxEvent, error)
	FinalizeCancellation(ctx context.Context, id string) error
	RejectCancellation(ctx context.Context, id, reason string) error
	GetPendingOutboxEvents(ctx context.Context, limit int) ([]OutboxEvent, error)
	MarkOutboxEventPublished(ctx context.Context, id string) error
	MarkOutboxEventFailed(ctx context.Context, id string) error
}
