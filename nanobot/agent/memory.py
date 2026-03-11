"""
Memory System - 长期记忆系统

================================================================================
【架构分层：业务层 - 记忆管理模块】

【核心作用】
实现长期记忆系统，解决 LLM 上下文窗口限制问题。

【为什么需要这个功能？】

问题背景：
  LLM 有 token 限制（如 Claude 200k tokens），当对话历史过长时：
  - 早期消息会被截断丢弃
  - 用户之前提供的关键信息（如项目技术栈、偏好设置等）会丢失
  - 每次新会话都从零开始，无法延续之前的上下文

解决方案：
  1. 当对话历史接近窗口限制时（memory_window=100条），触发压缩
  2. 调用 LLM 生成两类内容：
     - history_entry: 历史条目摘要（按时间线记录）
     - memory_update: 长期记忆更新（主题式组织）
  3. 保存到文件系统持久化
  4. 清空会话历史，但保留记忆上下文

【文件结构】
  workspace/
  └── .nanobot/
      └── sessions/
          └── {channel}:{user_id}/
              ├── session.json     # 会话历史（会被清空）
              ├── history.md       # 历史摘要（按时间线）
              └── memory.md        # 长期记忆（主题式）

【核心方法】
  - append_history(entry): 追加历史摘要条目
  - write_long_term(content): 写入/更新长期记忆文档
  - consolidate(session, provider): 压缩会话历史 → 生成记忆
  - get_context(): 获取记忆上下文（用于构建提示词）

【对比：有/无记忆系统】
┌─────────────────┬─────────────────────┬─────────────────────┐
│ 场景            │ 无记忆系统           │ 有记忆系统           │
├─────────────────┼─────────────────────┼─────────────────────┤
│ 长对话          │ 早期消息丢失         │ 关键信息保留         │
│ 跨会话          │ 每次从零开始         │ 延续之前上下文       │
│ 用户偏好        │ 每次重新告知         │ 自动记住             │
│ 项目上下文      │ 容易遗忘             │ 持久保存             │
└─────────────────┴─────────────────────┴─────────────────────┘

【依赖模块】
  - nanobot.providers.base.LLMProvider: 调用大模型生成记忆
  - nanobot.session.manager.Session: 获取会话历史
  - nanobot.utils.helpers: 文件系统操作

【异常边界】
  - 文件读写失败: 记录日志，返回空内容
  - LLM 调用失败: 记录日志，返回 False
  - 工具调用格式错误: 记录警告，返回 False

【性能/并发】
  - 文件读写使用异步 IO
  - 记忆压缩在后台异步执行，不阻塞主循环
================================================================================
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            # 这个工具让 LLM 决定哪些信息值得记住
            # LLM 会返回两个参数：
            # - history_entry: 历史条目摘要（带时间戳，用于搜索）
            # - memory_update: 长期记忆更新（主题式，用于构建上下文）
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class MemoryStore:
    """
    双层记忆存储系统

    【架构角色】
    业务层 - 记忆管理器，负责持久化 Agent 的长期记忆

    【存储结构】
    workspace/memory/
    ├── MEMORY.md    # 长期记忆（主题式，如项目信息、用户偏好）
    └── HISTORY.md   # 历史记录（时间线，用于搜索）

    【使用场景】
    1. AgentLoop 检测到会话历史接近 memory_window 时触发压缩
    2. /new 命令执行时归档所有历史
    3. ContextBuilder 构建提示词时读取长期记忆

    【设计原则】
    - 让 LLM 自己决定哪些信息值得记住（通过 save_memory 工具）
    - 历史记录按时间线组织，支持 grep 搜索
    - 长期记忆按主题组织，用于构建上下文
    """

    def __init__(self, workspace: Path):
        """
        初始化记忆存储

        Args:
            workspace: 工作空间路径，记忆文件将保存在 workspace/memory/ 目录下
        """
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"  # 长期记忆文件
        self.history_file = self.memory_dir / "HISTORY.md"  # 历史记录文件

    def read_long_term(self) -> str:
        """
        读取长期记忆内容

        Returns:
            长期记忆的 Markdown 内容，文件不存在时返回空字符串
        """
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """
        写入/更新长期记忆

        Args:
            content: 长期记忆的 Markdown 内容（通常由 LLM 生成）
        """
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        """
        追加历史记录条目

        Args:
            entry: 历史条目文本（建议以 [YYYY-MM-DD HH:MM] 开头）
        """
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        """
        获取记忆上下文，用于构建 Agent 提示词

        Returns:
            格式化的记忆上下文字符串，长期记忆为空时返回空字符串
        """
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """
        压缩会话历史，生成长期记忆

        核心流程：
        1. 确定需要压缩的消息范围（跳过最近的一半消息）
        2. 将历史消息格式化为带时间戳的文本
        3. 调用 LLM 执行 save_memory 工具
        4. 解析工具调用结果，保存 history_entry 和 memory_update
        5. 更新 session.last_consolidated 标记

        Args:
            session: 会话对象，包含消息历史
            provider: LLM 提供者，用于调用模型
            model: 模型名称
            archive_all: 是否归档全部消息（/new 命令时为 True）
            memory_window: 记忆窗口大小，决定保留多少最近消息

        Returns:
            True: 成功（包括无需压缩的情况）
            False: 失败（LLM 未调用工具或格式错误）

        性能说明：
            - 压缩操作在后台异步执行，不阻塞主循环
            - 单次压缩约需 1-3 秒（取决于消息数量）
        """
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated : -keep_count]
            if not old_messages:
                return True
            logger.info(
                "Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count
            )

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(
                f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}"
            )

        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
            # Some providers return arguments as a JSON string instead of dict
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                logger.warning(
                    "Memory consolidation: unexpected arguments type {}", type(args).__name__
                )
                return False

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info(
                "Memory consolidation done: {} messages, last_consolidated={}",
                len(session.messages),
                session.last_consolidated,
            )
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
