package model

// User 是云端 API 的用户实体（首版内存存储）。
type User struct {
	ID           string `json:"id"`
	Username     string `json:"username"`
	PasswordHash string `json:"-"`
}
