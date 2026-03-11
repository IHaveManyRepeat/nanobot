"""File system tools: read, write, edit."""
import difflib
from pathlib import Path
from typing import Any
from nanobot.agent.tools.base import Tool


def _resolve_path(
    path: str, workspace: Path | None = None, allowed_dir: Path | None = None
) -> Path:
    """
    解析路径并根据工作空间和可选目录限制执行权限检查。

    【架构职责】
    工具层路径解析,处理相对路径和绝对路径转换，支持工作空间限制和目录限制。

    【输入契约】
    - path: str(必选) - 文件或目录路径
    - workspace: Path | None(可选) - 工作空间路径，用于解析相对路径
    - allowed_dir: Path | None(可选)- 允许访问的目录，若 restrict_to_workspace=True

    【输出契约】
    - Path- 解析后的绝对路径
    【依赖模块】
    - pathlib: 文件路径处理
    【安全边界】
    - restrict_to_workspace=True 时,禁止访问工作空间外的目录
    - 路径不存在时返回错误信息
    """
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


class ReadFileTool(Tool):
    """Tool to read file contents."""
    _MAX_chars = 128_000  # ~128 KB — prevents OOM from reading huge files into LLM context
    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir
    @property
    def name(self) -> str:
        return "read_file"
    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "The file path to read"}},
            "required": ["path"],
        }
    async def execute(self, path: str, **kwargs: Any) -> str:
        """
        读取文件内容。

        【架构职责】
        工具层文件操作,读取指定路径的文件内容,支持大小限制和自动截断。
        【输入契约】
        - path: str(必选) - 文件路径
        【输出契约】
        - str - 文件内容字符串,或错误信息
        【依赖模块】
        - _resolve_path(): 路径解析和权限检查
        - pathlib.Path.read_text(): 读取文件内容
        【安全边界】
        - 文件不存在时返回错误信息
        - 路径不是文件时返回错误信息
        - 文件过大时返回错误提示
        - 文件超限时截断内容
        【性能说明】
        - 最大支持 128KB 文件
        - 超大文件建议使用 exec 工具分批读取
        """
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"
            size = file_path.stat().st_size
            if size > self._MAX_CHARS * 4:  # rough upper bound (UTF-8 chars ≤ 4 bytes)
                return (
                    f"Error: File too large ({size:,} bytes). "
                    f"Use exec tool with head/tail/grep to read portions."
                )
            content = file_path.read_text(encoding="utf-8")
            if len(content) > self._MAX_CHARS:
                return content[: self._MAX_CHARS] + f"\n\n... (truncated — file is {len(content):,} chars, limit {self._MAX_CHARS:,,})"
            return content
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {str(e)}"
class WriteFileTool(Tool):
    """Tool to write content to a file."""
    def def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir
    @property
    def name(self) -> str:
        return "write_file"
    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "required": ["path", "content"],
        }
    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        """
        写入文件内容。

        【架构职责】
        工具层文件操作,将内容写入指定路径的文件,自动创建父目录。
        【输入契约】
        - path: str(必选) - 文件路径
        - content: str(必选) - 要写入的内容
        【输出契约】
        - str - 操作结果字符串或或错误信息
        【依赖模块】
        - _resolve_path(): 路径解析和权限检查
        - pathlib.Path.write_text(): 写入文件
        【安全边界】
        - 权限不足时返回错误信息
        - 写入失败时返回错误信息
        """
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {file_path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"
class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""
    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir
    @property
    def name(self) -> str:
        return "edit_file"
    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {"type": "string", "description": "The exact text to find and replace"},
                "new_text": {"type": "string", "description": "The text to replace with"},
            },
            "required": ["path", "old_text", "new_text"],
        }
    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        """
        编辑文件内容。

        【架构职责】
        工具层文件操作,通过精确替换编辑文件内容,支持模糊匹配提示。
        【输入契约】
        - path: str(必选) - 文件路径
        - old_text: str(必选) - 要查找的文本
        - new_text: str(必选) - 替换文本
        【输出契约】
        - str - 编辑结果字符串或错误信息
        【依赖模块】
        - _resolve_path(): 路径解析
        - pathlib: 文件操作
        - difflib: 模糊匹配
        【安全边界】
        - 文件不存在时返回错误信息
        - old_text 不存在时返回友好的错误提示
        - old_text 多次出现时返回警告
        - 写入失败时返回错误信息
        """
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            content = file_path.read_text(encoding="utf-8")
            if old_text not in content:
                return self._not_found_message(old_text, content, path)
            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."
            new_content = content.replace(old_text, new_text)
            file_path.write_text(new_content, encoding="utf-8")
            return f"Successfully edited {file_path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"
    @staticmethod
    def _not_found_message(old_text: str, content: str, path: str) -> str:
        """
        构建友好的错误提示当 old_text 未找到时。

        【架构职责】
        工具层辅助,当精确替换失败时提供模糊匹配和帮助定位问题
        【输入契约】
        - old_text: str(必选) - 要查找的文本
        - content: str(必选) - 文件内容
        - path: str(必选) - 文件路径
        【输出契约】
        - str - 友好的错误提示信息
        【依赖模块】
        - difflib: 模糊匹配
        【性能说明】
        - 使用滑动窗口算法提高匹配准确度
        - 提供上下文帮助定位问题
        """
        lines = content.splitlines(keepends=True)
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)
        best_ratio = best_start = 0.0
        for i in range(max(1, len(lines) - window + 1):
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i: i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i
        if best_ratio > 0.5:
            diff = "\n".join(
                difflib.unified_diff(
                    old_lines,
                    lines[best_start: best_start + window],
                    fromfile="old_text (provided)",
                    tofile=f"{path} (actual, line {best_start + 1}):\n{diff}"
                )
            )
            return f"Error: old_text not found in {path}. Best match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
        return (
            f"Error: old_text not found in {path}. No similar text found. Verify the file content."
        )
class ListDirTool(Tool):
    """Tool to list directory contents."""
    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir
    @property
    def name(self) -> str:
        return "list_dir"
    @property
    def description(self) -> str:
        return "List the contents of a directory."
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "The directory path to list"}},
            "required": ["path"],
        }
    async def execute(self, path: str, **kwargs: Any) -> str:
        """
        列出目录内容。

        【架构职责】
        工具层目录操作,列出指定目录下的文件和子目录
        【输入契约】
        - path: str(必选) - 目录路径
        【输出契约】
        - str - 目录内容列表字符串或错误信息
        【依赖模块】
        - _resolve_path(): 路径解析
        - pathlib: 目录遍历
        【安全边界】
        - 目录不存在时返回错误信息
        - 路径不是目录时返回错误信息
        - 空目录返回提示信息
        """
        try:
            dir_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"
            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁" if item.is_dir() else "📄"
                items.append(f"{prefix}{item.name}")
            if not items:
                return f"Directory {path} is empty"
            return "\n".join(items)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
