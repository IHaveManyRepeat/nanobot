# Channels 模块

> 【架构分层：接口层 - 多渠道适配模块】

本目录实现 nanobot 的多渠道消息接入适配, 支持 10+ 主流聊天平台

## 模块定位

- **架构层**: 接口层
- **逻辑模块**: 多渠道适配
- **核心职责**: 审阅各聊天平台的消息，转换为统一的消息格式， 发布到消息总线； 同时将 Agent 的响应转换为各平台的特定格式发送

## 支持渠道

| 渠道 | 协议 | 特点 |
|------|------|------|
| Telegram | Bot API | 最简单接入，适合个人使用 |
| Discord | Bot Gateway | 支持服务器、群组消息 |
| Feishu | WebSocket | 国内企业，支持富文本 |
| Slack | Socket Mode | 企业协作，支持 Block Kit |
| WhatsApp | Web API | 个人通讯，需要扫码登录 |
| Email | IMAP/SMTP | 异步消息，支持附件 |
| Matrix | Client-Server | 去中心化，支持 E2EE |
| DingTalk | Stream Mode | 国内企业，支持富文本 |
| QQ | Bot API | 国内社交平台 |
| Mochat | WebSocket | Claw IM，私有部署 |

## 核心接口

### 入站消息处理
```
InboundMessage {
    channel: str,      # 来源渠道
    user_id: str,      # 用户标识
    content: str,      # 消息内容
    metadata: dict,   # 平台特定元数据
}
```

### 出站消息处理
```
OutboundMessage {
    channel: str,      # 目标渠道
    user_id: str,      # 用户标识
    content: str,      # 响应内容
    metadata: dict,   # 平台特定元数据
}
```

## 文件协作与角色

| 文件 | 架构角色 | 职责 |
|------|----------|------|
| `base.py` | 接口定义 | 定义 Channel 基类和消息格式 |
| `manager.py` | 生命周期管理 | 管理渠道的启动和停止 |
| `telegram.py` | Telegram 适配 | 实现 Telegram Bot API |
| `discord.py` | Discord 适配 | 实现 Discord Bot Gateway |
| `feishu.py` | 飞书适配 | 实现飞书 WebSocket 长连接 |
| `slack.py` | Slack 适配 | 实现 Slack Socket Mode |
| `mochat.py` | Mochat 适配 | 实现 Mochat WebSocket |

## 架构优缺点

### 优点
- ✅ **多渠道支持**: 支持 10+ 主流聊天平台
- ✅ **统一抽象**: 通过 `BaseChannel` 统一消息格式
- ✅ **可扩展**: 添加新渠道只需实现 `BaseChannel` 接口
- ✅ **解耦**: 通过 MessageBus 与 Agent 层解耦

### 缺点
- ⚠️ **平台差异**: 各平台消息格式差异大，适配复杂
- ⚠️ **依赖管理**: 各渠道依赖独立的 SDK
- ⚠️ **测试覆盖**: 需要针对每个渠道编写集成测试
