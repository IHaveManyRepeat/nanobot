"""
Session Management - 会话管理系统

================================================================================
【架构分层：支撑层 - 会话管理模块】

【核心作用】
实现会话管理系统，负责对话历史的持久化存储和生命周期管理。

【为什么需要这个功能？】

问题背景：
  没有会话管理时：
  - 对话历史只存在内存中，服务重启后丢失
  - 无法恢复之前的对话上下文
  - 用户需要重新描述需求和背景

解决方案：
  1. 每条消息实时写入磁盘 (JSONL 格式)
  2. 服务重启后自动加载历史会话
  3. 支持跨渠道会话隔离 (每个 channel:chat_id 独立)
  4. 与记忆系统协作，标记已压缩的消息

【文件结构】
  workspace/
  └── sessions/
      ├── telegram_user123.jsonl    # Telegram 用户 123 的会话
      ├── discord_user456.jsonl    # Discord 用户 456 的会话
      └── cli_direct.jsonl         # CLI 直接会话

【核心类】
  - Session: 会话数据结构，  - SessionManager: 会话生命周期管理

【核心方法】
  - get_or_create(key): 获取或创建会话
  - add_message(role, content): 追加消息
  - get_history(max_messages): 获取历史（用于 LLM）
  - save(session): 保存会话到磁盘
  - invalidate(key): 从内存缓存中移除

【与 Memory 系统的关系】
  Session 负责存储完整的对话历史
  Memory 负责压缩历史生成长期记忆
  两者通过 last_consolidated 字段协作

【设计原则】
  1. Append-Only: 消息只追加不修改，保证历史完整性
  2. 按需加载: 内存缓存 + 磁盘持久化
  3. 多渠道隔离: 每个 channel:chat_id 独立会话

【依赖模块】
  - nanobot.utils.helpers: 文件系统操作

【异常边界】
  - 文件读写失败: 记录警告，返回空会话
  - JSON 解析失败: 记录警告，返回空会话

【性能/并发】
  - 使用内存缓存减少磁盘读取
  - 保存操作同步执行，确保数据一致性
================================================================================
"""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir, safe_filename


@dataclass
class Session:
    """
    会话数据结构

    存储单个会话的完整状态，包括消息历史、元数据和压缩标记。

    设计原则：
    - Append-Only: 消息只追加不修改，保证历史完整性
    - 与 MemoryStore 协作: last_consolidated 标记已压缩的消息

    属性说明：
    - key: 会话唯一标识 (格式: channel:chat_id)
    - messages: 消息历史列表 (每条消息包含 role, content, timestamp 等)
    - created_at: 会话创建时间
    - updated_at: 最后更新时间
    - metadata: 扩展元数据 (如会话标题、标签等)
    - last_consolidated: 已压缩消息数 (用于增量压缩)
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # 已压缩消息数，用于增量压缩

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """
        追加消息到会话历史

        Args:
            role: 消息角色 (user/assistant/tool)
            content: 消息内容
            **kwargs: 扩展字段 (如 tool_calls, tool_call_id, name)

        注意：此方法不触发持久化，需手动调用 SessionManager.save()
        """
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """
        获取未压缩的消息历史，用于构建 LLM 提示词

        核心逻辑：
        1. 从 last_consolidated 开始截取 (跳过已压缩的)
        2. 保留最近 max_messages 条
        3. 丢弃开头的非用户消息 (避免孤立的 tool_result 块)

        Args:
            max_messages: 最大返回消息数

        Returns:
            格式化的消息列表，仅包含 LLM 需要的字段
        """
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]

        # 丢弃开头的非用户消息，避免孤立的 tool_result 块
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for m in sliced:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        """
        清空会话历史，重置为初始状态

        使用场景：
        - 用户执行 /new 命令开始新对话
        - 需要重置会话状态时
        """
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    会话管理器 - 负责会话的创建、加载、保存和缓存

    职责：
    1. 管理会话的生命周期（创建、加载、保存、删除）
    2. 维护内存缓存，减少磁盘读取
    3. 支持旧版本会话迁移

    文件存储格式 (JSONL)：
    ┌─────────────────────────────────────────────────────────────────┐
    │ 第一行: 元数据 {"_type": "metadata", "key": "...", ...}       │
    │ 第二行: 消息1 {"role": "user", "content": "...", ...}          │
    │ 第三行: 消息2 {"role": "assistant", "content": "...", ...}     │
    │ ...                                                            │
    └─────────────────────────────────────────────────────────────────┘

    存储路径：
    workspace/.nanobot/sessions/{channel}_{chat_id}.jsonl

    内存缓存：
    - 使用 dict 缓存活跃会话
    - 避免重复磁盘读取
    - 保存时同步更新缓存
    """

    def __init__(self, workspace: Path):
        """
        初始化会话管理器

        Args:
            workspace: 工作空间路径，会话文件将存储在 workspace/.nanobot/sessions/
        """
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = Path.home() / ".nanobot" / "sessions"
        self._cache: dict[str, Session] = {}  # 内存缓存

    def _get_session_path(self, key: str) -> Path:
        """
        获取会话文件路径

        Args:
            key: 会话标识 (格式: channel:chat_id)

        Returns:
            会话文件的完整路径
        """
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """
        获取旧版本会话路径 (~/.nanobot/sessions/)

        用于迁移旧版本会话到新位置
        """
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        获取现有会话或创建新会话

        查找顺序：
        1. 内存缓存
        2. 磁盘文件
        3. 创建新会话

        Args:
            key: 会话标识 (格式: channel:chat_id)

        Returns:
            Session 对象
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """
        从磁盘加载会话

        加载流程：
        1. 检查新路径是否存在
        2. 如果不存在，检查旧路径并迁移
        3. 解析 JSONL 文件

        Args:
            key: 会话标识

        Returns:
            Session 对象，加载失败返回 None
        """
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        # 第一行是元数据
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        # 后续行是消息
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """
        保存会话到磁盘

        保存流程：
        1. 写入元数据行（第一行）
        2. 逐行写入消息
        3. 更新内存缓存

        Args:
            session: 要保存的 Session 对象
        """
        path = self._get_session_path(session.key)

        with open(path, "w", encoding="utf-8") as f:
            # 第一行：元数据
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            # 后续行：消息
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """
        从内存缓存中移除会话

        使用场景：
        - /new 命令后，清空旧会话缓存
        - 需要强制重新加载会话时

        Args:
            key: 会话标识
        """
        self._cache.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        列出所有会话

        Returns:
            会话信息列表，按更新时间倒序排列

        每个会话包含：
        - key: 会话标识
        - created_at: 创建时间
        - updated_at: 更新时间
        - path: 文件路径
        """
        sessions = []

        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # 只读取元数据行
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = data.get("key") or path.stem.replace("_", ":", 1)
                            sessions.append({
                                "key": key,
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path)
                            })
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
