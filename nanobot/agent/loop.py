"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
import weakref
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryStore
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig
    from nanobot.cron.service import CronService


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _TOOL_RESULT_MAX_CHARS = 500

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
    ):
        """
        初始化 AgentLoop 核心处理引擎实例。

        【架构职责】
        业务层核心入口，组装消息总线、LLM提供者、会话管理器、工具注册表等核心组件，
        构建 Agent 运行的完整上下文环境。

        【输入契约】
        - bus: MessageBus（必选）- 消息总线，用于接收 inbound 消息和发送 outbound 消息
        - provider: LLMProvider（必选）- LLM 提供者抽象，支持多模型切换
        - workspace: Path（必选）- 工作空间路径，限制文件操作范围
        - model: str | None（可选）- 指定模型名称，默认使用 provider 默认模型
        - max_iterations: int（可选）- 工具调用最大迭代次数，默认 40，防止无限循环
        - temperature: float（可选）- 生成温度，默认 0.1（低随机性）
        - max_tokens: int（可选）- 单次响应最大 token 数，默认 4096
        - memory_window: int（可选）- 会话历史窗口大小，默认 100 条消息
        - reasoning_effort: str | None（可选）- 推理努力程度（如 "high"/"medium"/"low"）
        - brave_api_key: str | None（可选）- Brave 搜索 API 密钥
        - web_proxy: str | None（可选）- Web 请求代理地址
        - exec_config: ExecToolConfig | None（可选）- Shell 执行工具配置
        - cron_service: CronService | None（可选）- 定时任务服务
        - restrict_to_workspace: bool（可选）- 是否严格限制文件操作到工作空间，默认 False
        - session_manager: SessionManager | None（可选）- 会话管理器，默认自动创建
        - mcp_servers: dict | None（可选）- MCP 服务器配置字典
        - channels_config: ChannelsConfig | None（可选）- 通道配置

        【输出契约】
        无返回值，初始化实例属性。

        【依赖模块】
        - ContextBuilder: 构建对话上下文
        - SessionManager: 管理会话状态
        - ToolRegistry: 注册和管理工具
        - SubagentManager: 管理子代理
        - MessageBus: 消息总线

        【并发说明】
        - 初始化 _processing_lock 异步锁，确保消息处理串行化
        - 使用 WeakValueDictionary 管理 consolidation_locks，避免内存泄漏
        """
        from nanobot.config.schema import ExecToolConfig

        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=reasoning_effort,
            brave_api_key=brave_api_key,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._processing_lock = asyncio.Lock()
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """
        注册 Agent 默认工具集。

        【架构职责】
        工具层初始化，将文件系统、Shell执行、Web搜索/抓取、消息发送、子代理生成、
        定时任务等核心工具注册到 ToolRegistry，供 Agent 循环调用。

        【输入契约】
        无参数，使用实例属性 self.workspace、self.restrict_to_workspace、
        self.exec_config、self.brave_api_key、self.web_proxy、self.cron_service。

        【输出契约】
        无返回值，副作用是向 self.tools 注册多个工具实例。

        【依赖模块】
        - ReadFileTool/WriteFileTool/EditFileTool/ListDirTool: 文件系统工具
        - ExecTool: Shell 命令执行工具
        - WebSearchTool/WebFetchTool: Web 搜索和抓取工具
        - MessageTool: 消息发送工具（依赖 bus.publish_outbound）
        - SpawnTool: 子代理生成工具（依赖 SubagentManager）
        - CronTool: 定时任务工具（可选，依赖 cron_service）

        【安全边界】
        - restrict_to_workspace=True 时，文件操作被限制在 workspace 目录内
        - ExecTool 使用 exec_config.timeout 控制命令执行超时
        """
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
            )
        )
        self.tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
        self.tools.register(WebFetchTool(proxy=self.web_proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """
        懒加载连接到配置的 MCP（Model Context Protocol）服务器。

        【架构职责】
        驱动层连接管理，负责建立与外部 MCP 服务器的连接，扩展 Agent 的工具能力。
        采用懒加载模式，仅在首次需要时连接。

        【输入契约】
        无参数，使用实例属性 self._mcp_servers（MCP 服务器配置）。

        【输出契约】
        无返回值。连接成功时设置 self._mcp_connected = True。

        【依赖模块】
        - connect_mcp_servers: MCP 连接函数（from nanobot.agent.tools.mcp）
        - AsyncExitStack: 异步上下文管理器栈

        【异常边界】
        - 连接失败时捕获异常并记录日志，不抛出，允许后续重试
        - 失败时清理 _mcp_stack，保持状态一致性

        【并发说明】
        - 使用 _mcp_connecting 标志防止并发重入
        - 使用 _mcp_connected 标志确保只连接一次
        """
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers

        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """
        更新需要路由信息的工具上下文。

        【架构职责】
        上下文传递，将消息来源的通道、聊天ID、消息ID注入到需要路由信息的工具中，
        确保工具执行结果能正确路由回消息来源。

        【输入契约】
        - channel: str（必选）- 消息来源通道（如 "cli", "telegram", "discord"）
        - chat_id: str（必选）- 聊天会话标识
        - message_id: str | None（可选）- 消息标识，仅 message 工具需要

        【输出契约】
        无返回值，副作用是更新 message、spawn、cron 工具的内部上下文。

        【依赖模块】
        - MessageTool: 需要 channel、chat_id、message_id（用于回复消息）
        - SpawnTool: 需要 channel、chat_id（用于子代理路由）
        - CronTool: 需要 channel、chat_id（用于定时任务回调）

        【安全边界】
        使用 hasattr 检查工具是否支持 set_context 方法，避免调用不存在的方法
        """
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """
        将工具调用列表格式化为简洁的提示字符串。

        【架构职责】
        工具层格式化工具，将 LLM 返回的工具调用对象转换为用户友好的提示文本，
        用于在进度回调中展示当前正在执行的操作。

        【输入契约】
        - tool_calls: list（必选）- ToolCall 对象列表，每个对象包含 name 和 arguments 属性

        【输出契约】
        - str - 格式化后的工具调用提示，如 'web_search("查询内容…"), read_file("path.txt")'

        【依赖模块】
        无外部依赖，纯数据处理

        【边界条件】
        - 参数值超过 40 字符时截断并添加 "…" 后缀
        - 非字符串参数值仅显示工具名称
        - 空列表返回空字符串
        """

        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'

        return ", ".join(_fmt(tc) for tc in tool_calls)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """
        运行 Agent 迭代循环，执行 LLM 对话直到获得最终响应或达到最大迭代次数。

        【架构职责】
        业务层核心处理逻辑，实现"LLM调用→工具执行→LLM调用"的迭代循环，
        是 Agent 智能行为的执行引擎。

        【输入契约】
        - initial_messages: list[dict]（必选）- 初始消息列表，包含系统提示和历史对话
        - on_progress: Callable[..., Awaitable[None]] | None（可选）- 进度回调函数，
          接收 (content: str, tool_hint: bool = False) 参数

        【输出契约】
        - tuple[str | None, list[str], list[dict]]:
          - final_content: str | None - 最终响应内容
          - tools_used: list[str] - 使用的工具名称列表
          - messages: list[dict] - 完整的消息历史（包含工具调用和结果）

        【依赖模块】
        - LLMProvider.chat(): 调用 LLM 生成响应
        - ToolRegistry.execute(): 执行工具调用
        - ContextBuilder.add_assistant_message(): 添加助手消息
        - ContextBuilder.add_tool_result(): 添加工具结果

        【异常边界】
        - LLM 返回 error 类型的 finish_reason 时，不保存错误响应到会话历史
        - 达到最大迭代次数时返回友好的提示信息

        【性能说明】
        - 单次迭代包含一次 LLM 调用和可能的多次工具执行
        - 最大迭代次数由 max_iterations 控制（默认 40）
        - 长时间运行的任务应考虑设置合理的超时
        """
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
            )

            if response.has_tool_calls:
                if on_progress:
                    clean = self._strip_think(response.content)
                    if clean:
                        await on_progress(clean)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

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
                messages = self.context.add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                clean = self._strip_think(response.content)
                # Don't persist error responses to session history — they can
                # poison the context and cause permanent 400 loops (#1303).
                if response.finish_reason == "error":
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                messages = self.context.add_assistant_message(
                    messages,
                    clean,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                """
                含义： 当 LLM 岡有没有工具调用 时（即 response.has_tool_calls 为
                 False）， 退出循环。

                 原因：
                 - LLM 已经给出了最终响应（文本回复）
                 - 不需要再继续迭代，- 直接返回 final_content 和- 避免无限循环
                """
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        return final_content, tools_used, messages

    async def run(self) -> None:
        """
        启动 Agent 主循环，持续监听消息总线并分发处理任务。

        【架构职责】
        业务层入口点，启动 Agent 的核心事件循环。采用异步任务模式处理消息，
        确保 /stop 命令能及时响应而不阻塞主循环。

        【输入契约】
        无参数，使用实例属性 self.bus 消费消息。

        【输出契约】
        无返回值，持续运行直到调用 stop() 方法。

        【依赖模块】
        - MessageBus.consume_inbound(): 消费入站消息
        - _dispatch(): 分发消息处理任务
        - _handle_stop(): 处理停止命令
        - _connect_mcp(): 懒加载连接 MCP 服务器

        【并发说明】
        - 每条消息创建独立的 asyncio.Task，支持并发处理
        - 使用 _active_tasks 字典跟踪每个会话的活动任务
        - /stop 命令可取消特定会话的所有活动任务

        【边界条件】
        - 消息总线消费超时（1秒）时继续循环
        - 收到 /stop 命令时取消对应会话的任务
        """
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                """
                这是一个用于 add_done_callback 的 lambda 回调函数，让我逐步拆解：

                  Lambda 结构分解

                  lambda t, k=msg.session_key: (
                      self._active_tasks.get(k, []) and
                      self._active_tasks[k].remove(t)
                      if t in self._active_tasks.get(k, [])
                      else None
                  )

                  1. 参数部分

                  t, k=msg.session_key
                  - t - 回调接收的参数，是完成后的 task 对象
                  - k=msg.session_key - k 有默认值，使用捕获时的 msg.session_key

                  2. 函数体（条件表达式）

                  A if condition else None

                  条件：t in self._active_tasks.get(k, [])
                  - 检查 task 是否在活跃任务列表中

                  真值时执行：self._active_tasks.get(k, []) and self._active_tasks[k].remove(t)
                  - and 短路求值：先获取列表（确保存在），再执行移除

                  假值时：None
                  - 什么都不做

                  等价的普通函数

                  def remove_task_callback(t, k=msg.session_key):
                      active_list = self._active_tasks.get(k, [])
                      if t in active_list:
                          active_list.remove(t)

                  作用

                  当异步任务完成时，自动从 _active_tasks 字典的对应会话列表中移除该任务，防止内存泄漏和重复处理。
                """
                task.add_done_callback(
                    lambda t, k=msg.session_key: self._active_tasks.get(k, [])
                    and self._active_tasks[k].remove(t)
                    if t in self._active_tasks.get(k, [])
                    else None
                )

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """
        取消指定会话的所有活动任务和子代理。

        【架构职责】
        控制层命令处理，响应用户的 /stop 命令，取消正在执行的任务以释放资源。

        【输入契约】
        - msg: InboundMessage（必选）- 包含 session_key 的入站消息

        【输出契约】
        无返回值，通过 MessageBus 发布取消结果消息。

        【依赖模块】
        - SubagentManager.cancel_by_session(): 取消子代理
        - MessageBus.publish_outbound(): 发布取消结果

        【并发说明】
        - 使用 _active_tasks.pop() 原子移除任务列表
        - 等待所有任务完成（包括取消的任务）以避免资源泄漏
        """
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
            )
        )

    async def _dispatch(self, msg: InboundMessage) -> None:
        """
        分发消息到处理流程，在全局锁保护下执行。

        【架构职责】
        控制层消息分发，将入站消息路由到处理逻辑。使用全局锁确保消息串行处理，
        避免同一会话的并发冲突。

        【输入契约】
        - msg: InboundMessage（必选）- 入站消息对象

        【输出契约】
        无返回值，处理结果通过 bus.publish_outbound 发送。

        【依赖模块】
        - _process_message(): 处理消息的核心逻辑
        - MessageBus.publish_outbound(): 发送出站消息

        【异常边界】
        - 捕获 asyncio.CancelledError 并重新抛出
        - 捕获其他异常并发送友好的错误消息
        - CLI 通道在无响应时发送空消息

        【并发说明】
        - 使用 _processing_lock 确保消息串行处理
        - 取消的任务立即传播 CancelledError
        """
        async with self._processing_lock:
            try:
                response = await self._process_message(msg)
                if response is not None:
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="",
                            metadata=msg.metadata or {},
                        )
                    )
            except asyncio.CancelledError:
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception:
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Sorry, I encountered an error.",
                    )
                )

    async def close_mcp(self) -> None:
        """
        关闭 MCP 服务器连接。

        【架构职责】
        驱动层资源清理，释放 MCP 连接占用的资源。应在 Agent 停止时调用。

        【输入契约】
        无参数，使用实例属性 self._mcp_stack。

        【输出契约】
        无返回值。清理后设置 self._mcp_stack = None。

        【依赖模块】
        - AsyncExitStack.aclose(): 异步上下文管理器清理

        【异常边界】
        - 捕获 RuntimeError 和 BaseExceptionGroup 但忽略（MCP SDK 清理噪声）
        """
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """
        停止 Agent 主循环。

        【架构职责】
        控制层生命周期管理。设置停止标志，主循环将在下一次迭代时退出。

        【输入契约】
        无参数。

        【输出契约】
        无返回值，设置 self._running = False。

        【依赖模块】
        无外部依赖。

        【并发说明】
        简单的标志位操作，线程安全。
        """
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """
        处理单条入站消息并返回响应。

        【架构职责】
        业务层核心处理逻辑，解析消息、处理命令、构建上下文、调用 LLM、
        执行工具、保存会话、返回响应。是 AgentLoop 的主要处理入口。

        【输入契约】
        - msg: InboundMessage（必选）- 入站消息对象
        - session_key: str | None（可选）- 会话键，覆盖 msg.session_key
        - on_progress: Callable[[str], Awaitable[None]] | None（可选）- 进度回调

        【输出契约】
        - OutboundMessage | None - 嶈息响应对象，若 MessageTool 已发送消息则返回 None

        【依赖模块】
        - SessionManager: 获取/创建/保存会话
        - ContextBuilder: 构建对话消息
        - ToolRegistry: 执行工具
        - MemoryStore: 内存整合
        - MessageBus: 发布响应

        【异常边界】
        - /new 命令归档失败时返回错误消息
        - 消息处理异常时返回友好错误提示

        【处理流程】
        1. 系统消息：解析来源通道
        2. 命令处理： /new（新建会话）、/help（帮助）
        3. 内存整合： 超过窗口时自动触发
        4. 消息处理： 构建上下文 -> 调用 LLM -> 执行工具 -> 保存结果
        """
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (
                msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
            )
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.memory_window)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content,
                channel=channel,
                chat_id=chat_id,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or "Background task completed.",
            )

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated :]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )
            finally:
                self._consolidating.discard(session.key)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content="New session started."
            )
        if cmd == "/help":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="🐈 nanobot commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/help — Show available commands",
            )

        unconsolidated = len(session.messages) - session.last_consolidated
        if unconsolidated >= self.memory_window and session.key not in self._consolidating:
            self._consolidating.add(session.key)
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=self.memory_window)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """
        保存对话轮次到会话，截断过长的工具结果。

        【架构职责】
        数据层持久化，将 Agent 对话轮次保存到 Session 中。 对工具结果进行截断，
        避免会话历史过大。

        【输入契约】
        - session: Session（必选）- 会话对象
        - messages: list[dict]（必选）- 消息列表
        - skip: int（必选）- 跳过的消息数量（已处理的消息不保存）

        【输出契约】
        无返回值。直接修改 session.messages 列和。

        【依赖模块】
        - ContextBuilder._RUNTIME_CONTEXT_TAG: 用于识别和剥离运行时上下文
        - datetime: 用于时间戳

        【边界条件】
        - 跳过空的 assistant 消息（无内容且无 tool_calls）
        - 工具结果超过 _TOOL_RESULT_MAX_CHARS 字符时截断
        - 运行时上下文前缀从用户消息中剥离
        - data URL 图片替换为 "[image]" 占位符
        """
        from datetime import datetime

        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if (
                role == "tool"
                and isinstance(content, str)
                and len(content) > self._TOOL_RESULT_MAX_CHARS
            ):
                entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, str) and content.startswith(
                    ContextBuilder._RUNTIME_CONTEXT_TAG
                ):
                    # Strip the runtime-context prefix, keep only the user text.
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if (
                            c.get("type") == "text"
                            and isinstance(c.get("text"), str)
                            and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
                        ):
                            continue  # Strip runtime context from multimodal messages
                        if c.get("type") == "image_url" and c.get("image_url", {}).get(
                            "url", ""
                        ).startswith("data:image/"):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """
        委托 MemoryStore 执行内存整合。

        【架构职责】
        数据层内存管理。当会话消息超过 memory_window 时，将历史对话压缩为摘要，
        防止上下文无限增长。 支持手动 /new 命令触发完整归档。

        【输入契约】
        - session: Session（必选）- 会话对象
        - archive_all: bool（可选）- 是否归档全部消息，默认 False（仅归档增量）

        【输出契约】
        - bool - 整合成功返回 True，失败返回 False

        【依赖模块】
        - MemoryStore: 内存存储管理器
        - provider: LLM 提供者（用于生成摘要）

        【性能说明】
        - 涉及 LLM 调用，可能耗时较长
        - 应在后台任务中执行，不阻塞主循环
        """
        return await MemoryStore(self.workspace).consolidate(
            session,
            self.provider,
            self.model,
            archive_all=archive_all,
            memory_window=self.memory_window,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """
        直接处理消息（用于 CLI 或定时任务场景）。

        【架构职责】
        接口层便捷入口。为外部调用者提供简化的消息处理接口，
        跳过消息总线的异步消费机制。

        【输入契约】
        - content: str（必选）- 消息内容
        - session_key: str（可选）- 会话键，默认 "cli:direct"
        - channel: str（可选）- 通道名称，默认 "cli"
        - chat_id: str（可选）- 聊天ID，默认 "direct"
        - on_progress: Callable[[str], Awaitable[None]] | None（可选）- 进度回调

        【输出契约】
        - str - 嶈息响应内容，若响应为 None 则返回空字符串

        【依赖模块】
        - _connect_mcp(): 连接 MCP 服务器
        - _process_message(): 处理消息

        【使用场景】
        - CLI 命令行直接交互
        - 定时任务（ cron) 的自动执行
        - 测试和调试场景
        """
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        return response.content if response else ""
