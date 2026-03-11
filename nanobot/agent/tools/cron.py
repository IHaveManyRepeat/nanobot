"""Cron tool for scheduling reminders and tasks."""
from contextvars import ContextVar
from typing import Any
from nanobot.agent.tools.base import Tool
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule


class CronTool(Tool):
    """
    定时任务工具,用于调度提醒和定时任务。

    【架构分层】工具层 - 定时任务模块
    【模块职责】提供定时任务能力,支持添加、列表、删除提醒和定时任务。
        【核心依赖】
        - Tool: 工具基类
        - CronService: 定时任务服务
    """
    name = "cron"
    description = "Schedule reminders and recurring tasks. Actions: add, list, remove."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "remove"],
                "description": "Action to perform",
            },
            "message": {"type": "string", "description": "Reminder message (for add)"},
            "every_seconds": {
                "type": "integer",
                "description": "Interval in seconds (for recurring tasks)",
            },
            "cron_expr": {
                "type": "string",
                "description": "Cron expression like '0 9 * * *' (for scheduled tasks)",
            },
            "tz": {
                "type": "string",
                "description": "IANA timezone for cron expressions (e.g. 'America/Vancouver')",
            },
            "at": {
                "type": "string",
                "description": "ISO datetime for one-time execution (e.g. '2026-02-12T10:30:00')",
            },
            "job_id": {"type": "string", "description": "Job ID (for remove)"},
        },
        "required": ["action"]
    }
    def __init__(self, cron_service: CronService):
        self._cron = cron_service
        self._channel = ""
        self._chat_id = ""
        self._in_cron_context: ContextVar[bool] = ContextVar("cron_in_context", default=False)
    def set_context(self, channel: str, chat_id: str) -> None:
        """
        设置当前会话上下文。

        【架构职责】
        工具层上下文设置,设置消息发送的目标通道和聊天 ID。
        【输入契约】
        - channel: str(必选) - 通道名称
        - chat_id: str(必选) - 聊天 ID
        【输出契约】
        无返回值, 更新实例属性。
        【依赖模块】
        无外部依赖
        """
        self._channel = channel
        self._chat_id = chat_id
    def set_cron_context(self, active: bool):
        """
        标记工具是否在定时任务回调中执行。

        【架构职责】
        工具层状态标记,标记当前是否在定时任务回调中执行。
        【输入契约】
        - active: bool(必选) - 是否在定时任务回调中
        【输出契约】
        无返回值。 更新上下文变量。
        【依赖模块】
        - contextvars.ContextVar: 上下文变量
        """
        return self._in_cron_context.set(active)
    def reset_cron_context(self, token) -> None:
        """
        恢复之前的定时任务上下文。

        【架构职责】
        工具层状态恢复,恢复之前保存的定时任务上下文。
        【输入契约】
        - token: ContextToken | None(可选) - 上下文令牌
        【输出契约】
        无返回值, 重置上下文变量。
        【依赖模块】
        - contextvars.ContextVar: 上下文变量
        """
        self._in_cron_context.reset(token)
    @property
    def name(self) -> str:
        return "cron"
    @property
    def description(self) -> str:
        return "Schedule reminders and recurring tasks. Actions: add, list, remove."
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove"],
                    "description": "Action to perform",
                },
                "message": {"type": "string", "description": "Reminder message (for add)"},
                "every_seconds": {
                    "type": "integer",
                    "description": "Interval in seconds (for recurring tasks)",
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Cron expression like '0 9 * * *' (for scheduled tasks)",
                },
                "tz": {
                    "type": "string",
                    "description": "IANA timezone for cron expressions (e.g. 'America/Vancouver')",
                },
                "at": {
                    "type": "string",
                    "description": "ISO datetime for one-time execution (e.g. '2026-02-12T10:30:00')",
                },
                "job_id": {"type": "string", "description": "Job ID (for remove)"},
            },
            "required": ["action"]
        }
    async def execute(
        self,
        action: str,
        message: str = "",
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        tz: str | None = None,
        at: str | None = None,
        job_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        执行定时任务操作。

        【架构职责】
        工具层命令执行,根据 action类型执行添加、列表或删除定时任务。
        【输入契约】
        - action: str(必选) - 操作类型:add/list/remove
        - message: str(可选) - 提醒消息（添加时)
        - every_seconds: int(可选) - 间隔秒数（添加时)
        - cron_expr: str(可选) - Cron 表达式(添加时)
        - tz: str(可选) - 时区(添加时)
        - at: str(可选) - 一次性执行时间(添加时)
        - job_id: str(可选) - 任务 ID(删除时)
        【输出契约】
        - str - 操作结果消息
        【依赖模块】
        - CronService: 定时任务服务
        - _add_job(): 添加任务
        - _list_jobs(): 刋出任务列表
        - _remove_job(): 刃除任务
        【异常边界】
        - 在定时任务回调中执行时阻止添加新任务
        - 缺少消息/时间/表达式/时区返回错误
        - 缺少会话上下文时返回错误
        - 任务 ID 缺失时返回错误
        """
        if action == "add":
            if self._in_cron_context.get():
                return "Error: cannot schedule new jobs from within a cron job execution"
            return self._add_job(message, every_seconds, cron_expr, tz, at)
        elif action == "list":
            return self._list_jobs()
        elif action == "remove":
            return self._remove_job(job_id)
        return f"Unknown action: {action}"
    def _add_job(
        self,
        message: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
    ) -> str:
        """
        添加定时任务。

        【架构职责】
        工具层任务添加,创建新的定时任务并添加到调度服务中。
        【输入契约】
        - message: str(必选) - 提醒消息
        - every_seconds: int(可选) - 间隔秒数
        - cron_expr: str(可选) - Cron 表达式
        - tz: str(可选) - 时区
        - at: str(可选) - 一次性执行时间
        【输出契约】
        - str - 创建结果消息
        【依赖模块】
        - CronService.add_job(): 添加任务
        - CronSchedule: 调度配置
        - zoneinfo.ZoneInfo: 时区验证
        - datetime.fromisoformat: 时间解析
        【异常边界】
        - 缺少消息时返回错误
        - 缺少会话上下文时返回错误
        - 使用 tz 但没有 cron_expr 时返回错误
        - 时区验证失败时返回错误
        - 时间格式错误时返回错误
        - 缺少调度参数时返回错误
        """
        if not message:
            return "Error: message is required for add"
        if not self._channel or not self._chat_id:
            return "Error: no session context (channel/chat_id)"
        if tz and not cron_expr:
            return "Error: tz can only be used with cron_expr"
        if tz:
            from zoneinfo import ZoneInfo

            try:
                ZoneInfo(tz)
            except (KeyError, Exception):
                return f"Error: unknown timezone '{tz}'"
        # Build schedule
        delete_after = False
        if every_seconds:
            schedule = CronSchedule(type="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = CronSchedule(type="cron", expr=cron_expr, tz=tz)
        elif at:
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(at)
            except ValueError:
                return f"Error: invalid ISO datetime format '{at}'. Expected format: YYYY-MM-DDTHH:MM:SS"
            at_ms = int(dt.timestamp() * 1000)
            schedule = CronSchedule(type="at", at_ms=at_ms)
            delete_after = True
        else:
            return "Error: either every_seconds, cron_expr, or at is required"
        job = self._cron.add_job(
            name=message[:30],
            schedule=schedule,
            message=message,
            deliver=True,
            channel=self._channel,
            to=self._chat_id,
            delete_after_run=delete_after,
        )
        return f"Created job '{job.name}' (id: {job.id})"
    def _list_jobs(self) -> str:
        """
        列出所有定时任务。

        【架构职责】
        工具层查询,列出所有已调度的定时任务。
        【输入契约】
        无参数
        【输出契约】
        - str - 任务列表字符串
        【依赖模块】
        - CronService.list_jobs(): 查询任务列表
        """
        jobs = self._cron.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        lines = [f"- {j.name} (id: {j.id}, {j.schedule.kind})" for j in jobs]
        return "Scheduled jobs:\n" + "\n".join(lines)
    def _remove_job(self, job_id: str | None) -> str:
        """
        删除定时任务。

        【架构职责】
        工具层任务删除,根据 ID 删除指定的定时任务。
        【输入契约】
        - job_id: str(必选) - 任务 ID
        【输出契约】
        - str - 刴除结果消息
        【依赖模块】
        - CronService.remove_job(): 刬除任务
        【异常边界】
        - job_id 缺失时返回错误
        - 任务不存在时返回提示信息
        """
        if not job_id:
            return "Error: job_id is required for remove"
        if self._cron.remove_job(job_id):
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"
