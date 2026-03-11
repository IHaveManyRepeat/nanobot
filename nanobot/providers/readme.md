# Providers 模块
> 【架构分层: 支撑层 - LLM 提供者注册模块】

本目录实现 nanobot 的 LLM 提供者抽象层， 支持多种 LLM 后端

## 模块定位
- **架构层**: 支撑层
- **逻辑模块**: LLM 提供者注册
- **核心职责**: 提供 LLM 调用的统一抽象， 支持多种 LLM 后端， 负责模型选择和调用

## 支持的提供商

| Provider | 类型 | 特点 |
|---------|------|------|
| OpenRouter | 网关 | 支持所有模型，推荐 |
| Anthropic | 直连 | Claude 模型原生支持 |
| OpenAI | 直连 | GPT 稡型 |
| DeepSeek | 直连 | DeepSeek 模型 |
| Gemini | 直连 | Google Gemini |
| Groq | 直连 | Groq 模型，支持 Whisper |
| Moonshot | 直连 | Moonshot/Kimi |
| Zhipu | 直连 | 智谱 GLM |
| VolcEngine | 直连 | 火山引擎 |
| vLLM | 本地 | 本地 LLM 部署 |
| Custom | 自定义 | 任何 OpenAI 兼容 API |

## 核心接口

### LLMProvider 基类
```python
class LLMProvider(ABC):
    def get_default_model(self) -> str
    async def chat(self, messages: list, tools: list = None) -> dict
    async def stream(self, messages: list, tools: list = None) -> AsyncIterator
```

### ProviderSpec 注册规范
```python
@dataclass
class ProviderSpec:
    name: str                  # 配置字段名
    keywords: tuple[str, ...]  # 模型名关键词
    env_key: str               # 环境变量
    litellm_prefix: str        # LiteLLM 前缀
```

## 核心流程
```
请求到达 → ProviderRegistry.match(model_name)
                    ↓
            获取 Provider 实例
                    ↓
            provider.chat() / provider.stream()
                    ↓
            返回 LLM 响应
```

## 文件协作与角色

| 文件 | 架构角色 | 职责 |
|------|----------|------|
| `base.py` | 接口定义 | 定义 LLMProvider 抽象基类 |
| `registry.py` | 核心实现 | Provider 注册和匹配逻辑 |
| `litellm_provider.py` | LiteLLM 适配 | LiteLLM 统一调用封装 |
| `custom_provider.py` | 自定义适配 | OpenAI 兼容 API 适配 |
| `transcription.py` | 语音转录 | Whisper 语音转文字 |
| `openai_codex_provider.py` | Codex 适配 | OpenAI Codex OAuth 登录 |

## 架构优缺点

### 优点
- ✅ **统一抽象**: 通过 LLMProvider 接口统一所有 LLM
- ✅ **可扩展**: 添加新 Provider 只需 2 步
- ✅ **自动匹配**: 根据模型名自动选择 Provider
- ✅ **多后端支持**: 支持 15+ LLM 后端

### 缺点
- ⚠️ **LiteLLM 依赖**: 大部分 Provider 依赖 LiteLLM
- ⚠️ **配置复杂**: 各 Provider 配置项不同
- ⚠️ **错误处理**: 不同 Provider 错误格式不同

### 改进建议
1. 统一错误处理机制
2. 增加 Provider 健康检查
3. 支持 Provider 级别的超时配置
