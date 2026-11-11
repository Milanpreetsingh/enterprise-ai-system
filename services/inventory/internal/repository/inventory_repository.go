package repository

import (
	"context"
	"errors"
	"log"
	"time"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// Inventory represents product stock levels in the warehouse.
type Inventory struct {
	ProductID        string    `gorm:"type:uuid;primaryKey"`
	ProductName      string    `gorm:"type:varchar(255);not null"`
	StockQuantity    int32     `gorm:"not null;default:100"`
	ReservedQuantity int32     `gorm:"not null;default:0"`
	UpdatedAt        time.Time `gorm:"autoUpdateTime"`
}

func (Inventory) TableName() string {
	return "inventory"
}

// ProcessedEvent represents the idempotent consumer inbox ledger.
type ProcessedEvent struct {
	EventID       string    `gorm:"type:varchar(64);primaryKey"`
	ConsumerGroup string    `gorm:"type:varchar(64);primaryKey"`
	ProcessedAt   time.Time `gorm:"autoCreateTime"`
}

func (ProcessedEvent) TableName() string {
	return "processed_events"
}

// InventoryRepository provides operations for inventory ledger and consumer idempotency.
type InventoryRepository interface {
	RestockProductTx(ctx context.Context, eventID, consumerGroup, productID string, quantity int32) (newStock int32, isDuplicate bool, err error)
	GetStock(ctx context.Context, productID string) (*Inventory, error)
}

type postgresInventoryRepository struct {
	db *gorm.DB
}

func NewPostgresInventoryRepository(db *gorm.DB) InventoryRepository {
	return &postgresInventoryRepository{db: db}
}

// RestockProductTx executes an idempotent restock update within an ACID database transaction.
func (r *postgresInventoryRepository) RestockProductTx(
	ctx context.Context,
	eventID, consumerGroup, productID string,
	quantity int32,
) (int32, bool, error) {
	var newStock int32
	var isDuplicate bool

	err := r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		// 1. Check idempotency: Have we already processed this event_id in this consumer group?
		var processed ProcessedEvent
		checkErr := tx.Where("event_id = ? AND consumer_group = ?", eventID, consumerGroup).First(&processed).Error
		if checkErr == nil {
			log.Printf("[Inventory Repo - Idempotency] Event %s already processed by group %s. Skipping restock.", eventID, consumerGroup)
			isDuplicate = true
			return nil
		}
		if !errors.Is(checkErr, gorm.ErrRecordNotFound) {
			return checkErr
		}

		// 2. Fetch inventory record with row-level lock (FOR UPDATE)
		var item Inventory
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("product_id = ?", productID).First(&item).Error; err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				// Initialize a default record if item doesn't exist yet
				item = Inventory{
					ProductID:        productID,
					ProductName:      "Standard Catalog Item",
					StockQuantity:    100 + quantity,
					ReservedQuantity: 0,
				}
				if createErr := tx.Create(&item).Error; createErr != nil {
					return createErr
				}
				newStock = item.StockQuantity
			} else {
				return err
			}
		} else {
			// Increment available stock and decrement reserved
			item.StockQuantity += quantity
			if item.ReservedQuantity >= quantity {
				item.ReservedQuantity -= quantity
			} else {
				item.ReservedQuantity = 0
			}

			if saveErr := tx.Save(&item).Error; saveErr != nil {
				return saveErr
			}
			newStock = item.StockQuantity
		}

		// 3. Record event in processed_events ledger inside the SAME transaction
		record := ProcessedEvent{
			EventID:       eventID,
			ConsumerGroup: consumerGroup,
			ProcessedAt:   time.Now().UTC(),
		}
		if err := tx.Create(&record).Error; err != nil {
			return err
		}

		return nil
	})

	if err != nil {
		return 0, false, err
	}
	return newStock, isDuplicate, nil
}

// GetStock returns current stock details for a product.
func (r *postgresInventoryRepository) GetStock(ctx context.Context, productID string) (*Inventory, error) {
	var item Inventory
	err := r.db.WithContext(ctx).Where("product_id = ?", productID).First(&item).Error
	if err != nil {
		return nil, err
	}
	return &item, nil
}
