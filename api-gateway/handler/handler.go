package handler

import (
	"context"
	"net/http"
	"time"

	aipb "enterprise-ai-system/proto-schemas/aipb"
	orderpb "enterprise-ai-system/proto-schemas/orderpb"
	userpb "enterprise-ai-system/proto-schemas/userpb"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

// GatewayHandler coordinates REST requests to downstream microservices and AI engine.
type GatewayHandler struct {
	userClient  userpb.UserServiceClient
	orderClient orderpb.OrderServiceClient
	aiClient    aipb.AIServiceClient
	aiHTTPURL   string
	httpClient  *http.Client
	rdb         *redis.Client
}

// NewGatewayHandler instantiates a GatewayHandler.
func NewGatewayHandler(
	userClient userpb.UserServiceClient,
	orderClient orderpb.OrderServiceClient,
	aiClient aipb.AIServiceClient,
	aiHTTPURL string,
	rdb *redis.Client,
) *GatewayHandler {
	if aiHTTPURL == "" {
		aiHTTPURL = "http://localhost:8000"
	}
	return &GatewayHandler{
		userClient:  userClient,
		orderClient: orderClient,
		aiClient:    aiClient,
		aiHTTPURL:   aiHTTPURL,
		httpClient:  &http.Client{Timeout: 90 * time.Second},
		rdb:         rdb,
	}
}

// SignupRequest defines input validations for registration.
type SignupRequest struct {
	Email    string `json:"email" binding:"required,email"`
	Password string `json:"password" binding:"required,min=6"`
	FullName string `json:"full_name" binding:"required"`
	Role     string `json:"role"` // Optional: customer (default), support_agent, admin
}

// Signup forwards user signup to User Service.
func (h *GatewayHandler) Signup(c *gin.Context) {
	var req SignupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	role := req.Role
	if role == "" {
		role = "customer"
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := h.userClient.CreateUser(ctx, &userpb.CreateUserRequest{
		Email:    req.Email,
		Password: req.Password,
		FullName: req.FullName,
		Role:     role,
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"id":        resp.GetId(),
		"email":     resp.GetEmail(),
		"full_name": resp.GetFullName(),
		"role":      resp.GetRole(),
	})
}

// LoginRequest defines input validation for login.
type LoginRequest struct {
	Email    string `json:"email" binding:"required,email"`
	Password string `json:"password" binding:"required"`
}

// Login forwards user credentials to User Service for token issuance.
func (h *GatewayHandler) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := h.userClient.LoginUser(ctx, &userpb.LoginUserRequest{
		Email:    req.Email,
		Password: req.Password,
	})
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"user": gin.H{
			"id":        resp.GetUser().GetId(),
			"email":     resp.GetUser().GetEmail(),
			"full_name": resp.GetUser().GetFullName(),
			"role":      resp.GetUser().GetRole(),
		},
		"access_token":  resp.GetAccessToken(),
		"refresh_token": resp.GetRefreshToken(),
	})
}

// RefreshRequest defines token refresh input.
type RefreshRequest struct {
	RefreshToken string `json:"refresh_token" binding:"required"`
}

// Refresh issues a new access token via User Service.
func (h *GatewayHandler) Refresh(c *gin.Context) {
	var req RefreshRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := h.userClient.RefreshToken(ctx, &userpb.RefreshTokenRequest{
		RefreshToken: req.RefreshToken,
	})
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"access_token": resp.GetAccessToken(),
	})
}

// CreateOrderRequest defines the input required to create an order.
type CreateOrderRequest struct {
	ProductID string `json:"product_id" binding:"required"`
	Quantity  int32  `json:"quantity" binding:"required,gt=0"`
}

// CreateOrder places a new order through the Order Service.
func (h *GatewayHandler) CreateOrder(c *gin.Context) {
	userIDVal, exists := c.Get("userID")
	if !exists {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "User context missing"})
		return
	}
	userID := userIDVal.(string)

	var req CreateOrderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := h.orderClient.CreateOrder(ctx, &orderpb.CreateOrderRequest{
		UserId:    userID,
		ProductId: req.ProductID,
		Quantity:  req.Quantity,
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"id":         resp.GetId(),
		"user_id":    resp.GetUserId(),
		"product_id": resp.GetProductId(),
		"quantity":   resp.GetQuantity(),
		"status":     resp.GetStatus(),
	})
}

// GetOrder fetches a single order context.
func (h *GatewayHandler) GetOrder(c *gin.Context) {
	orderID := c.Param("id")
	if orderID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Order ID is required"})
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := h.orderClient.GetOrder(ctx, &orderpb.GetOrderRequest{
		Id: orderID,
	})
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": err.Error()})
		return
	}

	// IDOR Protection: Customers may only view their own orders
	callerUserID := c.GetString("userID")
	callerRole := c.GetString("role")
	if callerRole != "admin" && callerRole != "support_agent" && resp.GetUserId() != callerUserID {
		c.JSON(http.StatusForbidden, gin.H{
			"error": "Forbidden: You are not authorized to view orders belonging to other accounts",
		})
		return
	}   

	c.JSON(http.StatusOK, gin.H{
		"id":         resp.GetId(),
		"user_id":    resp.GetUserId(),
		"product_id": resp.GetProductId(),
		"quantity":   resp.GetQuantity(),
		"status":     resp.GetStatus(),
	})
}
