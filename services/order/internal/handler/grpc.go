package handler

import (
	"context"
	"log"
	"time"

	pb "enterprise-ai-system/proto-schemas/orderpb"
	"enterprise-ai-system/services/order/internal/service"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// OrderHandler implements the gRPC OrderServiceServer interface.
type OrderHandler struct {
	pb.UnimplementedOrderServiceServer
	orderService service.OrderService
}

// NewOrderHandler creates a new instance of OrderHandler.
func NewOrderHandler(orderService service.OrderService) *OrderHandler {
	return &OrderHandler{
		orderService: orderService,
	}
}

// CreateOrder handles creating a new order.
func (h *OrderHandler) CreateOrder(ctx context.Context, req *pb.CreateOrderRequest) (*pb.OrderResponse, error) {
	log.Printf("Received CreateOrder request for UserID: %s, ProductID: %s", req.GetUserId(), req.GetProductId())

	order, err := h.orderService.CreateOrder(ctx, req.GetUserId(), req.GetProductId(), req.GetQuantity())
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "failed to create order: %v", err)
	}

	return &pb.OrderResponse{
		Id:        order.ID,
		UserId:    order.UserID,
		ProductId: order.ProductID,
		Quantity:  order.Quantity,
		Status:    order.Status,
		CreatedAt: order.CreatedAt.Format(time.RFC3339),
	}, nil
}

// GetOrder handles retrieving an existing order.
func (h *OrderHandler) GetOrder(ctx context.Context, req *pb.GetOrderRequest) (*pb.OrderResponse, error) {
	log.Printf("Received GetOrder request for ID: %s", req.GetId())

	order, err := h.orderService.GetOrder(ctx, req.GetId())
	if err != nil {
		return nil, status.Errorf(codes.NotFound, "order not found: %v", err)
	}

	return &pb.OrderResponse{
		Id:        order.ID,
		UserId:    order.UserID,
		ProductId: order.ProductID,
		Quantity:  order.Quantity,
		Status:    order.Status,
		CreatedAt: order.CreatedAt.Format(time.RFC3339),
	}, nil
}

// CancelOrder handles cancelling an order and marking it CANCELLED in the database.
func (h *OrderHandler) CancelOrder(ctx context.Context, req *pb.CancelOrderRequest) (*pb.OrderResponse, error) {
	log.Printf("Received CancelOrder request for ID: %s, Reason: %s", req.GetId(), req.GetReason())

	order, err := h.orderService.CancelOrder(ctx, req.GetId(), req.GetReason())
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to cancel order: %v", err)
	}

	return &pb.OrderResponse{
		Id:        order.ID,
		UserId:    order.UserID,
		ProductId: order.ProductID,
		Quantity:  order.Quantity,
		Status:    order.Status,
		CreatedAt: order.CreatedAt.Format(time.RFC3339),
	}, nil
}
