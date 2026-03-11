# Config 模块
> 【架构分层: 支撑层 - 配置管理模块】

本目录实现 nanobot 的配置加载和管理

## 模块定位
- **架构层**: 支撑层
- **逻辑模块**: 配置管理
- **核心职责**: 从文件加载配置， 提供配置访问接口， 支持配置验证

## 核心配置结构

### 主配置文件 (~/.nanobot/config.json)
```json
{
  "providers": {
    "openrouter": { "apiKey": "sk-or-xxx" },
    "anthropic": { "apiKey": "sk-ant-xxx" }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4",
      "provider": "openrouter"
    }
  },
  "channels": {
    "telegram": { "enabled": true, "token": "xxx" },
    "discord": { "enabled": true, "token": "xxx" }
  },
  "tools": {
    "restrictToWorkspace": true,
    "mcpServers": { ... }
  }
}
```

## 核心接口

### 配置加载
```python
def load_config() -> dict:
    """从 ~/.nanobot/config.json 加载配置"""

def get_config() -> dict:
    """获取当前配置 (带缓存)"""
```

### 配置验证
```python
class ProvidersConfig(BaseModel):
    openrouter: ProviderConfig = ProviderConfig()
    anthropic: ProviderConfig = ProviderConfig()
    # ...

class ChannelsConfig(BaseModel):
    telegram: TelegramConfig = TelegramConfig()
    discord: DiscordConfig = DiscordConfig()
    # ...
```

## 文件协作与角色

| 文件 | 架构角色 | 职责 |
|------|----------|------|
| `loader.py` | 核心实现 | 配置文件加载和缓存 |
| `schema.py` | 数据定义 | Pydantic 配置模型定义 |

## 架构优缺点

### 优点
- ✅ **类型安全**: 使用 Pydantic 验证配置
- ✅ **自动创建**: 首次运行自动创建默认配置
- ✅ **环境变量**: 支持 API Key 从环境变量读取
- ✅ **文档完整**: 每个配置项有默认值和说明

### 缺点
- ⚠️ **无热更新**: 修改配置需要重启
- ⚠️ **无验证**: 启动时不验证配置完整性
- ⚠️ **无加密**: API Key 明文存储

### 改进建议
1. 支持配置热更新 (SIGHUP)
2. 启动时验证必需配置
3. 支持敏感信息加密存储
