package repository

import (
	"context"
	"time"
)

// User represents the database schema for a user.
// We use GORM struct tags to define the database constraints.
type User struct {
	ID         string    `gorm:"type:uuid;primaryKey;default:gen_random_uuid()"`
	Email      string    `gorm:"uniqueIndex;not null"`
	Password   string    `gorm:"not null"` // Hashed password, NEVER plain text
	FullName   string    `gorm:"not null"`
	Role       string    `gorm:"type:varchar(32);not null;default:'customer'"` // customer, support_agent, admin
	OrderCount int       `gorm:"not null;default:0"` // Tracks total orders processed asynchronously
	CreatedAt  time.Time `gorm:"autoCreateTime"`
	UpdatedAt  time.Time `gorm:"autoUpdateTime"`
}

// UserRepository defines the contract (interface) for user data persistence.
// By using an interface, we can easily mock the database for unit testing!
type UserRepository interface {
	Create(ctx context.Context, user *User) error
	GetByEmail(ctx context.Context, email string) (*User, error)
	GetByID(ctx context.Context, id string) (*User, error)
	IncrementOrderCount(ctx context.Context, id string) error
}
