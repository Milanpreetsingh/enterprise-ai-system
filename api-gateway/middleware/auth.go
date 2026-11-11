package middleware

import (
	"errors"
	"net/http"
	"os"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
)

// UserClaims defines the JWT custom claims payload matching the User Service.
type UserClaims struct {
	UserID string `json:"user_id"`
	Email  string `json:"email"`
	Role   string `json:"role"`
	jwt.RegisteredClaims
}

// JWTAuthMiddleware intercepts requests and validates the JWT in Authorization header or query param.
func JWTAuthMiddleware() gin.HandlerFunc {
	jwtSecret := []byte(os.Getenv("JWT_SECRET"))
	if len(jwtSecret) == 0 {
		jwtSecret = []byte("super-secret-key-change-in-production")
	}

	return func(c *gin.Context) {
		tokenString := ""
		authHeader := c.GetHeader("Authorization")
		if authHeader != "" {
			tokenString = strings.TrimSpace(strings.TrimPrefix(authHeader, "Bearer "))
		} else if queryToken := c.Query("token"); queryToken != "" {
			// Allows EventSource / SSE requests to authenticate via ?token=
			tokenString = strings.TrimSpace(strings.TrimPrefix(queryToken, "Bearer "))
		}

		if tokenString == "" {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "Authentication required: Bearer token or ?token= query parameter missing"})
			c.Abort()
			return
		}

		token, err := jwt.ParseWithClaims(tokenString, &UserClaims{}, func(token *jwt.Token) (interface{}, error) {
			if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
				return nil, errors.New("unexpected signing method")
			}
			return jwtSecret, nil
		})

		if err != nil || !token.Valid {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid or expired access token"})
			c.Abort()
			return
		}

		claims, ok := token.Claims.(*UserClaims)
		if !ok {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid token claims"})
			c.Abort()
			return
		}

		role := claims.Role
		if role == "" {
			role = "customer"
		}

		// Store user details in context for downstream handlers
		c.Set("userID", claims.UserID)
		c.Set("email", claims.Email)
		c.Set("role", role)
		c.Next()
	}
}

// RequireRole enforces Role-Based Access Control (RBAC).
// Only requests whose authenticated role matches one of allowedRoles can proceed.
func RequireRole(allowedRoles ...string) gin.HandlerFunc {
	return func(c *gin.Context) {
		roleVal, exists := c.Get("role")
		if !exists {
			c.JSON(http.StatusForbidden, gin.H{"error": "Forbidden: No authenticated role found in session"})
			c.Abort()
			return
		}

		userRole, _ := roleVal.(string)
		for _, allowed := range allowedRoles {
			if strings.EqualFold(userRole, allowed) {
				c.Next()
				return
			}
		}

		c.JSON(http.StatusForbidden, gin.H{
			"error":          "Forbidden: Insufficient permissions for this action",
			"required_roles": allowedRoles,
			"current_role":   userRole,
		})
		c.Abort()
	}
}

// OptionalJWTAuthMiddleware checks for an Authorization header or token query parameter.
// If valid, it attaches the authenticated UserID and Role to the context.
// If absent or invalid, it gracefully falls back to "anonymous" without rejecting the request.
func OptionalJWTAuthMiddleware() gin.HandlerFunc {
	jwtSecret := []byte(os.Getenv("JWT_SECRET"))
	if len(jwtSecret) == 0 {
		jwtSecret = []byte("super-secret-key-change-in-production")
	}

	return func(c *gin.Context) {
		tokenString := ""
		authHeader := c.GetHeader("Authorization")
		if authHeader != "" {
			tokenString = strings.TrimSpace(strings.TrimPrefix(authHeader, "Bearer "))
		} else if queryToken := c.Query("token"); queryToken != "" {
			tokenString = strings.TrimSpace(strings.TrimPrefix(queryToken, "Bearer "))
		}

		if tokenString != "" {
			token, err := jwt.ParseWithClaims(tokenString, &UserClaims{}, func(token *jwt.Token) (interface{}, error) {
				if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
					return nil, errors.New("unexpected signing method")
				}
				return jwtSecret, nil
			})

			if err == nil && token.Valid {
				if claims, ok := token.Claims.(*UserClaims); ok {
					role := claims.Role
					if role == "" {
						role = "customer"
					}
					c.Set("userID", claims.UserID)
					c.Set("email", claims.Email)
					c.Set("role", role)
					c.Next()
					return
				}
			}
		}

		// Guest / Anonymous fallback
		c.Set("userID", "anonymous")
		c.Set("role", "anonymous")
		c.Next()
	}
}
