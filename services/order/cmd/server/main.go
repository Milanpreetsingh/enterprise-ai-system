package main

import (
	"context"
	"log"
	"net"
	"os"
	"time"

	pb "enterprise-ai-system/proto-schemas/orderpb"
	userpb "enterprise-ai-system/proto-schemas/userpb"
	"enterprise-ai-system/services/order/internal/domain"
	"enterprise-ai-system/services/order/internal/handler"
	"enterprise-ai-system/services/order/internal/outbox"
	"enterprise-ai-system/services/order/internal/publisher"
	"enterprise-ai-system/services/order/internal/repository"
	"enterprise-ai-system/services/order/internal/service"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/reflection"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func main() {
	// 1. Connect to PostgreSQL
	// In local dev, fallback to localhost. Can be overridden with DB_DSN environment variable.
	dsn := os.Getenv("DB_DSN")
	if dsn == "" {
		dsn = "host=localhost user=postgres password=postgres dbname=postgres port=5432 sslmode=disable TimeZone=UTC"
	}

	var db *gorm.DB
	var err error

	// Retry loop: wait for the database container or service to be fully ready
	for i := 0; i < 5; i++ {
		db, err = gorm.Open(postgres.Open(dsn), &gorm.Config{})
		if err == nil {
			break
		}
		log.Printf("Database connection failed, retrying in 2 seconds... (%v)", err)
		time.Sleep(2 * time.Second)
	}

	if err != nil {
		log.Fatalf("Fatal: failed to connect to database: %v", err)
	}

	log.Println("Order Service successfully connected to PostgreSQL!")

	// 2. Run Auto-Migrations
	log.Println("Running database migrations for Order Service...")
	if err := db.AutoMigrate(&repository.Order{}, &repository.OutboxEvent{}); err != nil {
		log.Fatalf("Failed to auto-migrate database: %v", err)
	}

	// 3. Connect to User Service via gRPC
	userServiceAddr := os.Getenv("USER_SERVICE_ADDR")
	if userServiceAddr == "" {
		userServiceAddr = "localhost:50051"
	}

	log.Printf("Order Service connecting to User Service at %s...", userServiceAddr)
	userConn, err := grpc.NewClient(userServiceAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("failed to connect to user service: %v", err)
	}
	defer userConn.Close()

	userClient := userpb.NewUserServiceClient(userConn)

	// 4. Initialize Kafka Event Publisher
	kafkaBrokers := os.Getenv("KAFKA_BROKERS")
	if kafkaBrokers == "" {
		kafkaBrokers = domain.DefaultKafkaBrokerAddress
	}
	kafkaTopic := os.Getenv("KAFKA_ORDER_TOPIC")
	if kafkaTopic == "" {
		kafkaTopic = domain.DefaultKafkaTopicOrderEvents
	}

	log.Printf("Initializing Kafka Publisher on topic '%s' (brokers: %s)...", kafkaTopic, kafkaBrokers)
	orderPublisher := publisher.NewKafkaOrderPublisher(kafkaBrokers, kafkaTopic)
	defer func() {
		log.Println("Closing Kafka Publisher...")
		if err := orderPublisher.Close(); err != nil {
			log.Printf("Error closing Kafka Publisher: %v", err)
		}
	}()

	// 5. Initialize Repositories
	orderRepo := repository.NewPostgresOrderRepository(db)

	// 5b. Start Transactional Outbox Poller (Async Worker)
	outboxCtx, cancelOutbox := context.WithCancel(context.Background())
	defer cancelOutbox()
	outboxPoller := outbox.NewPoller(orderRepo, kafkaBrokers, kafkaTopic, 500*time.Millisecond)
	go outboxPoller.Start(outboxCtx)
	defer func() {
		if err := outboxPoller.Stop(); err != nil {
			log.Printf("Error stopping Outbox Poller: %v", err)
		}
	}()

	// 6. Initialize Services (injecting repository, user gRPC client, and Kafka publisher)
	orderService := service.NewOrderService(orderRepo, userClient, orderPublisher)

	// 7. Initialize Handlers
	orderHandler := handler.NewOrderHandler(orderService)

	// 8. Start TCP Listener
	port := os.Getenv("PORT")
	if port == "" {
		port = "50052"
	}
	lis, err := net.Listen("tcp", ":"+port)
	if err != nil {
		log.Fatalf("failed to listen on port %s: %v", port, err)
	}

	// 9. Create the gRPC server and register the handler
	s := grpc.NewServer()
	pb.RegisterOrderServiceServer(s, orderHandler)
	reflection.Register(s)

	log.Printf("Order Service is running and listening at %v", lis.Addr())
	if err := s.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}
