package auth

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"time"
)

const (
	tokenTypeAccess  = "access"
	tokenTypeRefresh = "refresh"
)

// Claims 表示 token 声明内容。
type Claims struct {
	UserID    string `json:"uid"`
	Username  string `json:"uname"`
	ExpiresAt int64  `json:"exp"`
	Issuer    string `json:"iss"`
	TokenType string `json:"typ"`
	JTI       string `json:"jti,omitempty"`
}

// JWTService 封装 access/refresh token 的签发与解析。
// 这里使用 HMAC 自定义 token（payload.signature）格式，避免外部依赖耦合。
type JWTService struct {
	secret     []byte
	accessTTL  time.Duration
	refreshTTL time.Duration
	issuer     string
}

// NewJWTService 创建 token 服务。
func NewJWTService(secret string, accessTTL, refreshTTL time.Duration, issuer string) *JWTService {
	if accessTTL <= 0 {
		accessTTL = 2 * time.Hour
	}
	if refreshTTL <= 0 {
		refreshTTL = 7 * 24 * time.Hour
	}
	if issuer == "" {
		issuer = "basketball-mvp-cloud"
	}
	return &JWTService{
		secret:     []byte(secret),
		accessTTL:  accessTTL,
		refreshTTL: refreshTTL,
		issuer:     issuer,
	}
}

// SignAccess 签发 access token。
func (s *JWTService) SignAccess(userID, username string) (string, int64, error) {
	claims := Claims{
		UserID:    userID,
		Username:  username,
		ExpiresAt: time.Now().Add(s.accessTTL).Unix(),
		Issuer:    s.issuer,
		TokenType: tokenTypeAccess,
	}
	raw, err := s.signClaims(claims)
	if err != nil {
		return "", 0, err
	}
	return raw, int64(s.accessTTL.Seconds()), nil
}

// SignRefresh 签发 refresh token，并返回 token 对应 jti。
func (s *JWTService) SignRefresh(userID, username string) (token string, jti string, expiresIn int64, err error) {
	jti, err = randomJTI()
	if err != nil {
		return "", "", 0, err
	}
	claims := Claims{
		UserID:    userID,
		Username:  username,
		ExpiresAt: time.Now().Add(s.refreshTTL).Unix(),
		Issuer:    s.issuer,
		TokenType: tokenTypeRefresh,
		JTI:       jti,
	}
	raw, err := s.signClaims(claims)
	if err != nil {
		return "", "", 0, err
	}
	return raw, jti, int64(s.refreshTTL.Seconds()), nil
}

// ParseAccess 解析并校验 access token。
func (s *JWTService) ParseAccess(raw string) (*Claims, error) {
	claims, err := s.parse(raw)
	if err != nil {
		return nil, err
	}
	if claims.TokenType != tokenTypeAccess {
		return nil, errors.New("invalid token type")
	}
	return claims, nil
}

// ParseRefresh 解析并校验 refresh token。
func (s *JWTService) ParseRefresh(raw string) (*Claims, error) {
	claims, err := s.parse(raw)
	if err != nil {
		return nil, err
	}
	if claims.TokenType != tokenTypeRefresh {
		return nil, errors.New("invalid token type")
	}
	if claims.JTI == "" {
		return nil, errors.New("invalid refresh token jti")
	}
	return claims, nil
}

// HashToken 对 token 原文做 SHA256，用于数据库持久化。
func HashToken(raw string) string {
	s := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(s[:])
}

func (s *JWTService) signClaims(claims Claims) (string, error) {
	if len(s.secret) == 0 {
		return "", errors.New("empty token secret")
	}
	buf, err := json.Marshal(claims)
	if err != nil {
		return "", err
	}
	body := base64.RawURLEncoding.EncodeToString(buf)
	signature := s.sign(body)
	return body + "." + signature, nil
}

func (s *JWTService) parse(raw string) (*Claims, error) {
	parts := strings.Split(raw, ".")
	if len(parts) != 2 {
		return nil, errors.New("invalid token format")
	}
	body := strings.TrimSpace(parts[0])
	signature := strings.TrimSpace(parts[1])
	if body == "" || signature == "" {
		return nil, errors.New("invalid token format")
	}
	if !hmac.Equal([]byte(signature), []byte(s.sign(body))) {
		return nil, errors.New("invalid token signature")
	}
	payload, err := base64.RawURLEncoding.DecodeString(body)
	if err != nil {
		return nil, errors.New("invalid token payload")
	}
	var claims Claims
	if err := json.Unmarshal(payload, &claims); err != nil {
		return nil, errors.New("invalid token payload")
	}
	if claims.ExpiresAt <= time.Now().Unix() {
		return nil, errors.New("token expired")
	}
	if claims.Issuer != s.issuer {
		return nil, errors.New("invalid token issuer")
	}
	return &claims, nil
}

func (s *JWTService) sign(body string) string {
	mac := hmac.New(sha256.New, s.secret)
	_, _ = mac.Write([]byte(body))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func randomJTI() (string, error) {
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}
