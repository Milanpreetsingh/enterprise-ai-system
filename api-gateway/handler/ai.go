package handler

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"

	"enterprise-ai-system/api-gateway/middleware"

	"github.com/gin-gonic/gin"
)

// AIChatRequest defines the JSON payload for AI chat.
type AIChatRequest struct {
	Message  string `json:"message" binding:"required"`
	ThreadID string `json:"thread_id" binding:"required"`
	UserID   string `json:"user_id"`
}

// Chat forwards buffered REST chat queries to the internal FastAPI AI service.
func (h *GatewayHandler) Chat(c *gin.Context) {
	var req AIChatRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Contextual authentication: if user is authenticated via JWT, inject real UserID
	if userIDVal, exists := c.Get("userID"); exists {
		if uid, ok := userIDVal.(string); ok && uid != "" && uid != "anonymous" {
			req.UserID = uid
		}
	}
	if req.UserID == "" {
		req.UserID = "anonymous"
	}

	payloadBytes, err := json.Marshal(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to serialize chat request"})
		return
	}

	httpReq, err := http.NewRequestWithContext(
		c.Request.Context(),
		http.MethodPost,
		h.aiHTTPURL+"/api/v1/chat",
		bytes.NewReader(payloadBytes),
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create upstream request"})
		return
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := h.httpClient.Do(httpReq)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unreachable: " + err.Error()})
		return
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to read AI response"})
		return
	}

	// FinOps: Record consumed tokens in Redis
	tokenEstimate := int64((len(req.Message) + len(respBody)) / 4)
	if tokenEstimate < 10 {
		tokenEstimate = 10
	}
	middleware.RecordConsumedTokens(h.rdb, req.UserID, tokenEstimate)

	c.Data(resp.StatusCode, "application/json", respBody)
}

// AIApproveRequest defines supervisor approval payload.
type AIApproveRequest struct {
	ThreadID string `json:"thread_id" binding:"required"`
	Approved bool   `json:"approved"`
}

// Approve resumes graph execution upon human supervisor authorization.
func (h *GatewayHandler) Approve(c *gin.Context) {
	var req AIApproveRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	payloadBytes, _ := json.Marshal(req)
	httpReq, err := http.NewRequestWithContext(
		c.Request.Context(),
		http.MethodPost,
		h.aiHTTPURL+"/api/v1/agent/approve",
		bytes.NewReader(payloadBytes),
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := h.httpClient.Do(httpReq)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unreachable: " + err.Error()})
		return
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, "application/json", respBody)
}

// SeedKnowledgeRequest defines payload to insert into vector store.
type SeedKnowledgeRequest struct {
	Title    string                 `json:"title"`
	Content  string                 `json:"content" binding:"required"`
	Category string                 `json:"category"`
	Metadata map[string]interface{} `json:"metadata"`
}

// SeedKnowledge inserts a support document into pgvector via the AI service.
func (h *GatewayHandler) SeedKnowledge(c *gin.Context) {
	var req SeedKnowledgeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	payloadBytes, _ := json.Marshal(req)
	httpReq, err := http.NewRequestWithContext(
		c.Request.Context(),
		http.MethodPost,
		h.aiHTTPURL+"/api/v1/rag/seed",
		bytes.NewReader(payloadBytes),
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := h.httpClient.Do(httpReq)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unreachable: " + err.Error()})
		return
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, "application/json", respBody)
}

// ListKnowledgeDocs retrieves all knowledge base documents from pgvector.
func (h *GatewayHandler) ListKnowledgeDocs(c *gin.Context) {
	httpReq, err := http.NewRequestWithContext(
		c.Request.Context(),
		http.MethodGet,
		h.aiHTTPURL+"/api/v1/rag/docs",
		nil,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	resp, err := h.httpClient.Do(httpReq)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unreachable: " + err.Error()})
		return
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, "application/json", respBody)
}

// QueryKnowledgeRequest defines query payload to test vector search.
type QueryKnowledgeRequest struct {
	Query string `json:"query" binding:"required"`
	Limit int    `json:"limit"`
}

// QueryKnowledge tests semantic distance queries against pgvector.
func (h *GatewayHandler) QueryKnowledge(c *gin.Context) {
	var req QueryKnowledgeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if req.Limit <= 0 {
		req.Limit = 3
	}

	payloadBytes, _ := json.Marshal(req)
	httpReq, err := http.NewRequestWithContext(
		c.Request.Context(),
		http.MethodPost,
		h.aiHTTPURL+"/api/v1/rag/query",
		bytes.NewReader(payloadBytes),
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := h.httpClient.Do(httpReq)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unreachable: " + err.Error()})
		return
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, "application/json", respBody)
}
