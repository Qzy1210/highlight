package provider

// Provider 抽象基础设施组件的生命周期。
type Provider interface {
	Name() string
	Init() error
	Boot() error
	Close() error
}

// ProviderFunc 是函数式 Provider 实现。
type ProviderFunc struct {
	name       string
	initer     func() error
	booter     func() error
	terminater func() error
}

// NewProvider 创建函数式 Provider。
// fn 依次对应 init / boot / terminate，可按需传入。
func NewProvider(name string, fn ...func() error) *ProviderFunc {
	p := &ProviderFunc{name: name}
	if len(fn) > 0 {
		p.initer = fn[0]
	}
	if len(fn) > 1 {
		p.booter = fn[1]
	}
	if len(fn) > 2 {
		p.terminater = fn[2]
	}
	return p
}

func (p *ProviderFunc) Name() string {
	return p.name
}

func (p *ProviderFunc) Init() error {
	if p.initer != nil {
		return p.initer()
	}
	return nil
}

func (p *ProviderFunc) Boot() error {
	if p.booter != nil {
		return p.booter()
	}
	return nil
}

func (p *ProviderFunc) Close() error {
	if p.terminater != nil {
		return p.terminater()
	}
	return nil
}
