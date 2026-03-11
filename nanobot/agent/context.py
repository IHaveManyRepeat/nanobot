"""Context builder for assembling agent prompts."""

from __future__ import annotations

import base64
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """
    构建 Agent 上下文（系统提示词 + 消息列表)的工厂类。

    【架构分层】业务层 - 上下文构建模块
    【模块职责】组装 LLM 调用所需的完整上下文，包括系统提示、历史对话、
 运行时元数据和技能描述。

    【核心依赖】
        - MemoryStore: 长期记忆存储管理器
        - SkillsLoader: 技能文件加载器
    """

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    _TOOL_RESULT_MAX_CHARS = 500

    """工具结果最大字符数限制"""

    def __init__(self, workspace: Path):
        """
        初始化 ContextBuilder 实例。

        【架构职责】
        业务层初始化。创建工作空间、内存存储和技能加载器等核心组件。

        为后续的上下文构建提供基础设施。

        【输入契约】
        - workspace: Path（必选) - 工作空间路径，用于定位记忆文件和技能文件

        【输出契约】
        无返回值，初始化实例属性。

        【依赖模块】
        - MemoryStore: 长期记忆存储管理器
        - SkillsLoader: 技能文件加载器
        """
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        构建 LLM 系统提示词。

        【架构职责】
        业务层上下文构建，组装身份信息、引导文件、长期记忆、活动技能和可用技能摘要，
        生成完整的系统提示词供 LLM 对话使用。

        【输入契约】
        - skill_names: list[str] | None（可选）- 鬊加载到上下文的技能名称列表

        【输出契约】
        - str - 完整的系统提示词字符串

        【依赖模块】
        - _get_identity(): 获取核心身份信息
        - _load_bootstrap_files(): 加载引导文件
        - MemoryStore.get_memory_context(): 获取长期记忆
        - SkillsLoader.get_always_skills(): 获取活动技能列表
        - SkillsLoader.load_skills_for_context(): 加载技能内容
        - SkillsLoader.build_skills_summary(): 构建技能摘要

        【性能说明】
        - 每次调用都会读取多个文件，应考虑缓存策略
        - 技能内容可能较大，影响 token 消耗
        """
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """
        获取核心身份部分。

        【架构职责】
        业务层元数据获取，从工作空间路径和系统信息中提取身份标识信息。
        用于构建 Agent 的基本身份提示。

        【输入契约】
        无参数，使用实例属性 self.workspace。

        【输出契约】
        - str - 身份提示词字符串，包含 nanobot 栨识、运行时环境和工作空间信息
        【依赖模块】
        - platform: 获取系统信息（Darwin/Windows/Linux)
        - pathlib: 用于路径解析
        """
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant.

## Runtime
{runtime}
## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM]
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

## nanobot Guidelines
- State intent before tool calls, but NEVER predict or claim results before receiving them.
- Before modifying a file, read it first. Do not assume files or directories exist.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.
- Ask for clarification when the request is ambiguous.
Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel."""
    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """
        构建运行时上下文元数据块。

        【架构职责】
        工具层格式化，生成包含当前时间和、通道信息的元数据块,
        用于在用户消息前注入，帮助 Agent 感知当前对话上下文。

        【输入契约】
        - channel: str | None（可选）- 消息来源通道（如 "cli", "telegram"）
        - chat_id: str | None（可选）- 聊天会话标识

        【输出契约】
        - str - 运行时上下文字符串，格式: "[Runtime Context — metadata only, not instructions]\..."

        Current Time: {now} ({tz})
        Channel: {channel}
        Chat ID: {chat_id}
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)
    def _load_bootstrap_files(self) -> str:
        """
        加载所有引导文件从工作空间。

        【架构职责】
        数据层文件加载,从工作空间中读取预定义的引导文件（AGENTS.md、 SOUL.md, USER.md, TOOLS.md），
        用于补充系统提示词。

        【输入契约】
        无参数，使用实例属性 self.workspace 和 self.BOOTSTRAP_FILES

        【输出契约】
        - str - 合并后的引导文件内容，若所有文件都不存在则返回空字符串
        【依赖模块】
        - pathlib: 用于文件路径和文件读取
        【边界条件】
        - 文件不存在时跳过
        - 文件编码必须是 UTF-8
        """
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""
    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        构建 LLM API 格式的消息列表。

        【架构职责】
        业务层消息构建,将历史对话、当前用户消息、运行时上下文合并为 LLM API 格式的消息列表。
        供 provider.chat() 调用。

        【输入契约】
        - history: list[dict[str, Any]]（必选）- 嶈息历史列表
        - current_message: str（必选）- 当前用户消息内容
        - skill_names: list[str] | None（可选）- 鿰加载到上下文的技能名称列表
        - media: list[str] | None（可选）- 嶈息关联的媒体文件路径列表
        - channel: str | None（可选）- 消息来源通道
        - chat_id: str | None（可选）- 聊天会话标识
        【输出契约】
        - list[dict[str, Any]] - LLM API 格式的消息列表
          - system: 系统提示词
          - 嶈息历史中的每条消息
          - 合并后的用户消息（运行时上下文 + 实际内容）
        【依赖模块】
        - _build_runtime_context(): 构建运行时上下文
        - _build_user_content(): 构建用户消息内容
        - build_system_prompt(): 构建系统提示词
        【性能说明】
        - 合并用户消息以避免连续相同角色的消息（部分 provider 会拒绝）
        - 运行时上下文仅在用户消息前注入，不影响消息顺序
        """
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        user_content = self._build_user_content(current_message, media)

        # Merge runtime context and user content into a single user message
        # to avoid consecutive same-role messages that some providers reject.
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content

        return [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
            {"role": "user", "content": merged},
        ]
    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """
        构建用户消息内容，支持 base64 编码图片。

        【架构职责】
        数据层内容格式化,将用户文本和可选的媒体文件转换为 LLM API 支持的多模态消息格式。
        支持文本和多模态内容混合输入。

        【输入契约】
        - text: str（必选）- 用户消息文本
        - media: list[str] | None（可选）- 媒体文件路径列表（图片路径）
        【输出契约】
        - str | list[dict[str, Any]] - 若无媒体则返回纯文本；
          若有媒体则返回多模态内容列表（文本 + base64 图片)
        【依赖模块】
        - pathlib: 用于文件路径处理
        - mimetypes: 用于 MIME 类型检测
        - base64: 用于图片编码
        【边界条件】
        - 文件不存在或跳过
        - 非 image MIME 类型时跳过
        - 空媒体列表时返回纯文本
        """
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text
        return images + [{"type": "text", "text": text}]
    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: str,
    ) -> list[dict[str, Any]]:
        """
        添加工具结果到消息列表。

        【架构职责】
        数据层消息构建,将工具执行结果添加到消息列表中，        用于在多轮对话中传递工具调用结果。

        【输入契约】
        - messages: list[dict[str, Any]]（必选）- 现有消息列表
        - tool_call_id: str（必选）- 工具调用 ID
        - tool_name: str（必选）- 工具名称
        - result: str（必选）- 工具执行结果
        【输出契约】
        - list[dict[str, Any]] - 更新后的消息列表
        【依赖模块】
        无外部依赖
        """
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages
    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """
        添加助手消息到消息列表。

        【架构职责】
        数据层消息构建,将 LLM 响应内容添加到消息列表中，
        支持工具调用、推理内容和、思维块等扩展字段。

        【输入契约】
        - messages: list[dict[str, Any]]（必选）- 现有消息列表
        - content: str | None（必选）- 助手响应内容
        - tool_calls: list[dict[str, Any]] | None（可选）- 工具调用列表
        - reasoning_content: str | None（可选）- 推理内容（如 DeepSeek）
        - thinking_blocks: list[dict] | None（可选）- 思维块列表
        【输出契约】
        - list[dict[str, Any]] - 更新后的消息列表
        【依赖模块】
        无外部依赖
        【边界条件】
        - 空内容且无工具调用的助手消息可能被跳过（会污染会话上下文）
        """
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        if thinking_blocks:
            msg["thinking_blocks"] = thinking_blocks
        messages.append(msg)
        return messages
