"""Subagent manager for background task execution."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ExecToolConfig
from nanobot.providers.base import LLMProvider


class SubagentManager:
    """
    后台子代理管理器，负责生成和管理后台执行的任务代理。

    【架构分层】业务层 - 子代理管理模块
    【模块职责】创建、管理和协调后台子代理的执行，处理任务分发、结果汇报和会话关联。
    【核心依赖】
        - LLMProvider: LLM 提供者
        - ToolRegistry: 工具注册表
        - MessageBus: 消息总线
        - 各种工具类: 文件/Shell/Web 工具
    """

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        """
        初始化子代理管理器。

        【架构职责】
        业务层初始化，配置子代理运行环境，包括 LLM 提供者、工作空间、消息总线等。

        【输入契约】
        - provider: LLMProvider（必选) - LLM 提供者
        - workspace: Path(必选) - 工作空间路径
        - bus: MessageBus(必选) - 消息总线
        - model: str | None(可选) - 模型名称，默认 provider 默认
        - temperature: float(可选) - 生成温度,默认 0.7
        - max_tokens: int(可选) - 最大 token 数,默认 4096
        - reasoning_effort: str | None(可选) - 推理努力程度
        - brave_api_key: str | None(可选) - Brave API 寿钥
        - web_proxy: str | None(可选) - Web 代理
        - exec_config: ExecToolConfig | None(可选) - Shell 执行配置
        - restrict_to_workspace: bool(可选) - 是否限制到工作空间,默认 False

        【输出契约】
        无返回值,初始化实例属性。

        【依赖模块】
        - ToolRegistry: 工具注册表
        - MessageBus: 消息总线
        - 各种工具类: 文件/Shell/Web 工具

        """
        from nanobot.config.schema import ExecToolConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
    ) -> str:
        """
        生成并启动一个后台子代理执行指定任务。

        【架构职责】
        业务层任务分发,创建一个独立的后台任务代理来执行指定任务,
        宏观任务状态和并在完成后通知主代理。

        【输入契约】
        - task: str(必选) - 要执行的任务描述
        - label: str | None(可选) - 任务标签,用于日志和UI 显示
        - origin_channel: str(可选) - 来源通道,默认 "cli"
        - origin_chat_id: str(可选) - 来源聊天ID,默认 "direct"
        - session_key: str | None(可选) - 会话键,用于任务取消关联

        【输出契约】
        - str - 任务启动消息,包含任务 ID 和        【依赖模块】
        - asyncio.create_task(): 创建异步任务
        - _run_subagent(): 执行子代理任务
        - _running_tasks: 存储任务引用
        - _session_tasks: 会话-任务关联
        【并发说明】
        - 使用 asyncio.create_task 在后台运行
        - 任务完成后通过回调自动清理引用
        - 支持通过 session_key 批量取消特定会话的所有子代理
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id}
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)
        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]
        bg_task.add_done_callback(_cleanup)
        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."
    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """
        执行子代理任务的核心循环。

        【架构职责】
        业务层任务执行,运行子代理的完整处理循环：构建工具->调用LLM->执行工具->返回结果,
        直到达到最大迭代次数或获得最终结果。
        【输入契约】
        - task_id: str(必选) - 任务 ID
        - task: str(必选) - 要执行的任务描述
        - label: str(必选) - 任务标签（用于日志)
        - origin: dict[str, str](必选) - 来源信息 {channel, chat_id}
        【输出契约】
        无返回值。任务完成后通过 _announce_result 汇报结果。
        【依赖模块】
        - ToolRegistry: 工具注册表
        - LLMProvider.chat(): LLM 调用
        - 各种工具类: ReadFileTool, WriteFileTool, EditFileTool, ListDirTool, ExecTool, WebSearchTool, WebFetchTool
        【异常边界】
        - 捕获所有异常并通过 _announce_result 报告错误
        - 最大迭代次数 15 次
        【性能说明】
        - 篮选工具集不不包含 message/spawn 工具,避免递归
        - 单次迭代包含一次 LLM 调用和可能的多次工具执行
        - 鯏个子代理独立运行,不阻塞主代理
        """
        logger.info("Subagent [{}] starting task: {}", task_id, label)
        try:
            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            allowed_dir = self.workspace if self.restrict_to_workspace else None
            tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
            ))
            tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
            tools.register(WebFetchTool(proxy=self.web_proxy))

 system_prompt = self._build_subagent_prompt()
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]
            # Run agent loop (limited iterations)
            max_iterations = 15
            iteration = 0
            final_result: str | None = None
            while iteration < max_iterations:
                iteration += 1
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    reasoning_effort=self.reasoning_effort,
                )
                if response.has_tool_calls:
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })
                    # Execute tools
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug("Subagent [{}] executing: {} with arguments: {}", task_id, tool_call.name, args_str)
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    final_result = response.content
                    break
            if final_result is None:
                final_result = "Task completed but no final response was generated."
            logger.info("Subagent [{}] completed successfully", task_id)
            await self._announce_result(task_id, label, task, final_result, origin, "ok")
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            await self._announce_result(task_id, label, task, error_msg, origin, "error")
    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """
        向主代理汇报子代理执行结果。

        【架构职责】
        业务层结果汇报,通过系统消息通道将子代理执行结果发送回主代理,
        触发主代理处理结果通知。
        【输入契约】
        - task_id: str(必选) - 任务 ID
        - label: str(必选) - 任务标签
        - task: str(必选) - 像执行的任务描述
        - result: str(必选) - 执行结果
        - origin: dict[str, str](必选) - 来源信息
        - status: str(必选) - 状态("ok" 或 "error")
        【输出契约】
        无返回值。发送系统消息到消息总线。
        【依赖模块】
        - MessageBus.publish_inbound(): 发布入站消息
        【消息格式】
        使用 system 通道，通过 chat_id 格式 "channel:chat_id" 定位目标会话
        """
        status_text = "completed successfully" if status == "ok" else "failed"
        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}
Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""
        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )
        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])
    def _build_subagent_prompt(self) -> str:
        """
        构建子代理专用系统提示词。

        【架构职责】
        业务层提示词构建,生成子代理专用的精简版系统提示词,
        不包含消息和生成工具等避免递归。

        【输入契约】
        无参数
        【输出契约】
        - str - 子代理系统提示词
        【依赖模块】
        - ContextBuilder._build_runtime_context(): 枍4构建运行时上下文
        - SkillsLoader.build_skills_summary(): 茏4技能摘要
        """
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.skills import SkillsLoader
        time_ctx = ContextBuilder._build_runtime_context(None, None)
        parts = [f"""# Subagent
{time_ctx}

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task. Your final response will be reported back to the main agent.

## Workspace
{self.workspace}"""]
        skills_summary = SkillsLoader(self.workspace).build_skills_summary()
        if skills_summary:
            parts.append(f"## Skills\n\nRead SKILL.md with read_file to use a skill.\n\n{skills_summary}")
        return "\n\n".join(parts)
    async def cancel_by_session(self, session_key: str) -> int:
        """
        取消指定会话的所有子代理。

        【架构职责】
        控制层会话管理, 取消与指定会话关联的所有后台子代理任务
        【输入契约】
        - session_key: str(必选) - 会话键
        【输出契约】
        - int - 取消的任务数量
        【依赖模块】
        无外部依赖
        【并发说明】
        - 使用集合推导避免迭代时修改问题
        - 使用 asyncio.gather 收集团取消的任务
        """
        tasks = [self._running_tasks[tid] for tid in self._session_tasks.get(session_key, [])]
        if tid in self._running_tasks and not self._running_tasks[tid].done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)
    def get_running_count(self) -> int:
        """
        获取当前运行中的子代理数量。

        【架构职责】
        业务层状态查询, 返回当前活跃的子代理任务数量
        【输入契约】
        无参数
        【输出契约】
        - int - 迋行中的子代理数量
        """
        return len(self._running_tasks)
