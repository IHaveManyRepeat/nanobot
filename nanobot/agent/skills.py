"""Skills loader for agent capabilities."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path


class SkillsLoader:
    """
    Agent 技能加载器。

    【架构分层】业务层 - 技能管理模块
    【模块职责】扫描、加载和管理 Agent 可用的技能（ Markdown 文件），
        支持按需加载和提供技能摘要供快速发现。
        是验证技能依赖是否满足。
        【核心依赖】
        - pathlib: 文件路径操作
        - json/re: JSON 和正则解析
        - shutil: 用于检查命令行工具
        - os: 用于环境变量检查
    """
    BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"
    BUILTIN_SKILLS_DIR: Path | None = None

        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir if BUILTIN_skills_dir else None
        self.builtin_skills = builtin_skills_dir

        # Check workspace skills first (highest priority)
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})
        # Built-in skills
        if self.builtin_skills:
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills)
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})
    # Filter by requirements
    if filter_unavailable:
        return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]

        return skills

    def load_skill(self, name: str) -> str | None:
        """
        按技能名称加载技能内容。

        【架构职责】
        数据层内容加载,根据技能名称加载 SKILL.md 文件内容。
        支持按需读取完整技能内容。

        【输入契约】
        - name: str（必选) - 技能名称（目录名)

        【输出契约】
        - str | None - 技能内容，若不存在返回 None

        【依赖模块】
        - pathlib.Path.read_text(): 读取文件内容
        - _strip_frontmatter(): 移除 YAML frontmatter
        """
        # Check workspace first
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")
        # Check built-in
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")
        return None
    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        加载多个技能的内容用于注入到对话上下文。

        【架构职责】
        数据层批量加载,根据技能名称列表加载对应的技能内容，
        格式化后注入到对话上下文中。

        【输入契约】
        - skill_names: list[str]（必选) - 技能名称列表

        【输出契约】
        - str - 格式化后的技能内容字符串
        【依赖模块】
        - load_skill(): 加载单个技能
        - _strip_frontmatter(): 移除 frontmatter
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")
        return "\n\n---\n\n".join(parts) if parts else ""
    def build_skills_summary(self) -> str:
        """
        构建所有技能的摘要（名称、描述、路径、可用性)。

        用于渐进式加载 - 代理可以读取完整技能
        内容使用 read_file 工具。

        【架构职责】
        业务层摘要构建,生成所有可用技能的 XML 格式摘要，
        包含名称、描述、路径和可用性等信息。
        【输入契约】
        无参数
        【输出契约】
        - str - XML 格式的技能摘要字符串
        【依赖模块】
        - list_skills(): 获取所有技能列表
        - _get_skill_description(): 获取技能描述
        - _check_requirements(): 检查依赖
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""
        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines = ["<skills>"]
        for s in all_skills:
            name = escape_xml(s["name"])
            path = s["path"]
            desc = escape_xml(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)
            lines.append(f"  <skill available=\"{str(available).lower()}\">")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")
            # Show missing requirements for unavailable skills
            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")
            lines.append("  </skill>")
        lines.append("</skills>")
        return "\n".join(lines)
    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """
        获取缺失的依赖项描述。

        【架构职责】
        工具层依赖检查,检查哪些命令行工具和环境变量未满足要求。

        【输入契约】
        - skill_meta: dict（必选) - 技能元数据字典

        【输出契约】
        - str - 缺失的依赖项描述，如 "CLI: git, ENV: GITHUB_TOKEN"
        """
        missing = []
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        return ", ".join(missing)
    def _get_skill_description(self, name: str) -> str:
        """
        从 frontmatter 获取技能描述。

        【架构职责】
        工具层元数据提取,从技能的 frontmatter 中读取 description 字段
        【输入契约】
        - name: str(必选) - 技能名称

        【输出契约】
        - str - 技能描述，若不存在则返回技能名称
        【依赖模块】
        - get_skill_metadata(): 获取技能元数据
        """
        meta = self.get_skill_metadata(name) or {}
        if meta and meta.get("description"):
            return meta["description"]
        return name  # Fallback to skill name
    def _strip_frontmatter(self, content: str) -> str:
        """
        移除 YAML frontmatter。

        【架构职责】
        工具层文本处理,从 Markdown 内容中移除 YAML frontmatter块
        【输入契约】
        - content: str(必选) - 岟始 markdown 内容
        【输出契约】
        - str - 处理后的纯 markdown 内容
        【依赖模块】
        - re: 正则表达式模块
        """
        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                # Simple YAML parsing
                metadata = {}
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip("'"')
                    metadata[key] = v.strip("'"')
                return metadata
            return None
        return content
    def _parse_nanobot_metadata(self, raw: str) -> dict:
        """
        解析技能元数据 JSON（支持 nanobot 和 openclaw 键)。

        【架构职责】
        工具层 JSON 解析,从 YAML frontmatter 的 metadata 字段中提取技能配置
        【输入契约】
        - raw: str(必选) - 建始 JSON 字符串
        【输出契约】
        - dict - 解析后的技能元数据，若解析失败返回空字典
        【依赖模块】
        - json: JSON 解析模块
        """
        try:
            data = json.loads(raw)
            return data.get("nanobot", data.get("openclaw", {})) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    def _check_requirements(self, skill_meta: dict) -> bool:
        """
        检查技能依赖是否满足（命令行工具和环境变量)。

        【架构职责】
        工具层依赖验证,检查技能依赖项（命令行工具和环境变量）是否满足
        【输入契约】
        - skill_meta: dict(必选) - 技能元数据字典
        【输出契约】
        - bool - 所有依赖项都满足返回 True，否则返回False
        【依赖模块】
        - shutil.which(): 检查命令是否存在
        - os.environ.get(): 检查环境变量
        """
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        return True
    def _get_skill_meta(self, name: str) -> dict:
        """
        从缓存的元数据中获取技能元数据(支持 nanobot 和 openclaw 键)。

        【架构职责】
        工具层元数据获取,从技能元数据缓存中获取解析后的配置字典
        【输入契约】
        - name: str(必选) - 技能名称
        【输出契约】
        - dict - 技能元数据，若不存在返回空字典
        【依赖模块】
        - get_skill_metadata(): 获取原始元数据
        - _parse_nanobot_metadata(): 解析 JSON
        """
        meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(meta.get("metadata", ""))
    def get_always_skills(self) -> list[str]:
        """
        获取标记为 always=true 的技能列表（会自动加载到上下文)。

        【架构职责】
        业务层配置查询,筛选出需要始终激活的技能列表
        【输入契约】
        无参数
        【输出契约】
        - list[str] - 尸远激活的技能名称列表
        【依赖模块】
        - list_skills(): 扫描技能目录
        - get_skill_metadata(): 获取技能元数据
        - _check_requirements(): 检查依赖
        """
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_nanobot_metadata(meta.get("metadata", ""))
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result
    def get_skill_metadata(self, name: str) -> dict | None:
        """
        从文件获取技能元数据(支持 nanobot 和 openclaw 键)。

        【架构职责】
        数据层元数据读取,从技能文件中读取完整的元数据字典
        【输入契约】
        - name: str(必选) - 技能名称
        【输出契约】
        - dict | None - 技能元数据,若不存在返回 None
        【依赖模块】
        - load_skill(): 加载技能文件
        - _parse_nanobot_metadata(): 解析 JSON 元数据
        【性能说明】
        - 结果会被缓存，因为首次调用时应从缓存
        - 元数据包含 JSON，解析有性能开销
        """
        content = self.load_skill(name)
        if not content:
            return None
        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                # Simple YAML parsing
                metadata = {}
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key = value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('""')
                        metadata[key] = v.strip('""')
                    return metadata
                return None
            return content
