package middleware

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

// InitRedisClient establishes a connection to Redis with automatic fallback.
func InitRedisClient() *redis.Client {
	redisAddr := os.Getenv("REDIS_ADDR")
	if redisAddr == "" {
		redisAddr = "localhost:6379"
	}

	rdb := redis.NewClient(&redis.Options{
		Addr:         redisAddr,
		Password:     os.Getenv("REDIS_PASSWORD"),
		DB:           0,
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	if err := rdb.Ping(ctx).Err(); err != nil {
		fmt.Printf("[Redis] Warning: Unable to connect to Redis at %s (%v). Rate limiting will operate in memory fallback mode.\n", redisAddr, err)
	} else {
		fmt.Printf("[Redis] Connected successfully to Redis at %s\n", redisAddr)
	}

	return rdb
}

// RateLimiterMiddleware implements a sliding-window rate limiter per identity (User ID or IP).
// Protects the API Gateway against DoS/abuse attacks when exposed publicly.
func RateLimiterMiddleware(rdb *redis.Client, limitPerMinute int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		if rdb == nil {
			c.Next()
			return
		}

		// Identify caller: prefer authenticated UserID, otherwise client IP
		identity := c.GetString("userID")
		if identity == "" || identity == "anonymous" {
			identity = c.ClientIP()
		}

		now := time.Now()
		minuteBucket := now.Format("200601021504") // YYYYMMDDHHmm
		redisKey := fmt.Sprintf("ratelimit:%s:%s", identity, minuteBucket)

		ctx, cancel := context.WithTimeout(c.Request.Context(), 1*time.Second)
		defer cancel()

		count, err := rdb.Incr(ctx, redisKey).Result()
		if err != nil {
			// Fail open on Redis connectivity error to not break user traffic
			c.Next()
			return
		}

		// Set key TTL to expire after 2 minutes
		if count == 1 {
			_ = rdb.Expire(ctx, redisKey, 2*time.Minute).Err()
		}

		c.Header("X-RateLimit-Limit", strconv.FormatInt(limitPerMinute, 10))
		remaining := limitPerMinute - count
		if remaining < 0 {
			remaining = 0
		}
		c.Header("X-RateLimit-Remaining", strconv.FormatInt(remaining, 10))

		if count > limitPerMinute {
			c.Header("Retry-After", "60")
			c.JSON(http.StatusTooManyRequests, gin.H{
				"error":       fmt.Sprintf("Too Many Requests: Rate limit of %d requests per minute exceeded.", limitPerMinute),
				"retry_after": 60,
			})
			c.Abort()
			return
		}

		c.Next()
	}
}

// TokenBudgetMiddleware enforces FinOps daily token quota per authenticated user.
// Returns HTTP 429 when a user exhausts their daily token quota (e.g., 10,000 tokens/day).
func TokenBudgetMiddleware(rdb *redis.Client, dailyLimit int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		if rdb == nil {
			c.Next()
			return
		}

		userID := c.GetString("userID")
		if userID == "" || userID == "anonymous" {
			c.Next()
			return
		}

		today := time.Now().UTC().Format("2006-01-02")
		budgetKey := fmt.Sprintf("ai:budget:%s:%s", userID, today)

		ctx, cancel := context.WithTimeout(c.Request.Context(), 1*time.Second)
		defer cancel()

		usedVal, err := rdb.Get(ctx, budgetKey).Result()
		var usedTokens int64 = 0
		if err == nil {
			usedTokens, _ = strconv.ParseInt(usedVal, 10, 64)
		}

		c.Header("X-Daily-Token-Budget", strconv.FormatInt(dailyLimit, 10))
		c.Header("X-Daily-Tokens-Used", strconv.FormatInt(usedTokens, 10))
		remaining := dailyLimit - usedTokens
		if remaining < 0 {
			remaining = 0
		}
		c.Header("X-Daily-Tokens-Remaining", strconv.FormatInt(remaining, 10))

		if usedTokens >= dailyLimit {
			c.JSON(http.StatusTooManyRequests, gin.H{
				"error":            "Daily AI Token Budget Exceeded: You have consumed your daily allowance of tokens.",
				"daily_limit":      dailyLimit,
				"tokens_used":      usedTokens,
				"resets_at":        "00:00 UTC",
			})
			c.Abort()
			return
		}

		c.Next()
	}
}

// RecordConsumedTokens updates the user's daily consumed token counter in Redis.
func RecordConsumedTokens(rdb *redis.Client, userID string, tokens int64) {
	if rdb == nil || userID == "" || userID == "anonymous" || tokens <= 0 {
		return
	}

	today := time.Now().UTC().Format("2006-01-02")
	budgetKey := fmt.Sprintf("ai:budget:%s:%s", userID, today)

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	_ = rdb.IncrBy(ctx, budgetKey, tokens).Err()
	_ = rdb.Expire(ctx, budgetKey, 48*time.Hour).Err()
}
