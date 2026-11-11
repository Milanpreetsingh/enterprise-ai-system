package main

import (
	"context"
	"log"
	"net"
	"os"
	"time"

	pb "enterprise-ai-system/proto-schemas/userpb"
	"enterprise-ai-system/services/user/internal/consumer"
	"enterprise-ai-system/services/user/internal/handler"
	"enterprise-ai-system/services/user/internal/repository"
	"enterprise-ai-system/services/user/internal/service"

	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func main() {
	// 1. Connect to PostgreSQL
	// In production, this would be loaded from an environment variable!
	dsn := os.Getenv("DB_DSN")
	if dsn == "" {
		dsn = "host=localhost user=postgres password=postgres dbname=postgres port=5432 sslmode=disable TimeZone=UTC"
	}
	
	var db *gorm.DB
	var err error
	
	// Retry loop: wait for the database container to be fully ready
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
	
	log.Println("Successfully connected to PostgreSQL!")

	// 2. Run Auto-Migrations
	// This automatically creates/updates the 'users' table based on our User struct
	log.Println("Running database migrations...")
	if err := db.AutoMigrate(&repository.User{}); err != nil {
		log.Fatalf("Failed to auto-migrate database: %v", err)
	}

	// 3. Initialize Repositories
	userRepo := repository.NewPostgresUserRepository(db)

	// 4. Initialize Kafka Consumer
	kafkaBrokers := os.Getenv("KAFKA_BROKERS")
	if kafkaBrokers == "" {
		kafkaBrokers = "localhost:9092"
	}
	kafkaTopic := os.Getenv("KAFKA_ORDER_TOPIC")
	if kafkaTopic == "" {
		kafkaTopic = "order-events"
	}
	kafkaGroup := os.Getenv("KAFKA_USER_GROUP")
	if kafkaGroup == "" {
		kafkaGroup = "user-service-group"
	}

	log.Printf("Initializing Kafka Consumer on topic '%s' (Group: '%s', Brokers: %s)...", kafkaTopic, kafkaGroup, kafkaBrokers)
	orderConsumer := consumer.NewOrderConsumer(kafkaBrokers, kafkaTopic, kafkaGroup, userRepo)
	defer func() {
		log.Println("Closing Kafka Consumer...")
		if err := orderConsumer.Close(); err != nil {
			log.Printf("Error closing Kafka Consumer: %v", err)
		}
	}()

	// Start background consumer loop
	consumerCtx, cancelConsumer := context.WithCancel(context.Background())
	defer cancelConsumer()
	go orderConsumer.Start(consumerCtx)
	
	// 5. Initialize Services
	jwtSecret := []byte(os.Getenv("JWT_SECRET"))
	if len(jwtSecret) == 0 {
		jwtSecret = []byte("super-secret-key-change-in-production")
	}
	userService := service.NewUserService(userRepo, jwtSecret)
	
	// 6. Initialize Handlers (gRPC Controllers)
	userHandler := handler.NewUserHandler(userService)
	
	// 7. Start TCP Listener
	lis, err := net.Listen("tcp", ":50051")
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}
	
	// 8. Create the gRPC server and register the handler
	s := grpc.NewServer()
	pb.RegisterUserServiceServer(s, userHandler)
	reflection.Register(s)
	
	log.Printf("User Service is running and listening at %v", lis.Addr())
	if err := s.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}
