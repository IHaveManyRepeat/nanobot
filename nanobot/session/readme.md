# Session 模块
> 【架构分层: 支撑层 - 会话管理模块】

本目录实现 nanobot 的会话管理， 支持历史持久化和压缩

## 模块定位
- **架构层**: 支撑层
- **逻辑模块**: 会话管理
- **核心职责**: 管理 Agent 会话的生命周期， 包括创建、存储、加载、压缩历史记录

## 核心接口

### Session 数据结构
```python
@dataclass
class Session:
    key: str                    # 会话标识 (channel:user_id)
    messages: list[dict]        # 消息历史
    created_at: float           # 创建时间
    updated_at: float           # 更新时间
    metadata: dict              # 元数据 (如标题、标签)
```

### SessionManager 接口
```python
class SessionManager:
    def get_or_create(self, key: str) -> Session
    def add_message(self, key: str, message: dict) -> None
    def get_messages(self, key: str, limit: int = None) -> list[dict]
    def save(self, key: str) -> None
    def consolidate(self, key: str) -> None
```

## 核心流程

### 消息处理流程
```
消息到达 → get_or_create(session_key)
                ↓
        add_message() 追加消息
                ↓
        检查是否需要压缩
                ↓
        (如果需要) consolidate() 压缩历史
                ↓
        save() 持久化
```

### 历史压缩流程
```
触发条件: messages > memory_window
                ↓
        保留最近的 N 条消息
                ↓
        调用 LLM 生成摘要
                ↓
        替换历史为摘要
```

## 文件协作与角色

| 文件 | 架构角色 | 职责 |
|------|----------|------|
| `manager.py` | 核心实现 | 会话生命周期管理、历史压缩 |

## 架构优缺点

### 优点
- ✅ **持久化**: 会话保存到 JSON 文件，重启后可恢复
- ✅ **压缩**: 支持历史压缩，减少 token 消耗
- ✅ **线程安全**: 使用锁保护并发访问
- ✅ **简单**: 单文件实现，易于理解

### 缺点
- ⚠️ **文件存储**: 大量会话时文件管理效率低
- ⚠️ **压缩延迟**: 压缩时需要调用 LLM，有延迟
- ⚠️ **内存占用**: 所有会话都在内存中

### 改进建议
1. 支持数据库存储 (如 SQLite)
2. 增加 LRU 缓存限制内存占用
3. 支持异步压缩避免阻塞
