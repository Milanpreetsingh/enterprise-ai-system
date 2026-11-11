package handler

import (
	"io"
	"net/http"

	"enterprise-ai-system/api-gateway/middleware"
	aipb "enterprise-ai-system/proto-schemas/aipb"

	"github.com/gin-gonic/gin"
)

// StreamChat handles HTTP Server-Sent Events (SSE) streaming real-time tokens from AI Service gRPC.
func (h *GatewayHandler) StreamChat(c *gin.Context) {
	message := c.Query("message")
	threadID := c.Query("thread_id")
	if message == "" || threadID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Missing required query params: message and thread_id"})
		return
	}

	userIDVal, exists := c.Get("userID")
	userID := "anonymous"
	if exists {
		userID = userIDVal.(string)
	}

	// Request gRPC server stream from Python AI Service
	stream, err := h.aiClient.StreamChat(c.Request.Context(), &aipb.ChatStreamRequest{
		Message:  message,
		ThreadId: threadID,
		UserId:   userID,
	})

	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to connect to AI streaming server: " + err.Error()})
		return
	}

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("Transfer-Encoding", "chunked")

	var streamedTokens int64 = int64(len(message) / 4)
	if streamedTokens < 5 {
		streamedTokens = 5
	}

	c.Stream(func(w io.Writer) bool {
		resp, err := stream.Recv()
		if err == io.EOF || (resp != nil && resp.GetIsFinal()) {
			middleware.RecordConsumedTokens(h.rdb, userID, streamedTokens)
			c.SSEvent("message", gin.H{"token": "", "is_final": true})
			return false
		}
		if err != nil {
			middleware.RecordConsumedTokens(h.rdb, userID, streamedTokens)
			c.SSEvent("error", gin.H{"error": err.Error()})
			return false
		}

		streamedTokens++
		c.SSEvent("message", gin.H{"token": resp.GetToken(), "is_final": false})
		return true
	})
}
