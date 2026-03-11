# nanobot 架构全景分析

> 生成时间：2026-03-10
> 分析工具： Architecture Analyzer

---

## 1. 工程架构全景

### 1.1 核心功能 + 架构目标

- **核心功能**: 超轻量个人 AI 助手
- **架构目标**: 极致轻量、易扩展、多渠道

### 1.2 整体架构分层
```
┌─────────────────────────────────────────────────────────────┐
│                      接口层 (Channels)                        │
│  Telegram │ Discord │ WhatsApp │ Feishu │ Slack │ Email   │
├─────────────────────────────────────────────────────────────┤
│                      业务层 (Agent)                           │
│  AgentLoop │ ContextBuilder │ MemoryStore │ SubagentManager │
├─────────────────────────────────────────────────────────────┤
│                      工具层 (Tools)                           │
│  Shell │ Filesystem │ Web │ MCP │ Spawn │ Cron │ Message   │
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

### 1.3 核心数据流
```
┌─────────────────────────────────────────────────────────────────────────┐
│                          用户消息处理流程                               │
├─────────────────────────────────────────────────────────────────────────┤
│  1. 用户发送消息到聊天平台 (Telegram/Discord/...)                        │
│                          ↓                                            │
│  2. Channel 接收消息， 转换为 InboundMessage                            │
│                          ↓                                            │
│  3. MessageBus.publish_inbound() 发布到队列                              │
│                          ↓                                            │
│  4. AgentLoop.process() 消费消息                                        │
│                          ↓                                            │
│  5. ContextBuilder 构建提示词 (历史 + 记忆 + 技能)               │
│                          ↓                                            │
│  6. LLMProvider.chat() 调用大模型                                    │
│                          ↓                                            │
│  7. 解析工具调用， ToolRegistry.get() 获取工具                        │
│                          ↓                                            │
│  8. Tool.execute() 执行工具                                          │
│                          ↓                                            │
│  9. 循环 5-7 直到无工具调用                                           │
│                          ↓                                            │
│  10. MessageBus.publish_outbound() 发布响应                            │
│                          ↓                                            │
│  11. Channel 接收 OutboundMessage， 转换为平台格式                      │
│                          ↓                                            │
│  12. 发送响应到聊天平台                                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 模块依赖关系

### 2.1 模块依赖图
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Channels   │────→│    Bus      │←────│   Agent     │
└─────────────┘     └─────────────┘     └─────────────┘
                                            │
                      ┌───────────────────┼───────────────────┐
                       ↓                   ↓                   ↓
              ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
              │  Providers  │     │   Session   │     │   Config     │
              └─────────────┘     └─────────────┘     └─────────────┘
                       │
                       ↓
              ┌─────────────┐
              │    Tools     │
              └─────────────┘
```

### 2.2 关键接口依赖

| 模块 | 依赖接口 | 被依赖模块 |
|------|----------|------------|
| AgentLoop | MessageBus | bus.queue |
| AgentLoop | LLMProvider | providers.base |
| AgentLoop | SessionManager | session.manager |
| AgentLoop | ContextBuilder | agent.context |
| AgentLoop | ToolRegistry | agent.tools.registry |
| Channel | MessageBus | bus.queue |
| Channel | SessionManager | session.manager |

---

## 3. 核心执行流程

### 3.1 正常流程
```
消息到达 → Channel.handle_message()
              ↓
         MessageBus.publish_inbound()
              ↓
         AgentLoop._process_message()
              ↓
         ContextBuilder.build()
              ↓
         LLMProvider.chat()
              ↓
         (工具调用?)
              ↓
         Tool.execute()
              ↓
         MessageBus.publish_outbound()
              ↓
         Channel.send_message()
```

### 3.2 异常流程
```
消息到达 → Channel.handle_message()
              ↓
         (认证失败?) → 返回错误消息
              ↓
         (超时?) → 返回超时消息
              ↓
         (异常?) → 记录日志， 返回错误消息
```

---

## 4. 核心文件架构角色

| 文件 | 数据流位置 | 架构角色 |
|------|-----------|----------|
| `agent/loop.py` | 核心处理节点 | Agent 循环引擎， 协调所有组件 |
| `agent/context.py` | 上下文构建 | 构建 LLM 提示词 |
| `agent/memory.py` | 记忆管理 | 管理长期记忆 |
| `bus/queue.py` | 消息路由 | 异步消息队列 |
| `bus/events.py` | 数据定义 | 消息数据结构 |
| `providers/registry.py` | LLM 调用 | Provider 匹配和注册 |
| `session/manager.py` | 会话持久化 | 会话生命周期管理 |
| `channels/telegram.py` | 消息入口 | Telegram 消息适配 |

---

## 5. 整体架构优缺点

### 5.1 优点
- ✅ **极致轻量**: 核心代码仅 ~4,000 行， 易于理解和扩展
- ✅ **高内聚**: 每个模块职责单一， 代码组织清晰
- ✅ **低耦合**: 通过 MessageBus 解耦 Channel 和 Agent
- ✅ **可扩展**: Provider Registry 模式支持快速添加新 LLM
- ✅ **多渠道支持**: 支持 10+ 聊天平台
- ✅ **MCP 支持**: 支持 Model Context Protocol 工具

### 5.2 缺点
- ⚠️ **缺乏接口抽象**: 直接依赖具体实现类， 测试性较差
- ⚠️ **无熔断机制**: 高并发下可用性风险
- ⚠️ **配置集中**: 修改需重启， 无热更新
- ⚠️ **文件存储**: 大量会话时文件管理效率低
- ⚠️ **无分布式支持**: 单机部署， 无水平扩展能力

### 5.3 架构改进建议

1. **引入依赖注入**: 解耦模块依赖， 提高可测试性
   ```python
   # 建议: 新增接口层
   class IAgentLoop(Protocol):
       async def process(self, message: InboundMessage) -> None
   ```

2. **新增熔断层**: 提升高并发可用性
   ```python
   # 建议: 使用 circuitbreaker
   from circuitbreaker import circuit
   @circuit(failure_threshold=5, recovery_timeout=30)
   async def call_llm(self, messages):
       ...
   ```

3. **配置中心化**: 支持热更新
   ```python
   # 建议: 支持 Nacos/Consul
   class ConfigWatcher:
       async def watch(self, path: str) -> None:
           # 监听配置变更， 热更新
   ```

4. **分布式会话存储**: 支持水平扩展
   ```python
   # 建议: 使用 Redis
   class RedisSessionManager(SessionManager):
       async def save(self, key: str, session: Session) -> None:
           await self.redis.set(f"session:{key}", session.json())
   ```

5. **增加审计日志**: 记录所有工具调用
   ```python
   # 建议: 增加审计中间件
   class AuditMiddleware:
       async def log_tool_call(self, tool: str, params: dict) -> None:
           logger.info(f"Tool call: {tool}", extra=params)
   ```

---

## 6. 扩展指南

### 6.1 添加新渠道
1. 在 `channels/` 目录创建新文件
2. 继承 `BaseChannel` 类
3. 实现 `handle_message()` 和 `send_message()` 方法
4. 在 `config/schema.py` 添加配置

### 6.2 添加新 Provider
1. 在 `providers/` 目录创建新文件
2. 继承 `LLMProvider` 类
3. 在 `registry.py` 添加 `ProviderSpec`
4. 在 `config/schema.py` 添加配置

### 6.3 添加新工具
1. 在 `agent/tools/` 目录创建新文件
2. 继承 `BaseTool` 类
3. 实现 `get_schema()` 和 `execute()` 方法
4. 在 `AgentLoop._register_default_tools()` 注册

---

*本报告由 Architecture Analyzer 自动生成*
