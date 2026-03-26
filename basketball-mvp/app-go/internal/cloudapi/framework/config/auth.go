package config

var authInstance *Auth

// Auth 描述认证/种子用户配置。
type Auth struct {
	JWTSecret        string `mapstructure:"jwt_secret"`
	Issuer           string `mapstructure:"issuer"`
	AccessTTLSecond  int64  `mapstructure:"access_ttl_second"`
	RefreshTTLSecond int64  `mapstructure:"refresh_ttl_second"`
	DefaultUsername  string `mapstructure:"default_username"`
	DefaultPassword  string `mapstructure:"default_password"`
}

// AuthInstance 返回认证配置单例。
func AuthInstance() *Auth {
	return authInstance
}

// AccessTTL 返回 access token TTL 秒。
func (a *Auth) AccessTTL() int64 {
	if a == nil || a.AccessTTLSecond <= 0 {
		return 7200
	}
	return a.AccessTTLSecond
}

// RefreshTTL 返回 refresh token TTL 秒。
func (a *Auth) RefreshTTL() int64 {
	if a == nil || a.RefreshTTLSecond <= 0 {
		return 604800
	}
	return a.RefreshTTLSecond
}

// Secret 返回 JWT secret。
func (a *Auth) Secret() string {
	if a == nil || a.JWTSecret == "" {
		return "please-change-this-secret-in-production"
	}
	return a.JWTSecret
}

// IssuerName 返回 token issuer。
func (a *Auth) IssuerName() string {
	if a == nil || a.Issuer == "" {
		return "basketball-mvp-cloud"
	}
	return a.Issuer
}
