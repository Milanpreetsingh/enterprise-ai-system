package service

import (
	"context"
	"errors"
	"time"

	"enterprise-ai-system/services/user/internal/repository"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
)

// UserClaims defines the JWT custom claims payload.
type UserClaims struct {
	UserID string `json:"user_id"`
	Email  string `json:"email"`
	Role   string `json:"role"`
	jwt.RegisteredClaims
}

// UserService defines the business logic operations for users.
type UserService interface {
	CreateUser(ctx context.Context, email, password, fullName, role string) (*repository.User, error)
	GetUser(ctx context.Context, id string) (*repository.User, error)
	Login(ctx context.Context, email, password string) (*repository.User, string, string, error)
	RefreshToken(ctx context.Context, refreshToken string) (string, error)
}

type userService struct {
	// We inject the UserRepository interface to separate business logic from data access.
	// This makes it easy to replace this SQL DB implementation with a mock for testing.
	userRepo  repository.UserRepository
	jwtSecret []byte
}

// NewUserService creates a new concrete implementation of UserService.
// We inject the Repository layer dependency (Dependency Injection / Constructor Injection)
// during initialization.
func NewUserService(userRepo repository.UserRepository, jwtSecret []byte) UserService {
	return &userService{
		userRepo:  userRepo,
		jwtSecret: jwtSecret,
	}
}

// CreateUser registers a new user after hashing their password.
func (s *userService) CreateUser(ctx context.Context, email, password, fullName, role string) (*repository.User, error) {
	if email == "" || password == "" || fullName == "" {
		return nil, errors.New("missing required fields")
	}

	if role == "" {
		role = "customer"
	}

	// Check if user already exists
	existing, err := s.userRepo.GetByEmail(ctx, email)
	if err == nil && existing != nil {
		return nil, errors.New("email already registered")
	}

	// Hash the password with bcrypt
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return nil, err
	}

	user := &repository.User{
		Email:    email,
		Password: string(hashedPassword),
		FullName: fullName,
		Role:     role,
	}

	if err := s.userRepo.Create(ctx, user); err != nil {
		return nil, err
	}

	return user, nil
}

// GetUser retrieves a user profile by ID.
func (s *userService) GetUser(ctx context.Context, id string) (*repository.User, error) {
	if id == "" {
		return nil, errors.New("invalid user ID")
	}
	return s.userRepo.GetByID(ctx, id)
}

// Login validates user credentials and returns signed JWT access & refresh tokens.
func (s *userService) Login(ctx context.Context, email, password string) (*repository.User, string, string, error) {
	if email == "" || password == "" {
		return nil, "", "", errors.New("missing email or password")
	}

	user, err := s.userRepo.GetByEmail(ctx, email)
	if err != nil {
		return nil, "", "", errors.New("invalid email or password")
	}

	// Compare bcrypt hashed password
	err = bcrypt.CompareHashAndPassword([]byte(user.Password), []byte(password))
	if err != nil {
		return nil, "", "", errors.New("invalid email or password")
	}

	// Generate access token (exp: 15 mins) and refresh token (exp: 7 days)
	accessToken, err := s.generateToken(user, 15*time.Minute)
	if err != nil {
		return nil, "", "", err
	}

	refreshToken, err := s.generateToken(user, 7*24*time.Hour)
	if err != nil {
		return nil, "", "", err
	}

	return user, accessToken, refreshToken, nil
}

// RefreshToken validates a refresh token and generates a new access token.
func (s *userService) RefreshToken(ctx context.Context, refreshToken string) (string, error) {
	if refreshToken == "" {
		return "", errors.New("missing refresh token")
	}

	claims, err := s.verifyToken(refreshToken)
	if err != nil {
		return "", errors.New("invalid or expired refresh token")
	}

	// Ensure user still exists
	user, err := s.userRepo.GetByID(ctx, claims.UserID)
	if err != nil {
		return "", errors.New("user not found")
	}

	// Generate new access token
	return s.generateToken(user, 15*time.Minute)
}

// Helper: Generates a JWT token for a given duration
func (s *userService) generateToken(user *repository.User, duration time.Duration) (string, error) {
	role := user.Role
	if role == "" {
		role = "customer"
	}

	claims := UserClaims{
		UserID: user.ID,
		Email:  user.Email,
		Role:   role,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(duration)),
			IssuedAt:  jwt.NewNumericDate(time.Now()),
			NotBefore: jwt.NewNumericDate(time.Now()),
			Issuer:    "enterprise-ai-system",
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(s.jwtSecret)
}

// Helper: Verifies a JWT token and returns claims
func (s *userService) verifyToken(tokenString string) (*UserClaims, error) {
	token, err := jwt.ParseWithClaims(tokenString, &UserClaims{}, func(token *jwt.Token) (interface{}, error) {
		// Validate the alg is HS256
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return s.jwtSecret, nil
	})

	if err != nil {
		return nil, err
	}

	claims, ok := token.Claims.(*UserClaims)
	if !ok || !token.Valid {
		return nil, errors.New("invalid token claims")
	}

	return claims, nil
}
