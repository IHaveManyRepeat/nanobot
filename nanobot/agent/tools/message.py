"""Message tool for sending messages to users."""
from typing import Any,from typing import Any, Awaitable, Callable
from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage
class MessageTool(Tool):
    """
    消息发送工具,用于向用户发送消息。

    【架构分层】工具层 - 消息发送模块
    【模块职责】提供消息发送能力,支持向指定通道发送文本消息和媒体附件,
        并跟踪当前会话是否已发送消息。
    【核心依赖】
        - Tool: 工具基类
        - OutboundMessage: 出站消息事件
    """
    name = "message"
    description = "Send a message to the user. Use this when you want to communicate something."
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The message content to send"
            },
            "channel": {
                "type": "string",
                "description": "Optional: target channel (telegram, discord, etc.)"
            },
            "chat_id": {
                "type": "string",
                "description": "Optional: target chat/user ID"
            },
            "media": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: list of file paths to attach (images, audio, documents)"
            }
        },
        "required": ["content"]
    }
    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ):
        """
        初始化消息发送工具。

        【架构职责】
        工具层初始化,配置消息发送回调和默认通道/聊天 ID。
        【输入契约】
        - send_callback: Callable[[OutboundMessage], Awaitable[None]] | None(可选) - 发送回调函数
        - default_channel: str(可选) - 默认通道
        - default_chat_id: str(可选) - 默认聊天 ID
        - default_message_id: str | None(可选) - 默认消息 ID
        【输出契约】
        无返回值,初始化实例属性。
        【依赖模块】
        - OutboundMessage: 出站消息数据类
        """
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id
        self._sent_in_turn: bool = False
    def set_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """
        设置当前消息上下文。

        【架构职责】
        工具层上下文设置,设置当前会话的通道、聊天 ID 和消息 ID。
        【输入契约】
        - channel: str(必选) - 通道名称
        - chat_id: str(必选) - 聊天 ID
        - message_id: str | None(可选) - 消息 ID
        【输出契约】
        无返回值。更新实例属性。
        【依赖模块】
        无外部依赖
        """
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id
    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """
        设置发送回调函数。

        【架构职责】
        工具层回调设置,设置用于发送消息的回调函数。
        【输入契约】
        - callback: Callable[[OutboundMessage], Awaitable[None]](必选) - 回调函数
        【输出契约】
        无返回值,更新实例属性。
        【依赖模块】
        无外部依赖
        """
        self._send_callback = callback
    def start_turn(self) -> None:
        """
        重置每轮发送跟踪。

        【架构职责】
        工具层状态重置,在每轮开始时重置发送跟踪标志。
        【输入契约】
        无参数
        【输出契约】
        无返回值。重置 _sent_in_turn 为 False。
        【依赖模块】
        无外部依赖
        """
        self._sent_in_turn = False
    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
        **kwargs: Any
    ) -> str:
        """
        执行消息发送。

        【架构职责】
        工具层消息发送,构造并发送 OutboundMessage 到指定通道。
        【输入契约】
        - content: str(必选) - 消息内容
        - channel: str | None(可选) - 目标通道（默认使用上下文中的通道）
        - chat_id: str | None(可选) - 目标聊天 ID（默认使用上下文中的聊天 ID)
        - message_id: str | None(可选) - 消息 ID(默认使用上下文中的消息 ID)
        - media: list[str] | None(可选) - 媒体文件路径列表
        【输出契约】
        - str - 发送结果消息或错误信息
        【依赖模块】
        - OutboundMessage: 出站消息数据类
        - self._send_callback: 发送回调
        【异常边界】
        - 通道/聊天 ID 缺失时返回错误
        - 回调未设置时返回错误
        - 发送失败时返回错误信息
        """
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        message_id = message_id or self._default_message_id
        if not channel or not chat_id:
            return "Error: No target channel/chat specified"
        if not self._send_callback:
            return "Error: Message sending not configured"
        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata={
                "message_id": message_id,
            },
        )
        try:
            await self._send_callback(msg)
            if channel == self._default_channel and chat_id == self._default_chat_id:
                self._sent_in_turn = True
            media_info = f" with {len(media)} attachments" if media else ""
            return f"Message sent to {channel}:{chat_id}{media_info}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
