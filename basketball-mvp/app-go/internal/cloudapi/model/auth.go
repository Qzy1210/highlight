package model

// LoginRequest 登录请求。
type LoginRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

// LoginResponse 登录成功返回。
type LoginResponse struct {
	AccessToken      string `json:"access_token"`
	RefreshToken     string `json:"refresh_token"`
	TokenType        string `json:"token_type"`
	ExpiresIn        int64  `json:"expires_in"`
	RefreshExpiresIn int64  `json:"refresh_expires_in"`
	UserID           string `json:"user_id"`
	Username         string `json:"username"`
}

// RefreshTokenRequest 刷新令牌请求。
type RefreshTokenRequest struct {
	RefreshToken string `json:"refresh_token" binding:"required"`
}
