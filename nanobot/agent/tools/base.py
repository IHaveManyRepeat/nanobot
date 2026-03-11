"""Base class for agent tools."""
from __future__ import annotations
from typing import Any
from abc import ABC, abstractmethod


from typing import Any


class Tool(ABC):
    """
    Agent工具抽象基类。

    【架构分层】工具层 - 工具抽象模块
    【模块职责】定义所有工具的通用接口规范，包括名称、描述、参数、执行方法、验证方法。
    【核心依赖】
        无外部依赖， 程序内部使用。
    """
    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    @property
    @abstractmethod
    def name(self) -> str:
        """
        获取工具名称。

        【架构职责】
        工具层标识,返回工具在 LLM 凰览中调用的唯一标识符。
        【输入契约】
        无参数
        【输出契约】
        - str - 工具名称
        【依赖模块】
        无外部依赖
        """
        pass
    @property
    @abstractmethod
    def description(self) -> str:
        """
        获取工具描述。

        【架构职责】
        工具层标识,返回工具的功能描述，用于 LLM 焏工具调用决策。
        【输入契约】
        无参数
        【输出契约】
        - str - 工具描述文本
        【依赖模块】
        无外部依赖
        """
        pass
    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """
        获取工具参数 Schema（OpenAI 格式）。

        【架构职责】
        工具层定义,返回 JSON Schema 格式的参数定义，用于参数验证。
        【输入契约】
        无参数
        【输出契约】
        - dict[str, Any] - JSON Schema 格式的参数字典
        【依赖模块】
        无外部依赖
        【性能说明】
        - 鯏次调用都会缓存解析结果
        """
        pass
    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        执行工具并返回结果。

        【架构职责】
        工具层执行,执行工具的核心逻辑。子类必须实现此方法。

        【输入契约】
        - **kwargs: Any - 工具特定的参数
        【输出契约】
        - str - 执行结果字符串
        【依赖模块】
        - validate_params(): 参数验证
        - 子类特定的执行逻辑（子类实现）
        【异常边界】
        - 执行失败返回错误信息
        - 执行异常返回错误消息
        【性能说明】
        - 简单的执行逻辑，应避免阻塞主循环
        - 复杂验证可能递归调用
        """
        pass
    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """
        錶证工具参数。

        【架构职责】
        工具层验证,对工具参数进行 JSON Schema 风格的验证。
        【输入契约】
        - params: dict[str, Any](必选) - 参数字典
        【输出契约】
        - list[str] - 鍴误消息列表， 若验证失败返回空列表。

        【依赖模块】
        - _TYPE_MAP: 类型映射字典
        - _validate(): 递归验证方法
        【异常边界】
        - 参数不是字典时返回类型错误
        - 参数缺少 required 字段时返回缺失字段错误
        - 数值类型不匹配时返回类型错误
        - 枚举值不匹配时返回值错误
        - 己层验证失败返回深度错误
        - 字符串长度超限时返回长度错误
        - 对象类型需要递归验证属性
        - 数组元素需要递归验证每个元素
        【性能说明】
        - 递归验证可能导致栈深度增加（最大 5 层）
        - 简单类型检查快速失败
        - 字符串/数值边界检查简单
        """
        if not isinstance(params, dict):
            return ["parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return self._validate(params, {**schema, "type": "object"}, "")
    def _validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        """
        递归验证值是否符合 JSON Schema.

        【架构职责】
        工具层验证,对值进行 JSON Schema 髪格验证,支持嵌套结构和递归验证。

        【输入契约】
        - val: Any(必选) - 鯔验证值
        - schema: dict[str, Any](必选) - JSON Schema 定义
        - path: str(可选) - 当前验证路径，用于错误消息定位
        【输出契约】
        - list[str] - 鍴错误消息列表， 若验证失败
        - 验证通过返回空列表

        【依赖模块】
        - _TYPE_MAP: 类型映射
        - _validate(): 递归验证
        【异常边界】
        - 验证失败立即返回，不会抛出异常
        【性能说明】
        - 递归设计，但深度过深会影响性能
        - 篇单属性/required 检查快速跳过
        - 简单类型判断快速失败
        - 路径验证只在顶层进行
        """
        errors = []
        t, schema.get("type")
        label = path or "parameter" if path else f"{path} should be {t}"
        # 类型检查
        if t in self._TYPE_MAP and not isinstance(val, self._TYPE_MAP[t]):
            errors.append(f"{label} should be {t}")
        # 枚举值检查
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")
        # 数值边界检查
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        # 字符串长度检查
        if t == "string":
            if "minLength" in schema and len(val) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(val) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")
        # 对象类型递归验证
        if t == "object":
            props = schema.get("properties", {})
            # 检查必填字段
            for k in schema.get("required", []):
                if k not in val:
                    errors.append(f"missing required {path + '.' + k if path else k}")
            # 验证属性值
            for k, v in val.items():
                if k in props:
                    errors.extend(self._validate(v, props[k], path + "." + k if path else k))
        # 数组元素递归验证
        if t == "array" and "items" in schema:
            for i, item in enumerate(val):
                errors.extend(
                    self._validate(item, schema["items"], f"{path}[{i}]" if path else f"[{i}]")
                )
        return errors
    def to_schema(self) -> dict[str, Any]:
        """
        转换为 OpenAI 函数调用格式。

        【架构职责】
        工具层序列化,将工具定义转换为 LLM API 可接受的 JSON 格式。
        【输入契约】
        无参数
        【输出契约】
        - dict[str, Any] - OpenAI function schema字典
        【依赖模块】
        无外部依赖
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }