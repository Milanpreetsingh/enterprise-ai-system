package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"enterprise-ai-system/services/inventory/internal/consumer"
	"enterprise-ai-system/services/inventory/internal/domain"
	"enterprise-ai-system/services/inventory/internal/repository"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func main() {
	log.Println("=====================================================")
	log.Println("       Starting Enterprise Inventory Service         ")
	log.Println("=====================================================")

	// 1. Connect to PostgreSQL
	dsn := os.Getenv("DB_DSN")
	if dsn == "" {
		dsn = "host=localhost user=postgres password=postgres dbname=postgres port=5432 sslmode=disable TimeZone=UTC"
	}

	var db *gorm.DB
	var err error
	for i := 0; i < 5; i++ {
		db, err = gorm.Open(postgres.Open(dsn), &gorm.Config{})
		if err == nil {
			break
		}
		log.Printf("Connecting to database... retrying in 2 seconds (%v)", err)
		time.Sleep(2 * time.Second)
	}
	if err != nil {
		log.Fatalf("Fatal: failed to connect to database: %v", err)
	}
	log.Println("Inventory Service connected to PostgreSQL successfully.")

	// 2. Auto-migrate tables
	if err := db.AutoMigrate(&repository.Inventory{}, &repository.ProcessedEvent{}); err != nil {
		log.Fatalf("Failed to auto-migrate inventory schemas: %v", err)
	}

	// 3. Initialize repository
	repo := repository.NewPostgresInventoryRepository(db)

	// 4. Initialize Kafka Consumer
	kafkaBrokers := os.Getenv("KAFKA_BROKERS")
	if kafkaBrokers == "" {
		kafkaBrokers = domain.DefaultKafkaBroker
	}
	kafkaTopic := os.Getenv("KAFKA_ORDER_TOPIC")
	if kafkaTopic == "" {
		kafkaTopic = domain.TopicOrderEvents
	}
	dlqTopic := os.Getenv("KAFKA_DLQ_TOPIC")
	if dlqTopic == "" {
		dlqTopic = domain.TopicOrderDLQ
	}
	consumerGroup := os.Getenv("KAFKA_CONSUMER_GROUP")
	if consumerGroup == "" {
		consumerGroup = domain.DefaultConsumerGroup
	}

	inventoryConsumer := consumer.NewInventoryConsumer(
		kafkaBrokers,
		kafkaTopic,
		dlqTopic,
		consumerGroup,
		repo,
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Launch consumer loop in background goroutine
	go inventoryConsumer.Start(ctx)

	// 5. Handle Graceful Shutdown
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)

	sig := <-sigCh
	log.Printf("Received termination signal (%v). Initiating graceful shutdown...", sig)
	cancel()

	if err := inventoryConsumer.Close(); err != nil {
		log.Printf("Error closing Kafka reader: %v", err)
	}
	log.Println("Inventory Service shut down cleanly.")
}
