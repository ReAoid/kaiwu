"""Web 内容抓取工具

支持 HTTP/HTTPS 请求，抓取网页内容并转换为可读格式。
参考: openclaw/src/agents/tools/web-fetch.ts

功能：
- 支持 HTTP/HTTPS 请求
- HTML 转 Markdown/Text
- 内容截断和清理
- 超时控制
- 重定向处理
- 内容清理（移除脚本、样式、隐藏元素）
- 内容长度限制
"""

import html
import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from core.tool import Tool, ToolParameter

logger = logging.getLogger(__name__)

# 提取模式
ExtractMode = Literal["markdown", "text"]
EXTRACT_MODES: List[ExtractMode] = ["markdown", "text"]
DEFAULT_EXTRACT_MODE: ExtractMode = "markdown"

# 默认配置
DEFAULT_MAX_CHARS = 50000
DEFAULT_MAX_RESPONSE_BYTES = 2000000  # 2MB
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# 隐藏元素的 CSS 类名
HIDDEN_CLASS_NAMES: Set[str] = {
    "sr-only",
    "visually-hidden",
    "d-none",
    "hidden",
    "invisible",
    "screen-reader-only",
    "offscreen",
}

# 需要移除的标签
REMOVE_TAGS: Set[str] = {
    "script", "style", "noscript", "head", "meta", "template",
    "svg", "canvas", "iframe", "object", "embed", "link",
}

# 零宽和不可见 Unicode 字符（用于防止提示注入攻击）
INVISIBLE_UNICODE_RE = re.compile(
    r'[\u200B-\u200F\u202A-\u202E\u2060-\u2064\u206A-\u206F\uFEFF]',
    re.UNICODE
)


@dataclass
class FetchResult:
    """抓取结果
    
    Attributes:
        url: 原始请求 URL
        final_url: 最终 URL（重定向后）
        status: HTTP 状态码
        content_type: 内容类型
        title: 页面标题（可选）
        text: 提取的文本内容
        extract_mode: 提取模式
        extractor: 使用的提取器
        truncated: 是否被截断
        length: 内容长度
        fetched_at: 抓取时间
        took_ms: 耗时（毫秒）
        error: 错误信息（可选）
    """
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    extract_mode: ExtractMode
    extractor: str
    truncated: bool
    length: int
    fetched_at: str
    took_ms: int
    title: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "url": self.url,
            "finalUrl": self.final_url,
            "status": self.status,
            "contentType": self.content_type,
            "extractMode": self.extract_mode,
            "extractor": self.extractor,
            "truncated": self.truncated,
            "length": self.length,
            "fetchedAt": self.fetched_at,
            "tookMs": self.took_ms,
            "text": self.text,
        }
        if self.title:
            result["title"] = self.title
        if self.error:
            result["error"] = self.error
        return result
    
    def to_json(self, indent: Optional[int] = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class ContentCleaner:
    """内容清理器
    
    清理 HTML 内容，移除脚本、样式、隐藏元素和不可见字符。
    参考: openclaw/src/agents/tools/web-fetch-visibility.ts
    
    功能：
    - 移除脚本和样式标签
    - 移除隐藏元素（aria-hidden, hidden 属性, 隐藏类名）
    - 移除不可见 Unicode 字符
    - 移除 HTML 注释
    - 移除内联样式中的隐藏元素
    """
    
    # 隐藏样式模式
    HIDDEN_STYLE_PATTERNS: List[Tuple[str, re.Pattern]] = [
        ("display", re.compile(r'^\s*none\s*$', re.IGNORECASE)),
        ("visibility", re.compile(r'^\s*hidden\s*$', re.IGNORECASE)),
        ("opacity", re.compile(r'^\s*0\s*$')),
        ("font-size", re.compile(r'^\s*0(px|em|rem|pt|%)?\s*$', re.IGNORECASE)),
        ("text-indent", re.compile(r'^\s*-\d{4,}px\s*$')),
        ("color", re.compile(r'^\s*transparent\s*$', re.IGNORECASE)),
    ]
    
    @staticmethod
    def clean(html_content: str) -> str:
        """清理 HTML 内容
        
        Args:
            html_content: 原始 HTML 内容
            
        Returns:
            清理后的 HTML 内容
        """
        if not html_content:
            return ""
        
        text = html_content
        
        # 1. 移除 HTML 注释
        text = re.sub(r'<!--[\s\S]*?-->', '', text)
        
        # 2. 移除需要删除的标签及其内容
        for tag in REMOVE_TAGS:
            text = re.sub(
                rf'<{tag}[^>]*>[\s\S]*?</{tag}>',
                '', text, flags=re.IGNORECASE
            )
            # 也移除自闭合标签
            text = re.sub(
                rf'<{tag}[^>]*/?>',
                '', text, flags=re.IGNORECASE
            )
        
        # 3. 移除带有 hidden 属性的元素
        text = re.sub(
            r'<[^>]+\shidden(?:\s|>|/>)[\s\S]*?</[^>]+>',
            '', text, flags=re.IGNORECASE
        )
        
        # 4. 移除带有 aria-hidden="true" 的元素
        text = re.sub(
            r'<[^>]+\saria-hidden\s*=\s*["\']true["\'][^>]*>[\s\S]*?</[^>]+>',
            '', text, flags=re.IGNORECASE
        )
        
        # 5. 移除带有隐藏类名的元素
        for class_name in HIDDEN_CLASS_NAMES:
            text = re.sub(
                rf'<[^>]+\sclass\s*=\s*["\'][^"\']*\b{class_name}\b[^"\']*["\'][^>]*>[\s\S]*?</[^>]+>',
                '', text, flags=re.IGNORECASE
            )
        
        # 6. 移除带有隐藏样式的元素
        text = ContentCleaner._remove_hidden_style_elements(text)
        
        # 7. 移除 input type="hidden"
        text = re.sub(
            r'<input[^>]+type\s*=\s*["\']hidden["\'][^>]*/?>',
            '', text, flags=re.IGNORECASE
        )
        
        return text
    
    @staticmethod
    def _remove_hidden_style_elements(html_content: str) -> str:
        """移除带有隐藏样式的元素
        
        Args:
            html_content: HTML 内容
            
        Returns:
            清理后的 HTML 内容
        """
        # 匹配带有 style 属性的标签
        def check_and_remove(match: re.Match) -> str:
            tag = match.group(0)
            style_match = re.search(r'style\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
            if style_match:
                style = style_match.group(1)
                if ContentCleaner._is_style_hidden(style):
                    return ''
            return tag
        
        # 简化处理：只移除明显隐藏的内联样式元素
        for prop, pattern in ContentCleaner.HIDDEN_STYLE_PATTERNS:
            # 匹配包含特定隐藏样式的元素
            html_content = re.sub(
                rf'<[^>]+style\s*=\s*["\'][^"\']*{prop}\s*:\s*none[^"\']*["\'][^>]*>[\s\S]*?</[^>]+>',
                '', html_content, flags=re.IGNORECASE
            )
        
        return html_content
    
    @staticmethod
    def _is_style_hidden(style: str) -> bool:
        """检查样式是否表示隐藏
        
        Args:
            style: CSS 样式字符串
            
        Returns:
            是否隐藏
        """
        for prop, pattern in ContentCleaner.HIDDEN_STYLE_PATTERNS:
            # 提取属性值
            match = re.search(rf'{prop}\s*:\s*([^;]+)', style, re.IGNORECASE)
            if match and pattern.match(match.group(1)):
                return True
        
        # 检查 width:0 + height:0 + overflow:hidden
        width_match = re.search(r'width\s*:\s*0(px)?\s*(?:;|$)', style, re.IGNORECASE)
        height_match = re.search(r'height\s*:\s*0(px)?\s*(?:;|$)', style, re.IGNORECASE)
        overflow_match = re.search(r'overflow\s*:\s*hidden\s*(?:;|$)', style, re.IGNORECASE)
        if width_match and height_match and overflow_match:
            return True
        
        # 检查负偏移定位
        left_match = re.search(r'left\s*:\s*-\d{4,}px', style, re.IGNORECASE)
        top_match = re.search(r'top\s*:\s*-\d{4,}px', style, re.IGNORECASE)
        if left_match or top_match:
            return True
        
        return False
    
    @staticmethod
    def strip_invisible_unicode(text: str) -> str:
        """移除不可见 Unicode 字符
        
        用于防止提示注入攻击。
        
        Args:
            text: 原始文本
            
        Returns:
            清理后的文本
        """
        return INVISIBLE_UNICODE_RE.sub('', text)


class HtmlToMarkdownConverter:
    """HTML 转 Markdown 转换器
    
    将 HTML 内容转换为 Markdown 格式，保留基本结构和链接。
    使用 html2text 库进行转换，如果不可用则回退到正则表达式方法。
    
    参考: openclaw/src/agents/tools/web-fetch.ts
    """
    
    # html2text 实例缓存
    _html2text_instance = None
    _html2text_available = None
    
    @classmethod
    def _get_html2text(cls):
        """获取 html2text 实例（懒加载）
        
        Returns:
            html2text.HTML2Text 实例，如果库不可用则返回 None
        """
        if cls._html2text_available is None:
            try:
                import html2text as h2t
                cls._html2text_instance = h2t.HTML2Text()
                # 配置 html2text
                cls._html2text_instance.ignore_links = False  # 保留链接
                cls._html2text_instance.ignore_images = False  # 保留图片
                cls._html2text_instance.ignore_emphasis = False  # 保留强调
                cls._html2text_instance.ignore_tables = False  # 保留表格
                cls._html2text_instance.body_width = 0  # 不自动换行
                cls._html2text_instance.unicode_snob = True  # 使用 Unicode
                cls._html2text_instance.skip_internal_links = False  # 保留内部链接
                cls._html2text_instance.inline_links = True  # 使用内联链接格式
                cls._html2text_instance.protect_links = True  # 保护链接不被截断
                cls._html2text_instance.wrap_links = False  # 不换行链接
                cls._html2text_instance.mark_code = False  # 不使用 [code] 标记，使用反引号
                cls._html2text_instance.default_image_alt = ""  # 默认图片 alt 文本
                cls._html2text_instance.single_line_break = False  # 使用双换行
                cls._html2text_available = True
                logger.debug("html2text 库已加载")
            except ImportError:
                cls._html2text_available = False
                logger.warning("html2text 库不可用，将使用正则表达式方法")
        
        return cls._html2text_instance if cls._html2text_available else None
    
    @staticmethod
    def convert(html_content: str) -> Tuple[str, Optional[str]]:
        """将 HTML 转换为 Markdown
        
        优先使用 html2text 库进行转换，如果不可用则回退到正则表达式方法。
        
        Args:
            html_content: HTML 内容
            
        Returns:
            (markdown_text, title) 元组
        """
        if not html_content:
            return "", None
        
        # 提取标题（在转换之前）
        title = HtmlToMarkdownConverter._extract_title(html_content)
        
        # 尝试使用 html2text 库
        h2t = HtmlToMarkdownConverter._get_html2text()
        if h2t is not None:
            try:
                markdown_text = HtmlToMarkdownConverter._convert_with_html2text(
                    html_content, h2t
                )
                return markdown_text, title
            except Exception as e:
                logger.warning(f"html2text 转换失败，回退到正则表达式方法: {e}")
        
        # 回退到正则表达式方法
        return HtmlToMarkdownConverter._convert_with_regex(html_content), title
    
    @staticmethod
    def _convert_with_html2text(html_content: str, h2t) -> str:
        """使用 html2text 库转换 HTML 到 Markdown
        
        Args:
            html_content: HTML 内容
            h2t: html2text.HTML2Text 实例
            
        Returns:
            Markdown 文本
        """
        # 使用 ContentCleaner 进行全面清理
        cleaned_html = ContentCleaner.clean(html_content)
        
        # 使用 html2text 转换
        markdown_text = h2t.handle(cleaned_html)
        
        # 后处理：规范化空白并移除不可见字符
        markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text)
        markdown_text = ContentCleaner.strip_invisible_unicode(markdown_text)
        markdown_text = markdown_text.strip()
        
        return markdown_text
    
    @staticmethod
    def _convert_with_regex(html_content: str) -> str:
        """使用正则表达式转换 HTML 到 Markdown（回退方法）
        
        Args:
            html_content: HTML 内容
            
        Returns:
            Markdown 文本
        """
        # 使用 ContentCleaner 进行全面清理
        text = ContentCleaner.clean(html_content)
        
        # 移除 head 部分（包含 title、meta 等）- ContentCleaner 已处理大部分
        text = re.sub(r'<head[^>]*>.*?</head>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 移除 HTML 注释
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        
        # 转换内联元素（先处理，因为它们可能嵌套在块级元素中）
        # 转换粗体（使用更精确的正则表达式避免匹配 <body> 等标签）
        text = re.sub(r'<(b|strong)(?:\s[^>]*)?>(.+?)</\1>', r'**\2**', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 转换斜体（使用更精确的正则表达式）
        text = re.sub(r'<(i|em)(?:\s[^>]*)?>(.+?)</\1>', r'*\2*', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 转换代码
        text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 转换链接（保留内部的 Markdown 格式）
        text = re.sub(
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
            lambda m: f'[{HtmlToMarkdownConverter._clean_link_text(m.group(2))}]({m.group(1)})',
            text,
            flags=re.DOTALL | re.IGNORECASE
        )
        
        # 转换块级元素
        # 转换标题标签
        for i in range(1, 7):
            text = re.sub(
                rf'<h{i}[^>]*>(.*?)</h{i}>',
                lambda m, level=i: f"\n{'#' * level} {HtmlToMarkdownConverter._clean_inline(m.group(1))}\n",
                text,
                flags=re.DOTALL | re.IGNORECASE
            )
        
        # 转换预格式化文本（在段落之前处理）
        text = re.sub(r'<pre[^>]*>(.*?)</pre>', r'\n```\n\1\n```\n', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 转换段落
        text = re.sub(r'<p[^>]*>(.*?)</p>', r'\n\1\n', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 转换换行
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        
        # 转换列表项
        text = re.sub(r'<li[^>]*>(.*?)</li>', r'\n- \1', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 转换引用
        text = re.sub(
            r'<blockquote[^>]*>(.*?)</blockquote>',
            lambda m: '\n> ' + m.group(1).replace('\n', '\n> ') + '\n',
            text,
            flags=re.DOTALL | re.IGNORECASE
        )
        
        # 移除剩余的 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        
        # 解码 HTML 实体
        text = html.unescape(text)
        
        # 规范化空白
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        text = '\n'.join(line.strip() for line in text.split('\n'))
        
        # 移除不可见 Unicode 字符
        text = ContentCleaner.strip_invisible_unicode(text)
        text = text.strip()
        
        return text
    
    @staticmethod
    def _extract_title(html_content: str) -> Optional[str]:
        """提取页面标题"""
        # 尝试从 <title> 标签提取
        match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.DOTALL | re.IGNORECASE)
        if match:
            title = html.unescape(match.group(1))
            title = re.sub(r'\s+', ' ', title).strip()
            return title if title else None
        return None
    
    @staticmethod
    def _clean_inline(text: str) -> str:
        """清理内联文本（移除所有 HTML 标签和 Markdown 格式）"""
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    @staticmethod
    def _clean_link_text(text: str) -> str:
        """清理链接文本（保留 Markdown 格式，只移除 HTML 标签）"""
        # 只移除 HTML 标签，保留已转换的 Markdown 格式
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text


class ContentExtractor:
    """内容提取器
    
    从 HTML 中提取可读内容，支持 Markdown 和纯文本模式。
    """
    
    @staticmethod
    def extract(
        content: str,
        content_type: str,
        extract_mode: ExtractMode = "markdown"
    ) -> Tuple[str, Optional[str], str]:
        """提取内容
        
        Args:
            content: 原始内容
            content_type: 内容类型
            extract_mode: 提取模式
            
        Returns:
            (text, title, extractor) 元组
        """
        content_type_lower = content_type.lower()
        
        # Markdown 内容直接返回
        if "text/markdown" in content_type_lower:
            if extract_mode == "text":
                return ContentExtractor._markdown_to_text(content), None, "cf-markdown"
            return content, None, "cf-markdown"
        
        # HTML 内容需要转换
        if "text/html" in content_type_lower:
            markdown_text, title = HtmlToMarkdownConverter.convert(content)
            if extract_mode == "text":
                return ContentExtractor._markdown_to_text(markdown_text), title, "html-converter"
            return markdown_text, title, "html-converter"
        
        # JSON 内容格式化
        if "application/json" in content_type_lower:
            try:
                parsed = json.loads(content)
                formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
                return formatted, None, "json"
            except json.JSONDecodeError:
                return content, None, "raw"
        
        # 其他内容直接返回
        return content, None, "raw"
    
    @staticmethod
    def _markdown_to_text(markdown: str) -> str:
        """将 Markdown 转换为纯文本"""
        if not markdown:
            return ""
        
        text = markdown
        
        # 移除 Markdown 标题标记
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        
        # 移除链接，保留文本
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        
        # 移除粗体/斜体标记
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
        text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
        
        # 移除代码标记
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'```[^`]*```', '', text, flags=re.DOTALL)
        
        # 移除引用标记
        text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
        
        # 移除列表标记
        text = re.sub(r'^[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
        
        # 规范化空白
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 移除不可见 Unicode 字符
        text = ContentCleaner.strip_invisible_unicode(text)
        text = text.strip()
        
        return text


class TextTruncator:
    """文本截断器"""
    
    @staticmethod
    def truncate(text: str, max_chars: int) -> Tuple[str, bool]:
        """截断文本到指定长度
        
        Args:
            text: 原始文本
            max_chars: 最大字符数
            
        Returns:
            (truncated_text, was_truncated) 元组
        """
        if not text or len(text) <= max_chars:
            return text, False
        
        # 尝试在单词/句子边界截断
        truncated = text[:max_chars]
        
        # 尝试在段落边界截断
        last_para = truncated.rfind('\n\n')
        if last_para > max_chars * 0.8:
            truncated = truncated[:last_para]
        else:
            # 尝试在句子边界截断
            last_sentence = max(
                truncated.rfind('. '),
                truncated.rfind('。'),
                truncated.rfind('! '),
                truncated.rfind('? ')
            )
            if last_sentence > max_chars * 0.8:
                truncated = truncated[:last_sentence + 1]
            else:
                # 尝试在单词边界截断
                last_space = truncated.rfind(' ')
                if last_space > max_chars * 0.8:
                    truncated = truncated[:last_space]
        
        return truncated.strip() + "\n\n[内容已截断...]", True


class UrlValidator:
    """URL 验证器"""
    
    @staticmethod
    def validate(url: str) -> Tuple[bool, Optional[str]]:
        """验证 URL
        
        Args:
            url: URL 字符串
            
        Returns:
            (is_valid, error_message) 元组
        """
        if not url:
            return False, "URL 不能为空"
        
        try:
            parsed = urllib.parse.urlparse(url)
            
            if parsed.scheme not in ("http", "https"):
                return False, "URL 必须是 http 或 https 协议"
            
            if not parsed.netloc:
                return False, "URL 缺少主机名"
            
            return True, None
            
        except Exception as e:
            return False, f"无效的 URL: {str(e)}"


class HttpFetcher:
    """HTTP 抓取器
    
    执行 HTTP/HTTPS 请求，处理重定向和超时。
    """
    
    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        user_agent: str = DEFAULT_USER_AGENT
    ):
        """初始化抓取器
        
        Args:
            timeout: 超时时间（秒）
            max_redirects: 最大重定向次数
            max_response_bytes: 最大响应字节数
            user_agent: User-Agent 字符串
        """
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.max_response_bytes = max_response_bytes
        self.user_agent = user_agent
    
    def fetch(self, url: str) -> Tuple[bytes, int, str, str]:
        """抓取 URL 内容
        
        Args:
            url: 要抓取的 URL
            
        Returns:
            (content, status_code, content_type, final_url) 元组
            
        Raises:
            urllib.error.URLError: 网络错误
            urllib.error.HTTPError: HTTP 错误
            TimeoutError: 超时
        """
        # 创建请求
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/markdown, text/html;q=0.9, */*;q=0.1",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
                "Accept-Encoding": "identity",  # 不使用压缩，简化处理
            }
        )
        
        # 创建 SSL 上下文（允许不验证证书，用于开发环境）
        ssl_context = ssl.create_default_context()
        
        # 创建自定义 opener 处理重定向
        redirect_handler = RedirectHandler(self.max_redirects)
        opener = urllib.request.build_opener(
            redirect_handler,
            urllib.request.HTTPSHandler(context=ssl_context)
        )
        
        # 执行请求
        response = opener.open(request, timeout=self.timeout)
        
        # 读取响应内容（限制大小）
        content = response.read(self.max_response_bytes)
        
        # 获取响应信息
        status_code = response.getcode() or 200
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        final_url = response.geturl() or url
        
        return content, status_code, content_type, final_url


class RedirectHandler(urllib.request.HTTPRedirectHandler):
    """自定义重定向处理器
    
    限制最大重定向次数。
    """
    
    def __init__(self, max_redirects: int = DEFAULT_MAX_REDIRECTS):
        super().__init__()
        self.max_redirects = max_redirects
        self.redirect_count = 0
    
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise urllib.error.HTTPError(
                newurl, code, f"超过最大重定向次数 ({self.max_redirects})", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class WebFetchTool(Tool):
    """Web 内容抓取工具
    
    抓取网页内容并转换为可读格式（Markdown 或纯文本）。
    
    功能：
    - 支持 HTTP/HTTPS 请求
    - HTML 转 Markdown/Text
    - 内容截断和清理
    - 超时控制
    - 重定向处理
    
    参考: openclaw/src/agents/tools/web-fetch.ts
    """
    
    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_chars: int = DEFAULT_MAX_CHARS,
        user_agent: str = DEFAULT_USER_AGENT
    ):
        """初始化工具
        
        Args:
            timeout: 超时时间（秒）
            max_redirects: 最大重定向次数
            max_response_bytes: 最大响应字节数
            max_chars: 最大返回字符数
            user_agent: User-Agent 字符串
        """
        super().__init__(
            name="web_fetch",
            description="抓取网页内容并转换为可读格式（Markdown 或纯文本）。用于获取网页内容，无需浏览器自动化。"
        )
        
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.max_response_bytes = max_response_bytes
        self.max_chars = max_chars
        self.user_agent = user_agent
        
        self._fetcher = HttpFetcher(
            timeout=timeout,
            max_redirects=max_redirects,
            max_response_bytes=max_response_bytes,
            user_agent=user_agent
        )
    
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义"""
        return [
            ToolParameter(
                name="url",
                type="string",
                description="要抓取的 HTTP 或 HTTPS URL",
                required=True
            ),
            ToolParameter(
                name="extract_mode",
                type="string",
                description=f"提取模式: {', '.join(EXTRACT_MODES)}。默认 {DEFAULT_EXTRACT_MODE}",
                required=False,
                default=DEFAULT_EXTRACT_MODE
            ),
            ToolParameter(
                name="max_chars",
                type="integer",
                description=f"最大返回字符数，默认 {DEFAULT_MAX_CHARS}",
                required=False,
                default=DEFAULT_MAX_CHARS
            )
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行抓取
        
        Args:
            parameters: 抓取参数
            
        Returns:
            JSON 格式的抓取结果
        """
        import time
        from datetime import datetime
        
        start_time = time.time()
        
        # 获取参数
        url = parameters.get("url", "")
        extract_mode = self._resolve_extract_mode(parameters.get("extract_mode"))
        max_chars = self._resolve_max_chars(parameters.get("max_chars"))
        
        # 验证 URL
        is_valid, error = UrlValidator.validate(url)
        if not is_valid:
            return self._error_response(error or "无效的 URL", url, start_time)
        
        try:
            # 执行抓取
            content_bytes, status, content_type, final_url = self._fetcher.fetch(url)
            
            # 检测编码并解码
            encoding = self._detect_encoding(content_type, content_bytes)
            try:
                content = content_bytes.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                content = content_bytes.decode("utf-8", errors="replace")
            
            # 提取内容
            text, title, extractor = ContentExtractor.extract(
                content, content_type, extract_mode
            )
            
            # 截断内容
            text, truncated = TextTruncator.truncate(text, max_chars)
            
            # 构建结果
            result = FetchResult(
                url=url,
                final_url=final_url,
                status=status,
                content_type=self._normalize_content_type(content_type),
                title=title,
                text=text,
                extract_mode=extract_mode,
                extractor=extractor,
                truncated=truncated,
                length=len(text),
                fetched_at=datetime.now().isoformat(),
                took_ms=int((time.time() - start_time) * 1000)
            )
            
            return result.to_json()
            
        except urllib.error.HTTPError as e:
            return self._error_response(
                f"HTTP 错误 {e.code}: {e.reason}",
                url, start_time, status=e.code
            )
        except urllib.error.URLError as e:
            return self._error_response(
                f"网络错误: {str(e.reason)}",
                url, start_time
            )
        except TimeoutError:
            return self._error_response(
                f"请求超时 ({self.timeout}秒)",
                url, start_time
            )
        except Exception as e:
            logger.exception(f"抓取失败: {url}")
            return self._error_response(
                f"抓取失败: {str(e)}",
                url, start_time
            )
    
    def _resolve_extract_mode(self, value: Any) -> ExtractMode:
        """解析提取模式"""
        if isinstance(value, str) and value.lower() in EXTRACT_MODES:
            return value.lower()  # type: ignore
        return DEFAULT_EXTRACT_MODE
    
    def _resolve_max_chars(self, value: Any) -> int:
        """解析最大字符数"""
        if isinstance(value, int) and value > 0:
            return min(value, self.max_chars)
        return self.max_chars
    
    def _detect_encoding(self, content_type: str, content: bytes) -> str:
        """检测内容编码"""
        # 从 Content-Type 头提取编码
        match = re.search(r'charset=([^\s;]+)', content_type, re.IGNORECASE)
        if match:
            return match.group(1).strip('"\'')
        
        # 从 HTML meta 标签提取编码
        head = content[:1024].decode("ascii", errors="ignore")
        match = re.search(r'<meta[^>]+charset=["\']?([^"\'\s>]+)', head, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # 默认 UTF-8
        return "utf-8"
    
    def _normalize_content_type(self, content_type: str) -> str:
        """规范化内容类型"""
        if not content_type:
            return "application/octet-stream"
        # 移除参数，只保留 MIME 类型
        parts = content_type.split(";")
        return parts[0].strip().lower()
    
    def _error_response(
        self,
        error: str,
        url: str,
        start_time: float,
        status: int = 0
    ) -> str:
        """生成错误响应"""
        import time
        from datetime import datetime
        
        result = FetchResult(
            url=url,
            final_url=url,
            status=status,
            content_type="",
            text="",
            extract_mode="markdown",
            extractor="none",
            truncated=False,
            length=0,
            fetched_at=datetime.now().isoformat(),
            took_ms=int((time.time() - start_time) * 1000),
            error=error
        )
        return result.to_json()

