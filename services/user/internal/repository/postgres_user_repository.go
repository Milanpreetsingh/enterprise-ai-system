package repository

import (
	"context"
	"errors"

	"gorm.io/gorm"
)

// postgresUserRepository is the concrete implementation of UserRepository using GORM.
type postgresUserRepository struct {
	db *gorm.DB
}

// NewPostgresUserRepository creates a new PostgreSQL implementation of UserRepository.
func NewPostgresUserRepository(db *gorm.DB) UserRepository {
	return &postgresUserRepository{db: db}
}

// Create inserts a new user into the database.
func (r *postgresUserRepository) Create(ctx context.Context, user *User) error {
	// WithContext ensures if the gRPC request is cancelled, the DB query cancels too!
	return r.db.WithContext(ctx).Create(user).Error
}

// GetByEmail fetches a user by their email. Used during Login.
func (r *postgresUserRepository) GetByEmail(ctx context.Context, email string) (*User, error) {
	var user User
	err := r.db.WithContext(ctx).Where("email = ?", email).First(&user).Error
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, errors.New("user not found")
		}
		return nil, err
	}
	return &user, nil
}

// GetByID fetches a user by their ID. Used by GetUser.
func (r *postgresUserRepository) GetByID(ctx context.Context, id string) (*User, error) {
	var user User
	err := r.db.WithContext(ctx).Where("id = ?", id).First(&user).Error
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, errors.New("user not found")
		}
		return nil, err
	}
	return &user, nil
}

// IncrementOrderCount increments the user's order count atomically in the DB.
func (r *postgresUserRepository) IncrementOrderCount(ctx context.Context, id string) error {
	return r.db.WithContext(ctx).Model(&User{}).Where("id = ?", id).Update("order_count", gorm.Expr("order_count + ?", 1)).Error
}

