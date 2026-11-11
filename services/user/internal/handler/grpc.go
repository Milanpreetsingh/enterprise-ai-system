package handler

import (
	"context"
	"log"

	pb "enterprise-ai-system/proto-schemas/userpb"
	"enterprise-ai-system/services/user/internal/service"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// UserHandler implements the gRPC UserServiceServer interface.
// Think of this exactly like a "Controller" in a REST API.
type UserHandler struct {
	// Required by gRPC to ensure forward compatibility
	pb.UnimplementedUserServiceServer
	
	// We store the service layer interface here. Storing it as an interface
	// rather than a concrete struct allows us to inject mock implementations in tests.
	userService service.UserService
}

// NewUserHandler creates a new instance of the UserHandler.
// We use Constructor Injection (a form of Dependency Injection) here to provide 
// the required UserService dependency to the handler when it is instantiated.
func NewUserHandler(userService service.UserService) *UserHandler {
	return &UserHandler{
		userService: userService,
	}
}

func (h *UserHandler) CreateUser(ctx context.Context, req *pb.CreateUserRequest) (*pb.UserResponse, error) {
	log.Printf("Received CreateUser request for email: %s, role: %s", req.GetEmail(), req.GetRole())
	
	role := req.GetRole()
	if role == "" {
		role = "customer"
	}

	user, err := h.userService.CreateUser(ctx, req.GetEmail(), req.GetPassword(), req.GetFullName(), role)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "failed to create user: %v", err)
	}
	
	return &pb.UserResponse{
		Id:       user.ID,
		Email:    user.Email,
		FullName: user.FullName,
		Role:     user.Role,
	}, nil
}

func (h *UserHandler) GetUser(ctx context.Context, req *pb.GetUserRequest) (*pb.UserResponse, error) {
	log.Printf("Received GetUser request for ID: %s", req.GetId())
	
	user, err := h.userService.GetUser(ctx, req.GetId())
	if err != nil {
		return nil, status.Errorf(codes.NotFound, "user not found: %v", err)
	}
	
	return &pb.UserResponse{
		Id:       user.ID,
		Email:    user.Email,
		FullName: user.FullName,
		Role:     user.Role,
	}, nil
}

func (h *UserHandler) LoginUser(ctx context.Context, req *pb.LoginUserRequest) (*pb.LoginUserResponse, error) {
	log.Printf("Received LoginUser request for email: %s", req.GetEmail())
	
	user, accessToken, refreshToken, err := h.userService.Login(ctx, req.GetEmail(), req.GetPassword())
	if err != nil {
		return nil, status.Errorf(codes.Unauthenticated, "login failed: %v", err)
	}
	
	return &pb.LoginUserResponse{
		User: &pb.UserResponse{
			Id:       user.ID,
			Email:    user.Email,
			FullName: user.FullName,
			Role:     user.Role,
		},
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
	}, nil
}

func (h *UserHandler) RefreshToken(ctx context.Context, req *pb.RefreshTokenRequest) (*pb.RefreshTokenResponse, error) {
	log.Printf("Received RefreshToken request")
	
	accessToken, err := h.userService.RefreshToken(ctx, req.GetRefreshToken())
	if err != nil {
		return nil, status.Errorf(codes.Unauthenticated, "refresh token failed: %v", err)
	}
	
	return &pb.RefreshTokenResponse{
		AccessToken: accessToken,
	}, nil
}
