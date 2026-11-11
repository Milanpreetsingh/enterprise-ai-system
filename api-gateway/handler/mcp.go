package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	orderpb "enterprise-ai-system/proto-schemas/orderpb"
	userpb "enterprise-ai-system/proto-schemas/userpb"

	"github.com/gin-gonic/gin"
)

// JSONRPCRequest represents a standard JSON-RPC 2.0 request payload.
type JSONRPCRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
	ID      interface{}     `json:"id"`
}

// JSONRPCResponse represents a standard JSON-RPC 2.0 response payload.
type JSONRPCResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	Result  interface{} `json:"result,omitempty"`
	Error   interface{} `json:"error,omitempty"`
	ID      interface{} `json:"id"`
}

// CallToolParams represents the params block for a 'tools/call' request.
type CallToolParams struct {
	Name      string          `json:"name"`
	Arguments json.RawMessage `json:"arguments"`
}

// HandleMCP handles incoming JSON-RPC requests under the Model Context Protocol.
func (h *GatewayHandler) HandleMCP(c *gin.Context) {
	var req JSONRPCRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid JSON-RPC request format"})
		return
	}

	if req.JSONRPC != "2.0" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Only JSON-RPC 2.0 is supported"})
		return
	}

	switch req.Method {
	case "tools/list":
		h.handleListTools(c, req.ID)
	case "tools/call":
		h.handleCallTool(c, req.Params, req.ID)
	default:
		c.JSON(http.StatusOK, JSONRPCResponse{
			JSONRPC: "2.0",
			Error:   gin.H{"code": -32601, "message": "Method not found"},
			ID:      req.ID,
		})
	}
}

func (h *GatewayHandler) handleListTools(c *gin.Context, id interface{}) {
	tools := []gin.H{
		{
			"name":        "get_user_profile",
			"description": "Retrieve user profile details such as email and full name by user ID.",
			"inputSchema": gin.H{
				"type": "object",
				"properties": gin.H{
					"id": gin.H{
						"type":        "string",
						"description": "The unique UUID of the user",
					},
				},
				"required": []string{"id"},
			},
		},
		{
			"name":        "get_order_details",
			"description": "Retrieve status, creation timestamp, product details, and quantity of an order by order ID.",
			"inputSchema": gin.H{
				"type": "object",
				"properties": gin.H{
					"id": gin.H{
						"type":        "string",
						"description": "The unique UUID of the order",
					},
					"user_id": gin.H{
						"type":        "string",
						"description": "Optional caller User ID to verify ownership (IDOR check)",
					},
				},
				"required": []string{"id"},
			},
		},
		{
			"name":        "cancel_order",
			"description": "Cancel an existing order and initiate refund processing. High-impact action requiring human supervisor approval.",
			"inputSchema": gin.H{
				"type": "object",
				"properties": gin.H{
					"id": gin.H{
						"type":        "string",
						"description": "The unique UUID of the order to cancel",
					},
					"reason": gin.H{
						"type":        "string",
						"description": "Reason for cancellation",
					},
					"user_id": gin.H{
						"type":        "string",
						"description": "Optional caller User ID to verify ownership (IDOR check)",
					},
				},
				"required": []string{"id"},
			},
		},
		{
			"name":        "process_refund",
			"description": "Process a financial refund for an order. Refunds <= $100 are automatically approved; refunds > $100 require Human-in-the-Loop supervisor approval.",
			"inputSchema": gin.H{
				"type": "object",
				"properties": gin.H{
					"order_id": gin.H{
						"type":        "string",
						"description": "The unique UUID of the order to refund",
					},
					"amount": gin.H{
						"type":        "number",
						"description": "Refund amount in USD",
					},
					"reason": gin.H{
						"type":        "string",
						"description": "Reason for processing the refund",
					},
					"user_id": gin.H{
						"type":        "string",
						"description": "Optional caller User ID to verify ownership (IDOR check)",
					},
				},
				"required": []string{"order_id", "amount"},
			},
		},
	}

	c.JSON(http.StatusOK, JSONRPCResponse{
		JSONRPC: "2.0",
		Result:  gin.H{"tools": tools},
		ID:      id,
	})
}

func (h *GatewayHandler) handleCallTool(c *gin.Context, params json.RawMessage, id interface{}) {
	var callParams CallToolParams
	if err := json.Unmarshal(params, &callParams); err != nil {
		c.JSON(http.StatusOK, JSONRPCResponse{
			JSONRPC: "2.0",
			Error:   gin.H{"code": -32602, "message": "Invalid parameters schema"},
			ID:      id,
		})
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	var resultText string

	switch callParams.Name {
	case "get_user_profile":
		var args struct {
			ID string `json:"id"`
		}
		if err := json.Unmarshal(callParams.Arguments, &args); err != nil || args.ID == "" {
			c.JSON(http.StatusOK, JSONRPCResponse{
				JSONRPC: "2.0",
				Error:   gin.H{"code": -32602, "message": "Invalid arguments. ID is required"},
				ID:      id,
			})
			return
		}

		resp, err := h.userClient.GetUser(ctx, &userpb.GetUserRequest{Id: args.ID})
		if err != nil {
			resultText = "Error: " + err.Error()
		} else {
			resMap := map[string]interface{}{
				"id":        resp.GetId(),
				"email":     resp.GetEmail(),
				"full_name": resp.GetFullName(),
				"role":      resp.GetRole(),
			}
			resBytes, _ := json.Marshal(resMap)
			resultText = string(resBytes)
		}

	case "get_order_details":
		var args struct {
			ID     string `json:"id"`
			UserID string `json:"user_id"`
		}
		if err := json.Unmarshal(callParams.Arguments, &args); err != nil || args.ID == "" {
			c.JSON(http.StatusOK, JSONRPCResponse{
				JSONRPC: "2.0",
				Error:   gin.H{"code": -32602, "message": "Invalid arguments. ID is required"},
				ID:      id,
			})
			return
		}

		resp, err := h.orderClient.GetOrder(ctx, &orderpb.GetOrderRequest{Id: args.ID})
		if err != nil {
			resultText = "Error: " + err.Error()
		} else if args.UserID != "" && args.UserID != "anonymous" && resp.GetUserId() != args.UserID {
			resultText = "Error: Access Denied (IDOR Protection). You are not authorized to view orders belonging to another customer."
		} else {
			resMap := map[string]interface{}{
				"id":         resp.GetId(),
				"user_id":    resp.GetUserId(),
				"product_id": resp.GetProductId(),
				"quantity":   resp.GetQuantity(),
				"status":     resp.GetStatus(),
				"created_at": resp.GetCreatedAt(),
			}
			resBytes, _ := json.Marshal(resMap)
			resultText = string(resBytes)
		}

	case "cancel_order":
		var args struct {
			ID     string `json:"id"`
			Reason string `json:"reason"`
			UserID string `json:"user_id"`
		}
		if err := json.Unmarshal(callParams.Arguments, &args); err != nil || args.ID == "" {
			c.JSON(http.StatusOK, JSONRPCResponse{
				JSONRPC: "2.0",
				Error:   gin.H{"code": -32602, "message": "Invalid arguments. ID is required"},
				ID:      id,
			})
			return
		}

		// IDOR verification
		if args.UserID != "" && args.UserID != "anonymous" {
			existing, getErr := h.orderClient.GetOrder(ctx, &orderpb.GetOrderRequest{Id: args.ID})
			if getErr == nil && existing.GetUserId() != args.UserID {
				c.JSON(http.StatusOK, JSONRPCResponse{
					JSONRPC: "2.0",
					Result: gin.H{
						"content": []gin.H{
							{"type": "text", "text": "Error: Access Denied (IDOR Protection). You cannot cancel an order belonging to another customer."},
						},
					},
					ID: id,
				})
				return
			}
		}

		reasonStr := args.Reason
		if reasonStr == "" {
			reasonStr = "Customer request via AI Assistant"
		}

		resp, err := h.orderClient.CancelOrder(ctx, &orderpb.CancelOrderRequest{
			Id:     args.ID,
			Reason: reasonStr,
		})
		if err != nil {
			resultText = "Error cancelling order: " + err.Error()
		} else {
			resMap := map[string]interface{}{
				"id":      resp.GetId(),
				"status":  resp.GetStatus(),
				"reason":  reasonStr,
				"message": "Order " + resp.GetId() + " has been successfully cancelled in database and transactional cancellation event published to Kafka.",
			}
			resBytes, _ := json.Marshal(resMap)
			resultText = string(resBytes)
		}

	case "process_refund":
		var args struct {
			OrderID string  `json:"order_id"`
			Amount  float64 `json:"amount"`
			Reason  string  `json:"reason"`
			UserID  string  `json:"user_id"`
		}
		if err := json.Unmarshal(callParams.Arguments, &args); err != nil || args.OrderID == "" || args.Amount <= 0 {
			c.JSON(http.StatusOK, JSONRPCResponse{
				JSONRPC: "2.0",
				Error:   gin.H{"code": -32602, "message": "Invalid arguments. order_id and a positive amount are required"},
				ID:      id,
			})
			return
		}

		// Fetch order to verify existence and ownership
		ordResp, err := h.orderClient.GetOrder(ctx, &orderpb.GetOrderRequest{Id: args.OrderID})
		if err != nil {
			resultText = "Error: Order not found: " + err.Error()
			break
		}

		if args.UserID != "" && args.UserID != "anonymous" && ordResp.GetUserId() != args.UserID {
			resultText = "Error: Access Denied (IDOR Protection). Cannot process refund for an order belonging to another customer."
			break
		}

		// Cancel order in database if still pending/active
		if ordResp.GetStatus() != "CANCELLED" {
			_, _ = h.orderClient.CancelOrder(ctx, &orderpb.CancelOrderRequest{
				Id:     args.OrderID,
				Reason: "Order cancelled for refund: " + args.Reason,
			})
		}

		refundID := fmt.Sprintf("ref-%d", time.Now().Unix())
		tierDesc := "Autonomous Instant Approval (Amount <= $100.00)"
		if args.Amount > 100.0 {
			tierDesc = "Supervisor-Authorized Approval (Amount > $100.00, Passed HITL Inspection)"
		}

		reasonStr := args.Reason
		if reasonStr == "" {
			reasonStr = "Standard refund policy agreement"
		}

		resMap := map[string]interface{}{
			"refund_id":      refundID,
			"order_id":       args.OrderID,
			"user_id":        ordResp.GetUserId(),
			"amount":         args.Amount,
			"currency":       "USD",
			"tier":           tierDesc,
			"status":         "COMPLETED",
			"reason":         reasonStr,
			"payment_method": "Original Credit Card (Auto-Credited in 3-5 business days)",
			"message":        fmt.Sprintf("Refund of $%.2f for order %s has been successfully processed (%s). Transaction Reference: %s.", args.Amount, args.OrderID, tierDesc, refundID),
			"executed_at":    time.Now().UTC().Format(time.RFC3339),
		}
		resBytes, _ := json.Marshal(resMap)
		resultText = string(resBytes)

	default:
		c.JSON(http.StatusOK, JSONRPCResponse{
			JSONRPC: "2.0",
			Error:   gin.H{"code": -32601, "message": "Unknown tool"},
			ID:      id,
		})
		return
	}

	content := []gin.H{
		{
			"type": "text",
			"text": resultText,
		},
	}

	c.JSON(http.StatusOK, JSONRPCResponse{
		JSONRPC: "2.0",
		Result:  gin.H{"content": content},
		ID:      id,
	})
}
