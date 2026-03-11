"""Spawn tool for creating background subagents."""
from typing import TYPE_CHECKING, Any
from nanobot.agent.tools.base import Tool
if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """
    子代理生成工具,用于创建后台执行的任务代理。

    【架构分层】工具层 - 子代理管理模块
    【模块职责】提供子代理生成能力,允许主代理将复杂任务委派给独立的后台子代理执行,
        并在完成后报告结果。

    【核心依赖】
        - Tool: 工具基类
        - SubagentManager: 子代理管理器
    """
    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._session_key = "cli:direct"
    def set_context(self, channel: str, chat_id: str) -> None:
        """
        设置来源上下文。

        【架构职责】
        工具层上下文设置,设置子代理结果汇报的目标通道和聊天 ID,
        用于结果通知路由。

        【输入契约】
        - channel: str(必选) - 来源通道（如 "cli", "telegram", "discord")
        - chat_id: str(必选) - 来源聊天 ID
        【输出契约】
        无返回值, 更新实例属性。
        【依赖模块】
        无外部依赖
        """
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"
    @property
    def name(self) -> str:
        return "spawn"
    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done."
        )
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": " "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
            },
            "required": ["task"],
        }
    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """
        生成子代理执行任务。

        【架构职责】
        业务层任务分发,创建后台子代理并返回启动确认消息。
        【输入契约】
        - task: str(必选) - 任务描述
        - label: str | None(可选) - 显示标签
        【输出契约】
        - str - 子代理启动消息
        【依赖模块】
        - SubagentManager.spawn(): 创建子代理
        """
        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
        )
