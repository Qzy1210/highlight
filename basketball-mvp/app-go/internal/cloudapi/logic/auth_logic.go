package logic

import (
	"errors"
	"strings"
	"time"

	"basketball-mvp/app-go/internal/cloudapi/auth"
	"basketball-mvp/app-go/internal/cloudapi/model"
	"basketball-mvp/app-go/internal/cloudapi/repository"

	"golang.org/x/crypto/bcrypt"
)

// AuthLogic 处理登录与用户查询。
type AuthLogic struct {
	users        repository.UserRepository
	refreshToken repository.RefreshTokenRepository
	jwt          *auth.JWTService
}

// NewAuthLogic 创建鉴权逻辑层。
func NewAuthLogic(
	users repository.UserRepository,
	refreshToken repository.RefreshTokenRepository,
	jwtSvc *auth.JWTService,
) *AuthLogic {
	return &AuthLogic{
		users:        users,
		refreshToken: refreshToken,
		jwt:          jwtSvc,
	}
}

// Login 验证用户名密码并签发令牌。
func (l *AuthLogic) Login(req model.LoginRequest) (*model.LoginResponse, error) {
	req.Username = strings.TrimSpace(req.Username)
	u, err := l.users.FindByUsername(req.Username)
	if err != nil {
		return nil, errors.New("username or password is incorrect")
	}
	if bcrypt.CompareHashAndPassword([]byte(u.PasswordHash), []byte(req.Password)) != nil {
		return nil, errors.New("username or password is incorrect")
	}
	accessToken, accessExpiresIn, err := l.jwt.SignAccess(u.ID, u.Username)
	if err != nil {
		return nil, err
	}
	refreshToken, jti, refreshExpiresIn, err := l.jwt.SignRefresh(u.ID, u.Username)
	if err != nil {
		return nil, err
	}
	hash := auth.HashToken(refreshToken)
	if err := l.refreshToken.Create(&model.RefreshToken{
		TokenHash: hash,
		JTI:       jti,
		UserID:    u.ID,
		Username:  u.Username,
		ExpiresAt: time.Now().Add(time.Duration(refreshExpiresIn) * time.Second),
		Revoked:   false,
	}); err != nil {
		return nil, err
	}
	return &model.LoginResponse{
		AccessToken:      accessToken,
		RefreshToken:     refreshToken,
		TokenType:        "Bearer",
		ExpiresIn:        accessExpiresIn,
		RefreshExpiresIn: refreshExpiresIn,
		UserID:           u.ID,
		Username:         u.Username,
	}, nil
}

// Refresh 用 refresh token 轮换获取新的 access/refresh token。
func (l *AuthLogic) Refresh(req model.RefreshTokenRequest) (*model.LoginResponse, error) {
	raw := strings.TrimSpace(req.RefreshToken)
	if raw == "" {
		return nil, errors.New("refresh_token is required")
	}
	claims, err := l.jwt.ParseRefresh(raw)
	if err != nil {
		return nil, errors.New("invalid refresh token")
	}
	hash := auth.HashToken(raw)
	dbToken, err := l.refreshToken.FindActiveByHash(hash)
	if err != nil {
		return nil, errors.New("invalid refresh token")
	}
	if dbToken.JTI != claims.JTI || dbToken.UserID != claims.UserID {
		return nil, errors.New("invalid refresh token")
	}

	// 刷新时旋转 token：先撤销旧 refresh，再签发新 refresh。
	if err := l.refreshToken.RevokeByHash(hash); err != nil {
		return nil, errors.New("invalid refresh token")
	}
	accessToken, accessExpiresIn, err := l.jwt.SignAccess(claims.UserID, claims.Username)
	if err != nil {
		return nil, err
	}
	newRefreshToken, newJTI, refreshExpiresIn, err := l.jwt.SignRefresh(claims.UserID, claims.Username)
	if err != nil {
		return nil, err
	}
	if err := l.refreshToken.Create(&model.RefreshToken{
		TokenHash: auth.HashToken(newRefreshToken),
		JTI:       newJTI,
		UserID:    claims.UserID,
		Username:  claims.Username,
		ExpiresAt: time.Now().Add(time.Duration(refreshExpiresIn) * time.Second),
		Revoked:   false,
	}); err != nil {
		return nil, err
	}
	return &model.LoginResponse{
		AccessToken:      accessToken,
		RefreshToken:     newRefreshToken,
		TokenType:        "Bearer",
		ExpiresIn:        accessExpiresIn,
		RefreshExpiresIn: refreshExpiresIn,
		UserID:           claims.UserID,
		Username:         claims.Username,
	}, nil
}

// Me 按用户 ID 查询当前用户信息。
func (l *AuthLogic) Me(userID string) (*model.User, error) {
	return l.users.FindByID(userID)
}
