# API Design & Routing Documentation

This document outlines the exact APIs we will build across the API Gateway and our internal microservices. It shows how external HTTP REST requests are mapped to internal gRPC calls.

## 1. Authentication Flow (User Service)
The User Service owns all authentication logic, including password hashing and JWT generation.

| Gateway REST API (Public) | Middleware | Internal gRPC Call (User Service) | Description |
| :--- | :--- | :--- | :--- |
| `POST /api/v1/auth/signup` | None | `CreateUser` | Hashes password, saves to Postgres. |
| `POST /api/v1/auth/login` | None | `LoginUser` | Verifies password, generates JWT Access & Refresh tokens. |
| `POST /api/v1/auth/refresh` | None | `RefreshToken` | Validates refresh token, issues new JWT Access token. |
| `GET /api/v1/users/me` | **JWT Auth** | `GetUser` | Fetches profile using the `user_id` extracted from the JWT. |

## 2. Order Flow (Order Service)
The Order Service manages the e-commerce lifecycle but relies on the User service for validation.

| Gateway REST API (Public) | Middleware | Internal gRPC Call (Order Service) | Description |
| :--- | :--- | :--- | :--- |
| `POST /api/v1/orders` | **JWT Auth** | `CreateOrder` | Creates order. **Internally calls `UserService.GetUser`** via gRPC to validate the user exists. |
| `GET /api/v1/orders/:id` | **JWT Auth** | `GetOrder` | Fetches a specific order from Postgres. |

## Inter-Service Communication Scenario
You asked: *"How does a gRPC service internally call other gRPC services?"*

There is a perfect scenario for this in our architecture!
When the API Gateway receives `POST /api/v1/orders`, it validates the JWT and sends the `user_id` to the **Order Service**. 
Before the Order Service saves the order to Postgres, it needs to ensure the user hasn't been banned or deleted. 
Therefore, the **Order Service** will instantiate a gRPC Client and make a blazingly fast internal network call to the **User Service's `GetUser`** endpoint. 

If the User Service returns an error (user not found), the Order Service aborts the transaction. This is classic microservice orchestration!
