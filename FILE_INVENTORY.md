# nanobot 架构化文件清单

> 生成时间：2026-03-10
> 分析工具: Architecture Analyzer

---

## 📁 接口层 (Channels)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| base.py | `nanobot/channels/base.py` | 接口定义 | **高** | 定义 Channel 基类和消息格式 |
| manager.py | `nanobot/channels/manager.py` | 核心业务 | **高** | 管理渠道的启动和停止 |
| telegram.py | `nanobot/channels/telegram.py` | 平台适配 | 中 | 实现 Telegram Bot API |
| discord.py | `nanobot/channels/discord.py` | 平台适配 | 中 | 实现 Discord Bot Gateway |
| feishu.py | `nanobot/channels/feishu.py` | 平台适配 | 中 | 实现飞书 WebSocket 长连接 |
| slack.py | `nanobot/channels/slack.py` | 平台适配 | 中 | 实现 Slack Socket Mode |
| whatsapp.py | `nanobot/channels/whatsapp.py` | 平台适配 | 中 | 实现 WhatsApp Web API |
| email.py | `nanobot/channels/email.py` | 平台适配 | 中 | 实现 Email IMAP/SMTP |
| matrix.py | `nanobot/channels/matrix.py` | 平台适配 | 中 | 实现 Matrix 协议 |
| dingtalk.py | `nanobot/channels/dingtalk.py` | 平台适配 | 中 | 实现钉钉 Stream Mode |
| qq.py | `nanobot/channels/qq.py` | 平台适配 | 中 | 实现 QQ Bot API |
| mochat.py | `nanobot/channels/mochat.py` | 平台适配 | 中 | 实现 Mochat WebSocket |

---

## 📁 业务层 (Agent)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| loop.py | `nanobot/agent/loop.py` | 核心业务 | **高** | Agent 核心循环， 接收消息、 调用 LLM、 执行工具 |
| context.py | `nanobot/agent/context.py` | 核心业务 | **高** | 构建 LLM 提示词， 整合历史、 记忆、 技能 |
| memory.py | `nanobot/agent/memory.py` | 核心业务 | **高** | 管理长期记忆， 存储和检索重要信息 |
| skills.py | `nanobot/agent/skills.py` | 核心业务 | 中 | 加载和管理技能 |
| subagent.py | `nanobot/agent/subagent.py` | 核心业务 | 中 | 管理子 Agent， 后台任务执行 |

---

## 📁 工具层 (Tools)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| base.py | `nanobot/agent/tools/base.py` | 接口定义 | **高** | 定义 BaseTool 抽象基类 |
| registry.py | `nanobot/agent/tools/registry.py` | 核心业务 | **高** | 工具注册和管理 |
| filesystem.py | `nanobot/agent/tools/filesystem.py` | 核心业务 | **高** | 文件读写、 编辑、 列表 |
| shell.py | `nanobot/agent/tools/shell.py` | 核心业务 | **高** | Shell 命令执行 |
| web.py | `nanobot/agent/tools/web.py` | 工具类 | 中 | Web 搜索和获取 |
| message.py | `nanobot/agent/tools/message.py` | 工具类 | 中 | 发送消息到渠道 |
| spawn.py | `nanobot/agent/tools/spawn.py` | 工具类 | 中 | 创建和管理子 Agent |
| cron.py | `nanobot/agent/tools/cron.py` | 工具类 | 中 | 定时任务管理 |
| mcp.py | `nanobot/agent/tools/mcp.py` | 核心业务 | **高** | MCP 协议集成 |

---

## 📁 支撑层 - 消息总线 (Bus)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| events.py | `nanobot/bus/events.py` | 接口定义 | **高** | 定义入站/出站消息数据结构 |
| queue.py | `nanobot/bus/queue.py` | 核心业务 | **高** | 实现异步消息队列和订阅机制 |

---

## 📁 支撑层 - LLM 提供者 (Providers)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| base.py | `nanobot/providers/base.py` | 接口定义 | **高** | 定义 LLMProvider 抽象基类 |
| registry.py | `nanobot/providers/registry.py` | 核心业务 | **高** | Provider 注册和匹配逻辑 |
| litellm_provider.py | `nanobot/providers/litellm_provider.py` | 核心业务 | **高** | LiteLLM 统一调用封装 |
| custom_provider.py | `nanobot/providers/custom_provider.py` | 工具类 | 中 | OpenAI 兼容 API 适配 |
| transcription.py | `nanobot/providers/transcription.py` | 工具类 | 中 | Whisper 语音转文字 |
| openai_codex_provider.py | `nanobot/providers/openai_codex_provider.py` | 工具类 | 中 | OpenAI Codex OAuth 登录 |

---

## 📁 支撑层 - 会话管理 (Session)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| manager.py | `nanobot/session/manager.py` | 核心业务 | **高** | 会话创建、 查询、 持久化、 压缩 |

---

## 📁 支撑层 - 配置管理 (Config)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| schema.py | `nanobot/config/schema.py` | 接口定义 | **高** | 定义配置数据结构 |
| loader.py | `nanobot/config/loader.py` | 核心业务 | **高** | 加载配置文件 |

---

## 📁 支撑层 - 定时任务 (Cron)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| service.py | `nanobot/cron/service.py` | 核心业务 | 中 | 定时任务调度服务 |
| types.py | `nanobot/cron/types.py` | 接口定义 | 中 | 定时任务类型定义 |

---

## 📁 支撑层 - 心跳 (Heartbeat)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| service.py | `nanobot/heartbeat/service.py` | 核心业务 | 中 | 周期性唤醒 Agent 执行任务 |

---

## 📁 接口层 - CLI (cli)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| commands.py | `nanobot/cli/commands.py` | 接口定义 | 中 | 定义 CLI 命令 |

---

## 📁 技能层 (Skills)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| clawhub/SKILL.md | `nanobot/skills/clawhub/SKILL.md` | 技能定义 | 低 | ClawHub 技能商店 |
| cron/SKILL.md | `nanobot/skills/cron/SKILL.md` | 技能定义 | 低 | 定时任务技能 |
| github/SKILL.md | `nanobot/skills/github/SKILL.md` | 技能定义 | 低 | GitHub 集成技能 |
| memory/SKILL.md | `nanobot/skills/memory/SKILL.md` | 技能定义 | 低 | 记忆管理技能 |
| weather/SKILL.md | `nanobot/skills/weather/SKILL.md` | 技能定义 | 低 | 天气查询技能 |

---

## 📁 模板层 (Templates)

| 文件 | 物理路径 | 文件类型 | 核心度 | 架构职责 |
|------|----------|----------|--------|----------|
| SOUL.md | `nanobot/templates/SOUL.md` | 配置 | 低 | Agent 人格模板 |
| USER.md | `nanobot/templates/USER.md` | 配置 | 低 | 用户信息模板 |
| TOOLS.md | `nanobot/templates/TOOLS.md` | 配置 | 低 | 工具说明模板 |
| HEARTBEAT.md | `nanobot/templates/HEARTBEAT.md` | 配置 | 低 | 心跳任务模板 |

---

*本清单由 Architecture Analyzer 自动生成*
