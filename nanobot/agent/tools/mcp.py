"""
MCP (Model Context Protocol) 客户端适配器模块。

【架构分层：工具层-外部协议适配】
本文件实现 MCP 协议客户端的核心逻辑，负责：
1. 建立与 MCP 服务器（stdio/HTTP）的双向通信连接
2. 动态发现并注册 MCP 服务器提供的工具
3. 将 MCP 工具包装为 nanobot 原生 Tool 接口

【在架构中的位置】
┌─────────────────────────────────────────────────────────────┐
│                    nanobot Agent                            │
├─────────────────────────────────────────────────────────────┤
│  ToolRegistry ◄─── MCPToolWrapper (本模块) ◄─── MCP 服务器  │
│        │                    │                    (外部)     │
│        ▼                    ▼                              │
│  其他原生工具         MCP 协议通信                          │
└─────────────────────────────────────────────────────────────┘

【核心依赖】
- nanobot.agent.tools.base.Tool：工具基类，定义统一接口契约
- nanobot.agent.tools.registry.ToolRegistry：工具注册中心
- mcp 库：MCP 协议官方 Python SDK

【异常边界】
- 连接异常：MCP 服务器不可达、启动失败
- 超时异常：工具执行超时、连接超时
- 协议异常：MCP 协议版本不兼容、消息格式错误
"""

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


class MCPToolWrapper(Tool):
    """
    MCP 工具包装器：将单个 MCP 服务器工具适配为 nanobot Tool 接口。

    【架构角色】
    适配器模式的实现，充当 MCP 工具与 nanobot 工具系统之间的桥梁。
    负责协议转换、名称空间隔离、超时控制。

    【设计决策】
    - 工具名称添加 `mcp_{server_name}_` 前缀，避免不同 MCP 服务器的工具名冲突
    - 使用组合模式持有 MCP session，而非继承，保持接口灵活性
    - 异步执行保证不阻塞主事件循环

    【并发安全】
    实例本身无共享状态，可安全并发调用 execute()。
    底层 MCP session 的并发安全性由 mcp 库保证。
    """

    def __init__(self, session, server_name: str, tool_def, tool_timeout: int = 30):
        """
        初始化 MCP 工具包装器。

        Args:
            session: MCP ClientSession 实例，用于与 MCP 服务器通信
                     【来源】由 connect_mcp_servers() 创建并管理生命周期
            server_name: MCP 服务器名称，用于工具命名空间隔离
                         【格式】配置文件中定义的服务器标识符
            tool_def: MCP 工具定义对象（mcp.types.Tool）
                      【字段】name, description, inputSchema
            tool_timeout: 工具执行超时时间（秒），默认 30s
                          【注意】应大于 MCP 工具的预期最大执行时间
        """
        self._session = session
        # 保留原始名称用于实际调用
        self._original_name = tool_def.name
        # 添加命名空间前缀，避免跨服务器工具名冲突
        self._name = f"mcp_{server_name}_{tool_def.name}"
        # 工具描述，用于 LLM 理解工具用途
        self._description = tool_def.description or tool_def.name
        # JSON Schema 格式的参数定义
        self._parameters = tool_def.inputSchema or {"type": "object", "properties": {}}
        self._tool_timeout = tool_timeout

    @property
    def name(self) -> str:
        """
        获取工具的唯一标识名称。

        Returns:
            str: 带命名空间前缀的工具名称，格式为 "mcp_{server}_{tool}"

        【命名规范】
        前缀确保：
        1. 与原生 nanobot 工具区分
        2. 同名工具来自不同 MCP 服务器时不会冲突
        """
        return self._name

    @property
    def description(self) -> str:
        """
        获取工具的功能描述。

        Returns:
            str: 工具描述文本，供 LLM 决定是否调用此工具

        【用途】
        描述会被传递给 LLM，影响工具选择决策。
        MCP 服务器应提供清晰、准确的描述。
        """
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        """
        获取工具参数的 JSON Schema 定义。

        Returns:
            dict: JSON Schema 格式的参数定义
                  包含 type, properties, required 等字段

        【契约】
        - 返回值符合 JSON Schema 规范
        - nanobot 使用此 schema 进行参数验证和 LLM 提示
        """
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        """
        执行 MCP 工具调用。

        Args:
            **kwargs: 工具参数，需符合 parameters 定义的 schema

        Returns:
            str: 工具执行结果的文本表示
                 - 成功时返回工具输出内容
                 - 超时时返回超时提示信息
                 - 无输出时返回 "(no output)"

        【执行流程】
        1. 通过 MCP session 调用远程工具
        2. 等待结果，支持超时中断
        3. 解析 MCP 响应格式（TextContent 或其他类型）
        4. 拼接多个内容块为字符串

        【异常边界】
        - asyncio.TimeoutError: 工具执行超时，捕获并返回提示信息
        - 其他异常: 向上抛出，由调用方处理

        【性能说明】
        - 调用耗时取决于 MCP 工具实现，可能从毫秒到数十秒
        - 使用 asyncio.wait_for 实现超时控制，不阻塞事件循环
        - 建议 tool_timeout 设置为工具预期最大执行时间的 1.5 倍

        【并发安全】
        - 同一实例的多次并发调用共享 session，由 mcp 库处理并发
        - 无实例级共享状态，可安全并发执行
        """
        from mcp import types
        try:
            # 使用 asyncio 超时机制，防止工具无限阻塞
            result = await asyncio.wait_for(
                self._session.call_tool(self._original_name, arguments=kwargs),
                timeout=self._tool_timeout,
            )
        except asyncio.TimeoutError:
            # 超时时记录警告并返回友好提示，而非抛出异常
            # 这样 LLM 可以根据提示调整策略（如重试或换用其他工具）
            logger.warning("MCP tool '{}' timed out after {}s", self._name, self._tool_timeout)
            return f"(MCP tool call timed out after {self._tool_timeout}s)"

        # 解析 MCP 响应内容
        # MCP 响应可能是多个内容块的列表（TextContent, ImageContent 等）
        parts = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                # 非文本内容转为字符串表示
                parts.append(str(block))

        return "\n".join(parts) or "(no output)"


async def connect_mcp_servers(
    mcp_servers: dict, registry: ToolRegistry, stack: AsyncExitStack
) -> None:
    """
    连接所有配置的 MCP 服务器并注册其工具。

    Args:
        mcp_servers: MCP 服务器配置字典
                     【格式】{server_name: MCPServerConfig}
                     【来源】通常从配置文件加载
        registry: 工具注册中心实例
                  【作用】注册发现的 MCP 工具，供 agent 调用
        stack: 异步上下文管理器栈
               【作用】管理 MCP 连接的生命周期，确保会话结束时正确清理

    【执行流程】
    1. 遍历配置中的每个 MCP 服务器
    2. 根据配置类型建立连接：
       - command 配置 → stdio 方式（启动本地进程）
       - url 配置 → HTTP 方式（连接远程服务）
    3. 初始化 MCP 会话并获取工具列表
    4. 为每个工具创建 MCPToolWrapper 并注册到 registry

    【支持的连接方式】
    ┌─────────────────────────────────────────────────────────────┐
    │  stdio 方式                                                  │
    │  - 启动本地 MCP 服务器进程                                   │
    │  - 通过 stdin/stdout 通信                                    │
    │  - 适用于：本地工具、命令行工具                              │
    ├─────────────────────────────────────────────────────────────┤
    │  HTTP 方式                                                   │
    │  - 连接远程 MCP 服务器                                       │
    │  - 使用 streamable_http_client 进行双向流通信                │
    │  - 适用于：云端服务、远程 API                                │
    └─────────────────────────────────────────────────────────────┘

    【异常边界】
    - 单个服务器连接失败不影响其他服务器
    - 异常被捕获并记录日志，不向上抛出
    - 这确保部分 MCP 服务不可用时 agent 仍可使用其他工具

    【性能/并发说明】
    - 当前实现为顺序连接，可优化为并行连接
    - 每个连接使用独立的 httpx.AsyncClient
    - httpx 超时设为 None，由 tool_timeout 在工具调用层面控制

    【资源管理】
    - 所有连接资源通过 AsyncExitStack 管理
    - 会话结束时自动清理：关闭进程、释放 HTTP 连接
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    for name, cfg in mcp_servers.items():
        try:
            # ===== 根据配置选择连接方式 =====
            if cfg.command:
                # stdio 方式：启动本地进程作为 MCP 服务器
                params = StdioServerParameters(
                    command=cfg.command,   # 可执行命令
                    args=cfg.args,         # 命令行参数
                    env=cfg.env or None    # 环境变量
                )
                # 进入 stdio 客户端上下文，获取读写流
                read, write = await stack.enter_async_context(stdio_client(params))

            elif cfg.url:
                # HTTP 方式：连接远程 MCP 服务器
                from mcp.client.streamable_http import streamable_http_client
                # 创建自定义 httpx 客户端
                # 关键：timeout=None 禁用 httpx 默认 5s 超时
                # 原因：让 tool_timeout 在更高层级控制超时行为
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=cfg.headers or None,   # 自定义请求头
                        follow_redirects=True,         # 自动跟随重定向
                        timeout=None,                  # 禁用底层超时
                    )
                )
                # 进入 HTTP 客户端上下文，获取读写流
                # 返回值：(read_stream, write_stream, session_id_callback)
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(cfg.url, http_client=http_client)
                )

            else:
                # 配置错误：既无 command 也无 url
                logger.warning("MCP server '{}': no command or url configured, skipping", name)
                continue

            # ===== 创建并初始化 MCP 会话 =====
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()  # 执行 MCP 协议握手

            # ===== 发现并注册工具 =====
            tools = await session.list_tools()  # 获取服务器提供的所有工具

            for tool_def in tools.tools:
                # 为每个工具创建包装器并注册
                wrapper = MCPToolWrapper(session, name, tool_def, tool_timeout=cfg.tool_timeout)
                registry.register(wrapper)
                logger.debug("MCP: registered tool '{}' from server '{}'", wrapper.name, name)

            logger.info("MCP server '{}': connected, {} tools registered", name, len(tools.tools))

        except Exception as e:
            # 单个服务器连接失败不中断其他服务器的连接
            # 这是容错设计：部分 MCP 服务不可用不应阻止 agent 启动
            logger.error("MCP server '{}': failed to connect: {}", name, e)
