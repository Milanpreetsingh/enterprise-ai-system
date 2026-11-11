package service

import (
	"context"
	"errors"
	"log"

	userpb "enterprise-ai-system/proto-schemas/userpb"
	"enterprise-ai-system/services/order/internal/domain"
	"enterprise-ai-system/services/order/internal/publisher"
	"enterprise-ai-system/services/order/internal/repository"
)

// OrderService defines the business logic operations for orders.
type OrderService interface {
	CreateOrder(ctx context.Context, userID, productID string, quantity int32) (*repository.Order, error)
	GetOrder(ctx context.Context, id string) (*repository.Order, error)
	CancelOrder(ctx context.Context, id, reason string) (*repository.Order, error)
}

type orderService struct {
	orderRepo      repository.OrderRepository
	userClient     userpb.UserServiceClient
	orderPublisher publisher.OrderEventPublisher
}

// NewOrderService creates a new concrete implementation of OrderService.
func NewOrderService(
	orderRepo repository.OrderRepository,
	userClient userpb.UserServiceClient,
	orderPublisher publisher.OrderEventPublisher,
) OrderService {
	return &orderService{
		orderRepo:      orderRepo,
		userClient:     userClient,
		orderPublisher: orderPublisher,
	}
}

// CreateOrder registers a new order in the database after validating the user exists.
func (s *orderService) CreateOrder(ctx context.Context, userID, productID string, quantity int32) (*repository.Order, error) {
	if userID == "" || productID == "" {
		return nil, errors.New("missing user_id or product_id")
	}
	if quantity <= 0 {
		return nil, errors.New("quantity must be greater than zero")
	}

	// Verify that the user exists by calling the User Service via gRPC
	_, err := s.userClient.GetUser(ctx, &userpb.GetUserRequest{Id: userID})
	if err != nil {
		return nil, errors.New("failed to verify user: " + err.Error())
	}

	order := &repository.Order{
		UserID:    userID,
		ProductID: productID,
		Quantity:  quantity,
		Status:    domain.OrderStatusPending.String(),
	}

	if err := s.orderRepo.Create(ctx, order); err != nil {
		return nil, err
	}

	// Publish OrderCreated event asynchronously to Kafka
	if err := s.orderPublisher.PublishOrderCreated(ctx, order.ID, order.UserID, order.ProductID, order.Quantity); err != nil {
		// Log the error but do not fail the HTTP request since DB persistence was successful
		log.Printf("[Order Service] Warning: failed to publish order created event to Kafka: %v", err)
	}

	return order, nil
}

// GetOrder retrieves an order by its ID.
func (s *orderService) GetOrder(ctx context.Context, id string) (*repository.Order, error) {
	if id == "" {
		return nil, errors.New("invalid order ID")
	}
	return s.orderRepo.GetByID(ctx, id)
}

// CancelOrder validates that the order exists, atomically updates its status to PENDING_CANCELLATION
// and registers the event in the outbox table via ONE ACID transaction.
func (s *orderService) CancelOrder(ctx context.Context, id, reason string) (*repository.Order, error) {
	if id == "" {
		return nil, errors.New("invalid order ID")
	}

	order, _, err := s.orderRepo.RequestCancellationTx(ctx, id, reason)
	if err != nil {
		return nil, err
	}

	log.Printf("[Order Service - Outbox SAGA] Order %s cancellation requested. Status: %s. Reason: %s", id, order.Status, reason)
	return order, nil
}
