# Agent 模块

> 【架构分层：业务层 - Agent 核心模块】

本目录实现 nanobot 的核心 Agent 逻辑，是 是整个系统的大脑，负责协调 LLM 调用、工具执行和消息路由。

## 模块定位

- **架构层**：业务层
- **逻辑模块**： Agent 核心
- **核心职责**： 实现 AI Agent 的核心循环逻辑，承接消息总线的入站消息，调用 LLM Provider 获取模型响应，执行工具调用，将结果返回消息总线

## 核心流程

```
消息总线 → AgentLoop.process()
              ↓
        ContextBuilder.build_context()  // 构建提示词
              ↓
        LLMProvider.chat()             // 调用大模型
              ↓
        ToolRegistry.execute()       // 执行工具
              ↓
        MessageBus.publish()           // 发送响应
```

## 关键接口

### 对外暴露接口

| 接口 | 方法 | 职责 |
|------|------|------|
| `AgentLoop` | `process()` | 处理入站消息，执行 Agent 循环 |
| `AgentLoop` | `run()` | 启动 Agent 循环，主入口 |
| `ContextBuilder` | `build_context()` | 构建发送给 LLM 的上下文 |

### 依赖的其他模块接口
| 模块 | 接口 | 说明 |
|------|------|------|
| `MessageBus` | `publish_inbound()` | 接收用户消息 |
| `MessageBus` | `publish_outbound()` | 发送响应消息 |
| `LLMProvider` | `chat()` | 调用大模型 API |
| `ToolRegistry` | `execute()` | 执行工具 |
| `SessionManager` | `get()` | 获取会话历史 |

| `MemoryStore` | `get()` | 获取记忆信息 |

## 文件协作与角色

| 文件 | 架构角色 | 说明 |
|------|------|------|
| `loop.py` | 核心业务 | Agent 主循环，消息处理 |
| `context.py` | 上下文构建 | 提示词组装、记忆管理 |
| `memory.py` | 记忆存储 | 持久化记忆、 短期/长期 |
| `skills.py` | 技能加载 | 从文件加载技能定义 |
| `subagent.py` | 子代理管理 | 后台任务执行 |
| `tools/*.py` | 工具实现 | 各种工具的具体实现 |

## 架构层面优缺点
### 优点
- ✅ **高内聚**：所有 Agent 核心逻辑集中在该目录
- ✅ **单一职责**：每个文件职责清晰（loop 负责循环, context 负责上下文等)
- ✅ **可测试性**：核心逻辑可依赖注入，易于单元测试
- ✅ **可扩展性**：通过 ToolRegistry 支持热插拔工具

### 缺点
- ⚠️ **缺乏接口抽象**：直接依赖具体实现类，更换实现需修改多处代码
- ⚠️ **并发控制**: `_processing_lock` 是简单的互斥锁，高并发下可能成为瓶颈
- ⚠️ **异常处理分散**: 异常处理逻辑分散在各处,缺乏统一策略
### 改进建议
1. 新增 `AgentService` 接口层，解耦业务逻辑与实现
2. 引入分布式锁机制处理高并发场景
3. 统一异常处理策略，使用中间件模式
