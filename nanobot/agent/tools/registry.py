"""Tool registry for dynamic tool management."""
from typing import Any
from nanobot.agent.tools.base import Tool


class ToolRegistry:
    """
    Agent工具注册表,动态管理工具的注册、执行和验证。
    支持按需加载完整技能内容。

    【架构分层】工具层 - 工具注册模块
    【模块职责】提供工具注册、验证、执行等能力,管理工具生命周期。
    【核心依赖】
    - Tool: 工具基类
    【输出契约】
    - ToolRegistry 实例
    """
    def __init__(self):
        self._tools: dict[str, Tool] = {}
    def register(self, tool: Tool) -> None:
        """
        注册工具到注册表。

        【架构职责】
        工具层注册,将工具实例添加到内部工具字典中。

        【输入契约】
        - tool: Tool(必选) - 工具实例
        【输出契约】
        无返回值。
        """
        self._tools[tool.name] = tool
    def unregister(self, name: str) -> None:
        """
        从注册表移除工具。

        【架构职责】
        工具层注销,从注册表中移除指定名称的工具。

        【输入契约】
        - name: str(必选) - 工具名称
        【输出契约】
        无返回值。
        """
        self._tools.pop(name, None)
    def get(self, name: str) -> Tool | None:
        """
        按名称获取工具实例。

        【架构职责】
        工具层查询,从注册表中获取指定名称的工具实例。

        【输入契约】
        - name: str(必选) - 工具名称
        【输出契约】
        - Tool | None - 工具实例，若不存在返回 None
        """
        return self._tools.get(name)
    def has(self, name: str) -> bool:
        """
        检查工具是否已注册。

        【架构职责】
        工具层查询,检查指定工具是否在注册表中注册。

        【输入契约】
        - name: str(必选) - 工具名称
        【输出契约】
        - bool - True 表示已注册, False 表示未注册
        """
        return name in self._tools
    def get_definitions(self) -> list[dict[str, Any]]:
        """
        获取所有工具的 OpenAI 函数定义格式。

        【架构职责】
        工具层序列化,将注册表中的所有工具转换为 OpenAI Function Calling 格式。
        用于 LLM 巄型调用。

        【输入契约】
        无参数
        【输出契约】
        - list[dict[str, Any]] - 工具定义列表
        【依赖模块】
        - Tool: 工具基类
        """
        return [tool.to_schema() for tool in self._tools.values()]
    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """
        执行指定工具并返回结果。

        【架构职责】
        工具层执行,根据工具名称和参数执行工具,返回执行结果。
        包含参数验证、错误处理和执行提示。

        【输入契约】
        - name: str(必选) - 工具名称
        - params: dict[str, Any](必选) - 工具参数
        【输出契约】
        - str - 工具执行结果或错误信息
        【依赖模块】
        - Tool: 工具基类
        - ToolRegistry: 工具注册表

        【异常边界】
        - 工具不存在时返回友好错误
        - 参数验证失败时返回详细错误信息
        - 执行异常时返回错误信息
        【并发说明】
        - 使用 HINT 注释引导 LLM 分析错误
        - 执行时捕获异常并返回友好错误信息
        """
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
        try:
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)
            
            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + _HINT
    @property
    def tool_names(self) -> list[str]:
        """
        获取所有已注册的工具名称列表。

        【架构职责】
        工具层查询,返回注册表中所有工具的名称列表。
        【输入契约】
        无参数
        【输出契约】
        - list[str] - 工具名称列表
        """
        return list(self._tools.keys())
    def __len__(self) -> int:
        return len(self._tools)
    def __contains__(self, name: str) -> bool:
        return name in self._tools
