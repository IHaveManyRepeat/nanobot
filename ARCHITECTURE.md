# nanobot 架构分析报告

> 生成时间: 2026-03-10
> 分析工具: Architecture Analyzer

---

## 📚 详细文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| **架构全景** | [OVERVIEW.md](./OVERVIEW.md) | 工程级架构全景分析 |
| **文件清单** | [FILE_INVENTORY.md](./FILE_INVENTORY.md) | 架构化文件清单 |
| **Agent 模块** | [nanobot/agent/readme.md](./nanobot/agent/readme.md) | Agent 核心模块文档 |
| **Channels 模块** | [nanobot/channels/readme.md](./nanobot/channels/readme.md) | 多渠道适配文档 |
| **Bus 模块** | [nanobot/bus/readme.md](./nanobot/bus/readme.md) | 消息总线文档 |
| **Session 模块** | [nanobot/session/readme.md](./nanobot/session/readme.md) | 会话管理文档 |
| **Providers 模块** | [nanobot/providers/readme.md](./nanobot/providers/readme.md) | LLM 提供者文档 |
| **Config 模块** | [nanobot/config/readme.md](./nanobot/config/readme.md) | 配置管理文档 |
| **Tools 模块** | [nanobot/agent/tools/readme.md](./nanobot/agent/tools/readme.md) | 工具层文档 |

---

## 1. 项目定位

**超轻量个人 AI 助手** — 仅 ~4,000 行核心代码实现完整 Agent 功能，比 Clawdbot 小 99%。

- **语言**： Python
- **代码规模**： ~4,000 行核心代码
- **适用场景**： 个人助手、快速原型

---

## 2. 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                      接口层 (Channels)                        │
│  Telegram │ Discord │ WhatsApp │ Feishu │ Slack │ Email   │
├─────────────────────────────────────────────────────────────┤
│                      业务层 (Agent)                           │
│  AgentLoop │ ContextBuilder │ MemoryStore │ SubagentManager │
├─────────────────────────────────────────────────────────────┤
│                      工具层 (Tools)                           │
│  Shell │ Filesystem │ Web │ MCP │ Spawn │ Cron │ Message    │
├─────────────────────────────────────────────────────────────┤
│                      支撑层 (Infrastructure)                  │
│  Providers │ Session │ Bus │ Config │ Cron │ Heartbeat      │
└─────────────────────────────────────────────────────────────┘
```

**每层职责与边界**:

| 层级 | 职责 | 边界 |
|------|------|------|
| 接口层 | 消息接入/接出， 平台适配 | 不包含业务逻辑 |
| 业务层 | Agent 循环， 上下文构建， 记忆管理 | 不直接与平台交互 |
| 工具层 | 执行具体操作 | 不包含决策逻辑 |
| 支撑层 | LLM 调用， 会话存储， 配置管理 | 不包含业务逻辑 |

---

## 3. 架构优缺点

### 优点
- ✅ **极致轻量**: 核心代码仅 ~4,000 行， 易于理解和扩展
- ✅ **高内聚**: 每个模块职责单一（如 `loop.py` 只负责代理循环）
- ✅ **低耦合**: 通过 `MessageBus` 解耦 Channel 和 Agent
- ✅ **可扩展**: Provider Registry 模式支持快速添加新 LLM
- ✅ **多渠道支持**: 支持 10+ 聊天平台

### 缺点
- ⚠️ **缺乏接口抽象**: 直接依赖具体实现， 测试性较差
- ⚠️ **无熔断机制**: 高并发下可用性风险
- ⚠️ **配置集中**: 修改需重启， 无热更新

---

## 4. 改进建议

1. 引入依赖注入框架解耦模块依赖
2. 新增熔断层（如 circuitbreaker）提升可用性
3. 实现配置中心化支持热更新

---

## 5. 技术特性

| 维度 | 说明 |
|------|------|
| **语言** | Python |
| **规模** | 极小 (4k行) |
| **分层** | 4层 |
| **并发模型** | asyncio |
| **热插拔** | 技能 |
| **传输协议** | 多渠道 |
| **持久化** | 文件 |

---

*本报告由 Architecture Analyzer 自动生成*
