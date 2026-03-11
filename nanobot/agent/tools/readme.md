# Tools 模块
> 【架构分层: 工具层 - Agent 工具实现模块】

本目录实现 nanobot 的 Agent 工具集， 是 Agent 与外部世界交互的接口

## 模块定位
- **架构层**: 工具层
- **逻辑模块**: Agent 工具
- **核心职责**: 实现 Agent 可调用的各种工具， 包括文件操作、Shell 执行、网络请求等

## 工具清单

| 工具 | 文件 | 职责 | 安全性 |
|------|------|------|--------|
| ReadFileTool | filesystem.py | 读取文件内容 | 可限制目录 |
| WriteFileTool | filesystem.py | 写入文件 | 可限制目录 |
| EditFileTool | filesystem.py | 编辑文件 | 可限制目录 |
| ListDirTool | filesystem.py | 列出目录 | 可限制目录 |
| ExecTool | shell.py | 执行 Shell 命令 | 沙箱、超时 |
| WebSearchTool | web.py | Web 搜索 | 需要 API Key |
| WebFetchTool | web.py | 获取网页内容 | 支持代理 |
| MessageTool | message.py | 发送消息 | - |
| SpawnTool | spawn.py | 创建子 Agent | - |
| CronTool | cron.py | 定时任务 | - |
| MCPTool | mcp.py | MCP 协议工具 | - |

## 核心接口

### 工具基类
```python
class BaseTool(ABC):
    name: str                    # 工具名称
    description: str             # 工具描述

    @abstractmethod
    def get_schema(self) -> dict:
        """返回 JSON Schema 格式的工具定义"""

    @abstractmethod
    async def execute(self, params: dict) -> dict:
        """执行工具， 返回结果"""
```

### 工具注册
```python
class ToolRegistry:
    def register(self, tool: BaseTool) -> None:
        """注册工具"""

    def get(self, name: str) -> BaseTool:
        """获取工具"""

    def get_all_schemas(self) -> list[dict]:
        """获取所有工具的 Schema"""
```

## 安全机制

### 文件系统隔离
```python
allowed_dir = workspace if restrict_to_workspace else None
# 限制文件操作只能在 allowed_dir 内
```

### Shell 执行沙箱
```python
ExecTool(
    working_dir=str(workspace),
    timeout=30,                    # 超时 30 秒
    restrict_to_workspace=True,    # 限制在工作目录
    path_append="",                # PATH 追加
)
```

## 文件协作与角色

| 文件 | 架构角色 | 职责 |
|------|----------|------|
| `base.py` | 接口定义 | 定义 BaseTool 抽象基类 |
| `registry.py` | 核心实现 | 工具注册和管理 |
| `filesystem.py` | 文件工具 | 文件读写、编辑、列表 |
| `shell.py` | Shell 工具 | 命令执行 |
| `web.py` | 网络工具 | Web 搜索和获取 |
| `message.py` | 消息工具 | 发送消息到渠道 |
| `spawn.py` | 子代理工具 | 创建和管理子 Agent |
| `cron.py` | 定时工具 | 定时任务管理 |
| `mcp.py` | MCP 工具 | MCP 协议集成 |

## 架构优缺点

### 优点
- ✅ **统一接口**: 所有工具实现相同接口
- ✅ **安全隔离**: 支持工作目录限制
- ✅ **可扩展**: 添加新工具只需继承 BaseTool
- ✅ **JSON Schema**: 工具定义标准化

### 缺点
- ⚠️ **无权限控制**: 工具级别无细粒度权限
- ⚠️ **无审计**: 工具调用无审计日志
- ⚠️ **无限制**: 部分工具无资源限制

### 改进建议
1. 增加工具调用审计日志
2. 支持工具级别的权限配置
3. 增加资源使用限制 (如文件大小)
