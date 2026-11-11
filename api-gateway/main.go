package main

import (
	"log"
	"os"

	"enterprise-ai-system/api-gateway/handler"
	"enterprise-ai-system/api-gateway/middleware"
	aipb "enterprise-ai-system/proto-schemas/aipb"
	orderpb "enterprise-ai-system/proto-schemas/orderpb"
	userpb "enterprise-ai-system/proto-schemas/userpb"

	"github.com/gin-gonic/gin"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func main() {
	// 1. Resolve microservice address configurations
	userServiceAddr := os.Getenv("USER_SERVICE_ADDR")
	if userServiceAddr == "" {
		userServiceAddr = "localhost:50051"
	}

	orderServiceAddr := os.Getenv("ORDER_SERVICE_ADDR")
	if orderServiceAddr == "" {
		orderServiceAddr = "localhost:50052"
	}

	// 2. Establish gRPC Client connections
	aiServiceAddr := getEnv("AI_SERVICE_ADDR", "localhost:50053")

	log.Printf("Connecting to User Service at %s...", userServiceAddr)
	userConn, err := grpc.NewClient(userServiceAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("failed to connect to user service: %v", err)
	}
	defer userConn.Close()
	userClient := userpb.NewUserServiceClient(userConn)

	log.Printf("Connecting to Order Service at %s...", orderServiceAddr)
	orderConn, err := grpc.NewClient(orderServiceAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("failed to connect to order service: %v", err)
	}
	defer orderConn.Close()
	orderClient := orderpb.NewOrderServiceClient(orderConn)

	log.Printf("Connecting to AI Service at %s...", aiServiceAddr)
	aiConn, err := grpc.NewClient(aiServiceAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Printf("Warning: failed to connect to AI gRPC service: %v. Streaming will be unavailable.", err)
	}
	defer aiConn.Close()
	aiClient := aipb.NewAIServiceClient(aiConn)

	aiHTTPURL := getEnv("AI_HTTP_URL", "http://localhost:8000")

	// 3. Initialize Redis Client for Distributed Rate Limiting & Token Budgeting
	rdb := middleware.InitRedisClient()

	// 4. Initialize Route Handlers
	gatewayHandler := handler.NewGatewayHandler(userClient, orderClient, aiClient, aiHTTPURL, rdb)

	// 5. Configure HTTP Server
	r := gin.Default()

	// CORS Middleware to allow requests from frontend (e.g. localhost:3000)
	r.Use(func(c *gin.Context) {
		origin := c.Request.Header.Get("Origin")
		if origin != "" {
			c.Writer.Header().Set("Access-Control-Allow-Origin", origin)
		} else {
			c.Writer.Header().Set("Access-Control-Allow-Origin", "*")
		}
		c.Writer.Header().Set("Access-Control-Allow-Credentials", "true")
		c.Writer.Header().Set("Access-Control-Allow-Headers", "Content-Type, Content-Length, Accept-Encoding, X-CSRF-Token, Authorization, accept, origin, Cache-Control, X-Requested-With")
		c.Writer.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS, GET, PUT, DELETE, PATCH")

		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}

		c.Next()
	})

	// Global Sliding-Window Rate Limiter (30 requests/minute per IP/User)
	r.Use(middleware.RateLimiterMiddleware(rdb, 30))

	// 6. Register Routes
	v1 := r.Group("/api/v1")
	{
		// Authentication Routes (Public)
		auth := v1.Group("/auth")
		{
			auth.POST("/signup", gatewayHandler.Signup)
			auth.POST("/login", gatewayHandler.Login)
			auth.POST("/refresh", gatewayHandler.Refresh)
		}

		// Order Routes (Mandatory JWT Authentication & IDOR Verification)
		orders := v1.Group("/orders")
		orders.Use(middleware.JWTAuthMiddleware())
		{
			orders.POST("", gatewayHandler.CreateOrder)
			orders.GET("/:id", gatewayHandler.GetOrder)
		}

		// Model Context Protocol (MCP) Server Endpoint (Internal / Agent Access)
		v1.POST("/mcp", gatewayHandler.HandleMCP)

		// AI Chat Endpoints (Mandatory JWT Authentication & FinOps Token Budget: 10,000 tokens/day)
		v1.POST("/chat", middleware.JWTAuthMiddleware(), middleware.TokenBudgetMiddleware(rdb, 10000), gatewayHandler.Chat)
		v1.GET("/chat/stream", middleware.JWTAuthMiddleware(), middleware.TokenBudgetMiddleware(rdb, 10000), gatewayHandler.StreamChat)

		// Supervisor Approval Endpoint (Admin / Support Agent RBAC Only)
		v1.POST("/agent/approve", middleware.JWTAuthMiddleware(), middleware.RequireRole("admin", "support_agent"), gatewayHandler.Approve)

		// Knowledge Base RAG Management Endpoints (Public queries, Admin-Only Seeding)
		v1.GET("/rag/docs", gatewayHandler.ListKnowledgeDocs)
		v1.POST("/rag/query", gatewayHandler.QueryKnowledge)
		v1.POST("/rag/seed", middleware.JWTAuthMiddleware(), middleware.RequireRole("admin"), gatewayHandler.SeedKnowledge)
	}

	// 7. Start API Gateway Server
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("API Gateway is running on port %s...", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("failed to run gateway server: %v", err)
	}
}

func getEnv(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}
