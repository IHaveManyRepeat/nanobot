"""Shell execution tool."""
import asyncio
import os
import re
from pathlib import Path
from typing import Any
from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """
    Shell 命令执行工具。

    【架构分层】工具层 - 命令执行模块
    【模块职责】提供安全的 Shell 命令执行能力,包括超时控制、工作目录限制、
    安全防护（黑名单和白名单机制)。
    【核心依赖】
    - asyncio: 异步子进程管理
    - os: 环境变量和路径操作
    - re: 正则表达式匹配
    """
    # Default dangerous command patterns (deny list)
    DENY_PATTERNS = [
        r"\brm\s+-[rf]{1,2}\b",          # rm -r. rm -rf. rm -fr
        r"\bdel\s+/[fq]\b",              # del /f. del /q
        r"\brmdir\s+/s\b",               # rmdir /s
        r"(?:^|[;&|]\s*)format\b",       # format (as standalone command only)
        r"\b(mkfs|diskpart)\b",          # disk operations
        r"\bdd\s+if=",                   # dd
        r">\s*/dev/sd",                  # write to disk
        r"\b(shutdown|reboot|poweroff)\b",  # system power
        r":\(\)\s*\{.*\};\s*:",          # fork bomb
    ]
    # Default timeout (60 seconds)
    DEFAULT_TIMEOUT = 60
    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        path_append: str = "",
    ):
        """
        初始化 Shell 执行工具。

        【架构职责】
        工具层初始化,配置 Shell 命令执行环境,包括超时、工作目录、安全限制等。

        【输入契约】
        - timeout: int(可选) - 寽令超时时间(秒)
        - working_dir: str | None(可选) - 工作目录
        - deny_patterns: list[str] | None(可选) - 黑名单命令模式列表
        - allow_patterns: list[str] | None(可选) - 白名单命令模式列表
        - restrict_to_workspace: bool(可选) - 是否限制到工作空间,默认 False
        - path_append: str(可选) - PATH 环境变量追加路径

        【输出契约】
        无返回值,初始化实例属性。
        【依赖模块】
        - asyncio: 异步子进程管理
        - os: 环境变量和路径操作
        - re: 正则表达式匹配
        【安全边界】
        - 黑名单模式阻止危险命令
        - 白名单模式限制可执行范围
        - restrict_to_workspace=True 时检查路径遍历
        【性能说明】
        - 默认超时 60 秒
        - 子进程独立运行,不阻塞主循环
        """
        self.timeout = timeout
        self.working_dir = working_dir
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r. rm -rf. rm -fr
            r"\bdel\s+/[fq]\b",              # del /f. del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"(?:^|[;&|]\s*)format\b",       # format (as standalone command only)
            r"\b(mkfs|diskpart)\b",          # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append
    @property
    def name(self) -> str:
        return "exec"
    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command"
                }
            },
            "required": ["command"]
        }

    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        """
        执行 Shell 命令并返回输出。

        【架构职责】
        工具层命令执行,在安全限制范围内执行 Shell 命令并返回标准输出/错误输出。
        【输入契约】
        - command: str(必选) - 要执行的 Shell 命令
        - working_dir: str | None(可选) - 工作目录（覆盖默认）
        【输出契约】
        - str - 匽令执行结果（标准输出 + 错误输出 + 退出码)
        【依赖模块】
        - asyncio.create_subprocess_shell(): 创建子进程
        - _guard_command(): 安全检查
        【安全边界】
        - 危险命令被阻止
        - 超时强制终止
        - 输出超过 10000 字符时截断
        【性能说明】
        - 单次执行时间取决于命令复杂度
        - 最大输出 10000 字符
        """
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                # Wait for the process to fully terminate so pipes are
                # drained and file descriptors are released.
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return f"Error: Command timed out after {self.timeout} seconds"

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate very long output
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"

            return result

        except Exception as e:
            return f"Error executing command: {str(e)}"
    def _guard_command(self, command: str, cwd: str) -> str | None:
        """
        安全检查命令，防止危险操作。

        【架构职责】
        工具层安全检查,对 Shell 命令进行安全验证,阻止危险命令执行。
        【输入契约】
        - command: str(必选) - 嚾检查的命令字符串
        - cwd: str(必选) - 当前工作目录
        【输出契约】
        - str | None - 验证通过，无返回
        - str - 错误信息,验证失败时返回错误描述
        【依赖模块】
        - re: 正则表达式匹配
        - self.deny_patterns: 黑名单列表
        - self.allow_patterns: 白名单列表
        【安全边界】
        - 黑名单模式匹配时阻止
        - 白名单模式匹配时阻止
        - restrict_to_workspace=True 时检查路径遍历
        """
        cmd = command.strip()
        lower = cmd.lower()
        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"
        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"
        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"
            cwd_path = Path(cwd).resolve()
            for raw in self._extract_absolute_paths(command):
                try:
                    p = Path(raw.strip()).resolve()
                except Exception:
                    continue
                if p.is_absolute() and cwd_path not in p.parents:
    def _extract_absolute_paths(self, command: str) -> list[str]:
        """
        从命令中提取所有绝对路径。

        【架构职责】
        工具层路径解析,从 Shell 命令中提取 Windows 和 POSIX 风格的绝对路径,
        用于路径遍历安全检查。

        【输入契约】
        - command: str(必选) - Shell 嚽令字符串
        【输出契约】
        - list[str] - 提取到的绝对路径列表
        【依赖模块】
        - re: 正则表达式匹配
        """
        win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|<;]+", command)   # Windows: C:\...
        posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", command) # POSIX: /absolute only
        return win_paths + posix_paths