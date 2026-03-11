# Bus 模块
> 【架构分层: 基础层 - 消息路由模块】

本目录实现 nanobot 的消息总线， 是系统的通信枢纽

## 模块定位
- **架构层**: 基础层
- **逻辑模块**: 消息路由
- **核心职责**: 宍现异步消息队列， 解耦消息生产者 (Channel) 和消费者 (Agent)

## 核心流程
```
Channel (生产者) → MessageBus → AgentLoop (消费者)
                                    ↓
Channel (消费者) ← MessageBus ← AgentLoop (生产者)
```

## 核心接口

### InboundMessage
```python
@dataclass
class InboundMessage:
    channel: str           # 来源渠道 (telegram, discord, ...)
    user_id: str           # 用户标识
    content: str           # 消息内容 (文本或 URL)
    metadata: dict         # 元数据 (平台特定信息)
    timestamp: float       # 时间戳
```

### OutboundMessage
```python
@dataclass
class OutboundMessage:
    channel: str           # 目标渠道
    user_id: str           # 用户标识
    content: str           # 响应内容 (文本或文件路径)
    metadata: dict         # 元数据 (如 reply_to, file_url)
```

### MessageBus
```python
class MessageBus:
    async def publish_inbound(self, msg: InboundMessage) -> None:
        """发布入站消息到队列，通知所有订阅者"""

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """发布出站消息，通知所有订阅者"""

    async def subscribe_inbound(self, handler: Callable[[InboundMessage], Awaitable[None]]) -> None:
        """订阅入站消息"""

    async def subscribe_outbound(self, handler: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """订阅出站消息"""
```

## 文件协作与角色

| 文件 | 架构角色 | 职责 |
|------|----------|------|
| `events.py` | 数据定义 | 定义入站/出站消息数据结构 |
| `queue.py` | 核心实现 | 实现异步消息队列和订阅机制 |

## 架构优缺点

### 优点
- ✅ **解耦**: 生产者和消费者完全解耦， 互不依赖
- ✅ **异步**: 基于 asyncio.Queue， 支持高并发
- ✅ **多订阅者**: 支持多个订阅者同时处理消息
- ✅ **简单**: 最小化实现， 易于理解

### 缺点
- ⚠️ **无持久化**: 消息只在内存中， 重启丢失
- ⚠️ **无确认机制**: 消息发布后无法确认是否被处理
- ⚠️ **无重试**: 处理失败后消息丢失
- ⚠️ **无优先级**: 所有消息优先级相同

### 改进建议
1. 增加消息确认机制 (ACK)
2. 支持消息重试和死信队列
3. 增加消息优先级支持
4. 可选的消息持久化
