"""Web tools: web_search, web_fetch."""
import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse
import httpx
from loguru import logger
from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks
def _strip_tags(text: str) -> str:
    """
    移除 HTML 标签并解码实体。

    【架构职责】
    工具层文本处理,从 HTML 内容中移除标签,脚本、样式等元素,
    并解码 HTML 实体。

    【输入契约】
    - text: str(必选) - HTML 内容字符串
    【输出契约】
    - str - 处理后的纯文本
    【依赖模块】
    - re: 正则表达式
    - html: HTML 实体解码
    """
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()
def _normalize(text: str) -> str:
    """
    规范化空白字符。

    【架构职责】
    工具层文本处理,将多个连续空格/制表符压缩为单个空格/制表符。
    【输入契约】
    - text: str(必选) - 文本内容
    【输出契约】
    - str - 规范化后的文本
    【依赖模块】
    - re: 正则表达式
    """
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()
def _validate_url(url: str) -> tuple[bool, str]:
    """
    验证 URL 格式。

    【架构职责】
    工具层 URL 验证,检查 URL 是否为 http(s) 协议且并包含有效的域名。
    【输入契约】
    - url: str(必选) - 待验证的 URL
    【输出契约】
    - tuple[bool, str] - (is_valid, error_msg) 項元组
          - is_valid: 是否为有效 URL
          - error_msg: 错误信息
    【依赖模块】
    - urllib.parse.urlparse(): URL 解析
    """
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)
class WebSearchTool(Tool):
    """
    Web 搜索工具,使用 Brave Search API 搜索互联网。

    【架构分层】工具层 - Web 搜索模块
    【模块职责】提供 Web 搜索能力,通过 Brave Search API 搜索互联网信息并返回结果摘要。
    【核心依赖】
        - httpx: HTTP 客户端
        - Brave Search API: 第三方搜索服务
    """
    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }
    def __init__(self, api_key: str | None = None, max_results: int = 5, proxy: str | None = None):
        self._init_api_key = api_key
        self.max_results = max_results
        self.proxy = proxy
    @property
    def api_key(self) -> str:
        """
        获取 API 密钥。

        【架构职责】
        工具层配置获取,延迟获取 API 密钥,支持环境变量动态更新。
        【输入契约】
        无参数
        【输出契约】
        - str - API 密钥
        【依赖模块】
        - os.environ.get(): 空间环境变量获取
        """
        return self._init_api_key or os.environ.get("BRAVE_API_KEY", "")
    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        """
        执行 Web 搜索。

        【架构职责】
        工具层 Web 搜索,通过 Brave Search API 执行搜索并返回格式化结果。
        【输入契约】
        - query: str(必选) - 搜索查询词
        - count: int | None(可选) - 结果数量(1-10)
        【输出契约】
        - str - 格式化的搜索结果
        【依赖模块】
        - httpx.AsyncClient: HTTP 客户端
        - os.environ.get(): 环境变量获取
        【异常边界】
        - API 密钥缺失时返回配置错误
        - 代理错误时返回代理错误
        - 其他异常返回通用错误
        【性能说明】
        - 默认超时 10 秒
        - 最大结果数 10 个
        """
        if not self.api_key:
            return (
                "Error: Brave Search API key not configured. Set it in "
                "~/.nanobot/config.json under tools.web.search.apiKey "
                "(or export BRAVE_API_KEY), then restart the gateway."
            )
        try:
            n = min(max(count or self.max_results, 1), 10)
            logger.debug("WebSearch: {}", "proxy enabled" if self.proxy else "direct connection")
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    timeout=10.0
                )
                r.raise_for_status()
            results = r.json().get("web", {}).get("results", [])[:n]
            if not results:
                return f"No results for: {query}"
            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except httpx.ProxyError as e:
            logger.error("WebSearch proxy error: {}", e)
            return f"Proxy error: {e}"
        except Exception as e:
            logger.error("WebSearch error: {}", e)
            return f"Error: {e}"
class WebFetchTool(Tool):
    """
    Web 内容抓取工具,使用 Readability 从 URL 揫取可读内容。

    【架构分层】工具层 - Web 抓取模块
    【模块职责】提供 Web 内容抓取能力,从 URL 获取网页并使用 Readability 握取可读部分,
        支持 HTML 转文本和 Markdown 格式输出。
    【核心依赖】
        - httpx: HTTP 客户端
        - readability: HTML 内容提取库
    """
    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }
    def __init__(self, max_chars: int = 50000, proxy: str | None = None):
        self.max_chars = max_chars
        self.proxy = proxy
    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        """
        抓取 URL 内容。

        【架构职责】
        工具层内容抓取,从 URL 获取内容并使用 Readability 揍取可读部分。
        【输入契约】
        - url: str(必选) - 要抓取的 URL
        - extractMode: str(可选) - 提取模式, "markdown" 或 "text"
        - maxChars: int | None(可选) - 最大字符数
        【输出契约】
        - str - JSON 格式的抓取结果
        【依赖模块】
        - httpx.AsyncClient: HTTP 客户端
        - readability.Document: Readability 解析器
        - _validate_url(): URL 验证
        - _to_markdown(): HTML 转 Markdown
        【异常边界】
        - URL 验证失败时返回错误
        - 代理错误时返回代理错误
        - 其他异常返回通用错误
        【性能说明】
        - 默认最大 50000 字符
        - HTTP 超时 30 秒
        - 重定向限制 5 次
        """
        from readability import Document
        max_chars = maxChars or self.max_chars
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)
        try:
            logger.debug("WebFetch: {}", "proxy enabled" if self.proxy else "direct connection")
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0,
                proxy=self.proxy,
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else _strip_tags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = "raw"
            truncated = len(text) > max_chars
            if truncated: text = text[:max_chars]
            return json.dumps({"url": url, "finalUrl": str(r.url), "status": r.status_code,
                              "extractor": extractor, "truncated": truncated, "length": len(text), "text": text}, ensure_ascii=False)
        except httpx.ProxyError as e:
            logger.error("WebFetch proxy error for {}: {}", url, e)
            return json.dumps({"error": f"Proxy error: {e}", "url": url}, ensure_ascii=False)
        except Exception as e:
            logger.error("WebFetch error for {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)
    def _to_markdown(self, html: str) -> str:
        """
        将 HTML 转换为 Markdown。

        【架构职责】
        工具层格式转换,将 HTML 内容转换为 Markdown 格式。
        【输入契约】
        - html: str(必选) - HTML 内容
        【输出契约】
        - str - Markdown 格式的内容
        【依赖模块】
        - re: 正则表达式
        - _strip_tags(): 移除 HTML 标签
        - _normalize(): 规范化空白
        """
        # Convert links, headings, lists before stripping tags
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*]([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
