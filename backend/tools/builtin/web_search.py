"""Web 搜索工具

支持多种搜索引擎（DuckDuckGo, Google, Bing）进行网络搜索。
参考: openclaw/src/agents/tools/web-search.ts

DuckDuckGo 为默认引擎，无需 API Key。
Google 和 Bing 需要配置相应的 API Key。

API Key 配置位置：
- config/config.json: 通用配置
- config/secrets.json: 敏感信息（API Key）- 不应提交到 git
"""

import html
import json
import logging
import re
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Literal, Optional, Union

from core.tool import Tool, ToolParameter
from config.settings import Settings

logger = logging.getLogger(__name__)

# 支持的搜索引擎
SearchProvider = Literal["duckduckgo", "google", "bing"]
SUPPORTED_PROVIDERS: List[SearchProvider] = ["duckduckgo", "google", "bing"]
DEFAULT_PROVIDER: SearchProvider = "duckduckgo"

# 默认配置
DEFAULT_SEARCH_COUNT = 5
MAX_SEARCH_COUNT = 10
DEFAULT_TIMEOUT_SECONDS = 30

# DuckDuckGo API (无需 API Key)
DUCKDUCKGO_API_URL = "https://api.duckduckgo.com/"

# Google Custom Search API
GOOGLE_SEARCH_API_URL = "https://www.googleapis.com/customsearch/v1"

# Bing Web Search API
BING_SEARCH_API_URL = "https://api.bing.microsoft.com/v7.0/search"


@dataclass
class SearchResult:
    """搜索结果
    
    Attributes:
        title: 结果标题
        url: 结果 URL
        description: 结果摘要/描述
        published: 发布日期（可选）
        site_name: 网站名称（可选）
        raw_data: 原始数据（可选，用于调试）
        relevance_score: 相关性分数（可选，用于排序）
    """
    title: str
    url: str
    description: str
    published: Optional[str] = None
    site_name: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = field(default=None, repr=False)
    relevance_score: float = field(default=0.0)
    
    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        """转换为字典
        
        Args:
            include_raw: 是否包含原始数据
            
        Returns:
            字典表示
        """
        result = {
            "title": self.title,
            "url": self.url,
            "description": self.description,
        }
        if self.published:
            result["published"] = self.published
        if self.site_name:
            result["site_name"] = self.site_name
        if self.relevance_score > 0:
            result["relevance_score"] = round(self.relevance_score, 4)
        if include_raw and self.raw_data:
            result["raw_data"] = self.raw_data
        return result
    
    def to_json(self, include_raw: bool = False, indent: Optional[int] = None) -> str:
        """转换为 JSON 字符串
        
        Args:
            include_raw: 是否包含原始数据
            indent: JSON 缩进
            
        Returns:
            JSON 字符串
        """
        return json.dumps(self.to_dict(include_raw), ensure_ascii=False, indent=indent)


@dataclass
class SearchResponse:
    """搜索响应
    
    Attributes:
        query: 搜索查询
        provider: 搜索引擎
        count: 结果数量
        results: 搜索结果列表
        error: 错误信息（可选）
        raw_response: 原始响应（可选，用于调试）
    """
    query: str
    provider: str
    count: int
    results: List[SearchResult]
    error: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = field(default=None, repr=False)
    
    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        """转换为字典
        
        Args:
            include_raw: 是否包含原始数据
            
        Returns:
            字典表示
        """
        result = {
            "query": self.query,
            "provider": self.provider,
            "count": self.count,
            "results": [r.to_dict(include_raw) for r in self.results],
        }
        if self.error:
            result["error"] = self.error
        if include_raw and self.raw_response:
            result["raw_response"] = self.raw_response
        return result
    
    def to_json(self, include_raw: bool = False, indent: Optional[int] = 2) -> str:
        """转换为 JSON 字符串
        
        Args:
            include_raw: 是否包含原始数据
            indent: JSON 缩进，默认 2
            
        Returns:
            JSON 字符串
        """
        return json.dumps(self.to_dict(include_raw), ensure_ascii=False, indent=indent)


# 排序方式
SortBy = Literal["relevance", "date", "title"]
SUPPORTED_SORT_BY: List[SortBy] = ["relevance", "date", "title"]
DEFAULT_SORT_BY: SortBy = "relevance"


class SearchResultSorter:
    """搜索结果排序器
    
    支持按相关性、日期、标题等方式对搜索结果进行排序。
    相关性排序基于查询词在标题和描述中的匹配程度计算分数。
    """
    
    @staticmethod
    def calculate_relevance_score(result: SearchResult, query: str) -> float:
        """计算搜索结果的相关性分数
        
        基于以下因素计算分数：
        1. 查询词在标题中的匹配（权重较高）
        2. 查询词在描述中的匹配
        3. 完全匹配 vs 部分匹配
        4. 匹配位置（越靠前分数越高）
        
        Args:
            result: 搜索结果
            query: 搜索查询
            
        Returns:
            相关性分数 (0.0 - 1.0)
        """
        if not query:
            return 0.0
        
        score = 0.0
        query_lower = query.lower().strip()
        query_words = query_lower.split()
        
        title_lower = (result.title or "").lower()
        desc_lower = (result.description or "").lower()
        
        # 1. 标题完全匹配（最高分）
        if query_lower in title_lower:
            score += 0.4
            # 标题开头匹配额外加分
            if title_lower.startswith(query_lower):
                score += 0.1
        
        # 2. 标题词匹配
        title_word_matches = sum(1 for word in query_words if word in title_lower)
        if query_words:
            score += 0.2 * (title_word_matches / len(query_words))
        
        # 3. 描述完全匹配
        if query_lower in desc_lower:
            score += 0.15
        
        # 4. 描述词匹配
        desc_word_matches = sum(1 for word in query_words if word in desc_lower)
        if query_words:
            score += 0.1 * (desc_word_matches / len(query_words))
        
        # 5. URL 包含查询词
        url_lower = (result.url or "").lower()
        if query_lower.replace(" ", "") in url_lower.replace("-", "").replace("_", ""):
            score += 0.05
        
        return min(score, 1.0)
    
    @classmethod
    def sort_by_relevance(
        cls,
        results: List[SearchResult],
        query: str,
        descending: bool = True
    ) -> List[SearchResult]:
        """按相关性排序搜索结果
        
        Args:
            results: 搜索结果列表
            query: 搜索查询
            descending: 是否降序排列（默认 True，最相关的在前）
            
        Returns:
            排序后的搜索结果列表
        """
        # 计算每个结果的相关性分数
        for result in results:
            result.relevance_score = cls.calculate_relevance_score(result, query)
        
        # 按分数排序
        return sorted(results, key=lambda r: r.relevance_score, reverse=descending)
    
    @staticmethod
    def sort_by_date(
        results: List[SearchResult],
        descending: bool = True
    ) -> List[SearchResult]:
        """按日期排序搜索结果
        
        Args:
            results: 搜索结果列表
            descending: 是否降序排列（默认 True，最新的在前）
            
        Returns:
            排序后的搜索结果列表
        """
        def get_date_key(result: SearchResult) -> str:
            # 没有日期的放在最后
            if not result.published:
                return "" if descending else "9999-99-99"
            return result.published
        
        return sorted(results, key=get_date_key, reverse=descending)
    
    @staticmethod
    def sort_by_title(
        results: List[SearchResult],
        descending: bool = False
    ) -> List[SearchResult]:
        """按标题字母顺序排序搜索结果
        
        Args:
            results: 搜索结果列表
            descending: 是否降序排列（默认 False，A-Z 顺序）
            
        Returns:
            排序后的搜索结果列表
        """
        return sorted(
            results,
            key=lambda r: (r.title or "").lower(),
            reverse=descending
        )
    
    @classmethod
    def sort(
        cls,
        results: List[SearchResult],
        query: str,
        sort_by: SortBy = "relevance",
        descending: bool = True
    ) -> List[SearchResult]:
        """排序搜索结果
        
        Args:
            results: 搜索结果列表
            query: 搜索查询（用于相关性排序）
            sort_by: 排序方式 ("relevance", "date", "title")
            descending: 是否降序排列
            
        Returns:
            排序后的搜索结果列表
        """
        if not results:
            return results
        
        if sort_by == "relevance":
            return cls.sort_by_relevance(results, query, descending)
        elif sort_by == "date":
            return cls.sort_by_date(results, descending)
        elif sort_by == "title":
            return cls.sort_by_title(results, descending)
        else:
            # 默认按相关性排序
            return cls.sort_by_relevance(results, query, descending)


class SearchResultFilter:
    """搜索结果过滤器
    
    支持按域名、关键词、日期范围等条件过滤搜索结果。
    """
    
    @staticmethod
    def filter_by_domains(
        results: List[SearchResult],
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """按域名过滤搜索结果
        
        Args:
            results: 搜索结果列表
            include_domains: 只包含这些域名的结果（可选）
            exclude_domains: 排除这些域名的结果（可选）
            
        Returns:
            过滤后的搜索结果列表
        """
        if not include_domains and not exclude_domains:
            return results
        
        filtered = []
        include_set = {d.lower() for d in (include_domains or [])}
        exclude_set = {d.lower() for d in (exclude_domains or [])}
        
        for result in results:
            domain = (result.site_name or "").lower()
            
            # 如果指定了包含域名，检查是否在列表中
            if include_set and not any(d in domain for d in include_set):
                continue
            
            # 检查是否在排除列表中
            if exclude_set and any(d in domain for d in exclude_set):
                continue
            
            filtered.append(result)
        
        return filtered
    
    @staticmethod
    def filter_by_keywords(
        results: List[SearchResult],
        must_contain: Optional[List[str]] = None,
        must_not_contain: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """按关键词过滤搜索结果
        
        Args:
            results: 搜索结果列表
            must_contain: 必须包含的关键词（可选）
            must_not_contain: 不能包含的关键词（可选）
            
        Returns:
            过滤后的搜索结果列表
        """
        if not must_contain and not must_not_contain:
            return results
        
        filtered = []
        must_contain_lower = [k.lower() for k in (must_contain or [])]
        must_not_contain_lower = [k.lower() for k in (must_not_contain or [])]
        
        for result in results:
            text = f"{result.title} {result.description}".lower()
            
            # 检查必须包含的关键词
            if must_contain_lower and not all(k in text for k in must_contain_lower):
                continue
            
            # 检查不能包含的关键词
            if must_not_contain_lower and any(k in text for k in must_not_contain_lower):
                continue
            
            filtered.append(result)
        
        return filtered
    
    @staticmethod
    def limit_results(
        results: List[SearchResult],
        max_results: int
    ) -> List[SearchResult]:
        """限制结果数量
        
        Args:
            results: 搜索结果列表
            max_results: 最大结果数量
            
        Returns:
            限制数量后的搜索结果列表
        """
        if max_results <= 0:
            return results
        return results[:max_results]
    
    @classmethod
    def filter_and_limit(
        cls,
        results: List[SearchResult],
        max_results: int,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        must_contain: Optional[List[str]] = None,
        must_not_contain: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """过滤并限制搜索结果
        
        Args:
            results: 搜索结果列表
            max_results: 最大结果数量
            include_domains: 只包含这些域名的结果（可选）
            exclude_domains: 排除这些域名的结果（可选）
            must_contain: 必须包含的关键词（可选）
            must_not_contain: 不能包含的关键词（可选）
            
        Returns:
            过滤并限制数量后的搜索结果列表
        """
        # 先按域名过滤
        filtered = cls.filter_by_domains(results, include_domains, exclude_domains)
        
        # 再按关键词过滤
        filtered = cls.filter_by_keywords(filtered, must_contain, must_not_contain)
        
        # 最后限制数量
        return cls.limit_results(filtered, max_results)


class SearchResultParser(ABC):
    """搜索结果解析器抽象基类
    
    定义搜索结果解析的通用接口，支持不同搜索引擎的结果解析。
    """
    
    @abstractmethod
    def parse(self, raw_data: Dict[str, Any], query: str, max_results: int) -> SearchResponse:
        """解析原始搜索结果
        
        Args:
            raw_data: 原始 API 响应数据
            query: 搜索查询
            max_results: 最大结果数量
            
        Returns:
            解析后的搜索响应
        """
        pass
    
    @staticmethod
    def clean_text(text: Optional[str]) -> str:
        """清理文本内容
        
        移除 HTML 标签、解码 HTML 实体、规范化空白字符。
        
        Args:
            text: 原始文本
            
        Returns:
            清理后的文本
        """
        if not text:
            return ""
        
        # 解码 HTML 实体
        text = html.unescape(text)
        
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        
        # 规范化空白字符
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    @staticmethod
    def extract_domain(url: str) -> Optional[str]:
        """从 URL 提取域名
        
        Args:
            url: URL 字符串
            
        Returns:
            域名，如果无法提取则返回 None
        """
        if not url:
            return None
        
        try:
            parsed = urllib.parse.urlparse(url)
            return parsed.netloc or None
        except Exception:
            return None
    
    @staticmethod
    def truncate_text(text: str, max_length: int = 500) -> str:
        """截断文本到指定长度
        
        Args:
            text: 原始文本
            max_length: 最大长度
            
        Returns:
            截断后的文本
        """
        if not text or len(text) <= max_length:
            return text
        
        # 尝试在单词边界截断
        truncated = text[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.8:
            truncated = truncated[:last_space]
        
        return truncated + "..."


class DuckDuckGoParser(SearchResultParser):
    """DuckDuckGo 搜索结果解析器
    
    解析 DuckDuckGo Instant Answer API 的响应。
    """
    
    def parse(self, raw_data: Dict[str, Any], query: str, max_results: int) -> SearchResponse:
        """解析 DuckDuckGo API 响应
        
        Args:
            raw_data: DuckDuckGo API 响应
            query: 搜索查询
            max_results: 最大结果数量
            
        Returns:
            解析后的搜索响应
        """
        results: List[SearchResult] = []
        
        # 解析主要结果（Abstract）
        if raw_data.get("Abstract"):
            results.append(SearchResult(
                title=self.clean_text(raw_data.get("Heading", query)),
                url=raw_data.get("AbstractURL", ""),
                description=self.clean_text(raw_data.get("Abstract", "")),
                site_name=raw_data.get("AbstractSource"),
                raw_data={"type": "abstract", "source": raw_data.get("AbstractSource")}
            ))
        
        # 解析相关主题
        results.extend(self._parse_related_topics(
            raw_data.get("RelatedTopics", []),
            max_results - len(results)
        ))
        
        # 解析直接结果
        results.extend(self._parse_results(
            raw_data.get("Results", []),
            max_results - len(results)
        ))
        
        return SearchResponse(
            query=query,
            provider="duckduckgo",
            count=len(results),
            results=results[:max_results],
            raw_response=raw_data
        )
    
    def _parse_related_topics(
        self,
        topics: List[Any],
        max_count: int
    ) -> List[SearchResult]:
        """解析相关主题
        
        Args:
            topics: 相关主题列表
            max_count: 最大数量
            
        Returns:
            搜索结果列表
        """
        results: List[SearchResult] = []
        
        for topic in topics:
            if len(results) >= max_count:
                break
            
            if not isinstance(topic, dict):
                continue
            
            # 普通主题
            if "Text" in topic:
                text = self.clean_text(topic.get("Text", ""))
                results.append(SearchResult(
                    title=self.truncate_text(text, 100),
                    url=topic.get("FirstURL", ""),
                    description=text,
                    site_name=self.extract_domain(topic.get("FirstURL", "")),
                    raw_data={"type": "related_topic"}
                ))
            # 子主题组
            elif "Topics" in topic:
                for subtopic in topic.get("Topics", []):
                    if len(results) >= max_count:
                        break
                    if isinstance(subtopic, dict) and "Text" in subtopic:
                        text = self.clean_text(subtopic.get("Text", ""))
                        results.append(SearchResult(
                            title=self.truncate_text(text, 100),
                            url=subtopic.get("FirstURL", ""),
                            description=text,
                            site_name=self.extract_domain(subtopic.get("FirstURL", "")),
                            raw_data={"type": "subtopic", "group": topic.get("Name")}
                        ))
        
        return results
    
    def _parse_results(
        self,
        results_data: List[Any],
        max_count: int
    ) -> List[SearchResult]:
        """解析直接结果
        
        Args:
            results_data: 结果列表
            max_count: 最大数量
            
        Returns:
            搜索结果列表
        """
        results: List[SearchResult] = []
        
        for item in results_data:
            if len(results) >= max_count:
                break
            
            if not isinstance(item, dict):
                continue
            
            text = self.clean_text(item.get("Text", ""))
            results.append(SearchResult(
                title=self.truncate_text(text, 100),
                url=item.get("FirstURL", ""),
                description=text,
                site_name=self.extract_domain(item.get("FirstURL", "")),
                raw_data={"type": "result"}
            ))
        
        return results


class GoogleParser(SearchResultParser):
    """Google Custom Search 结果解析器
    
    解析 Google Custom Search API 的响应。
    """
    
    def parse(self, raw_data: Dict[str, Any], query: str, max_results: int) -> SearchResponse:
        """解析 Google API 响应
        
        Args:
            raw_data: Google API 响应
            query: 搜索查询
            max_results: 最大结果数量
            
        Returns:
            解析后的搜索响应
        """
        results: List[SearchResult] = []
        
        for item in raw_data.get("items", [])[:max_results]:
            if not isinstance(item, dict):
                continue
            
            # 提取页面元数据
            pagemap = item.get("pagemap", {})
            metatags = pagemap.get("metatags", [{}])[0] if pagemap.get("metatags") else {}
            
            # 提取发布日期
            published = (
                metatags.get("article:published_time") or
                metatags.get("og:updated_time") or
                metatags.get("date") or
                item.get("snippet", "")[:10] if re.match(r'\d{4}-\d{2}-\d{2}', item.get("snippet", "")[:10]) else None
            )
            
            results.append(SearchResult(
                title=self.clean_text(item.get("title", "")),
                url=item.get("link", ""),
                description=self.clean_text(item.get("snippet", "")),
                published=published,
                site_name=item.get("displayLink"),
                raw_data={
                    "type": "google_result",
                    "kind": item.get("kind"),
                    "cacheId": item.get("cacheId"),
                }
            ))
        
        # 检查是否有错误
        error = None
        if "error" in raw_data:
            error_info = raw_data["error"]
            error = f"{error_info.get('code', 'Unknown')}: {error_info.get('message', 'Unknown error')}"
        
        return SearchResponse(
            query=query,
            provider="google",
            count=len(results),
            results=results,
            error=error,
            raw_response=raw_data
        )


class BingParser(SearchResultParser):
    """Bing Web Search 结果解析器
    
    解析 Bing Web Search API 的响应。
    """
    
    def parse(self, raw_data: Dict[str, Any], query: str, max_results: int) -> SearchResponse:
        """解析 Bing API 响应
        
        Args:
            raw_data: Bing API 响应
            query: 搜索查询
            max_results: 最大结果数量
            
        Returns:
            解析后的搜索响应
        """
        results: List[SearchResult] = []
        
        web_pages = raw_data.get("webPages", {})
        for item in web_pages.get("value", [])[:max_results]:
            if not isinstance(item, dict):
                continue
            
            # 提取域名
            display_url = item.get("displayUrl", "")
            site_name = display_url.split("/")[0] if display_url else None
            
            results.append(SearchResult(
                title=self.clean_text(item.get("name", "")),
                url=item.get("url", ""),
                description=self.clean_text(item.get("snippet", "")),
                published=item.get("dateLastCrawled"),
                site_name=site_name,
                raw_data={
                    "type": "bing_result",
                    "id": item.get("id"),
                    "language": item.get("language"),
                    "isFamilyFriendly": item.get("isFamilyFriendly"),
                }
            ))
        
        # 检查是否有错误
        error = None
        if "error" in raw_data:
            error_info = raw_data["error"]
            error = f"{error_info.get('code', 'Unknown')}: {error_info.get('message', 'Unknown error')}"
        
        return SearchResponse(
            query=query,
            provider="bing",
            count=len(results),
            results=results,
            error=error,
            raw_response=raw_data
        )


class SearchResultParserFactory:
    """搜索结果解析器工厂
    
    根据搜索引擎类型创建对应的解析器。
    """
    
    _parsers: Dict[str, SearchResultParser] = {
        "duckduckgo": DuckDuckGoParser(),
        "google": GoogleParser(),
        "bing": BingParser(),
    }
    
    @classmethod
    def get_parser(cls, provider: str) -> SearchResultParser:
        """获取指定搜索引擎的解析器
        
        Args:
            provider: 搜索引擎名称
            
        Returns:
            对应的解析器实例
            
        Raises:
            ValueError: 如果不支持该搜索引擎
        """
        parser = cls._parsers.get(provider.lower())
        if not parser:
            raise ValueError(f"不支持的搜索引擎: {provider}")
        return parser
    
    @classmethod
    def register_parser(cls, provider: str, parser: SearchResultParser) -> None:
        """注册自定义解析器
        
        Args:
            provider: 搜索引擎名称
            parser: 解析器实例
        """
        cls._parsers[provider.lower()] = parser
    
    @classmethod
    def supported_providers(cls) -> List[str]:
        """获取支持的搜索引擎列表
        
        Returns:
            搜索引擎名称列表
        """
        return list(cls._parsers.keys())


class WebSearchTool(Tool):
    """Web 搜索工具
    
    支持多种搜索引擎进行网络搜索：
    - DuckDuckGo: 默认引擎，无需 API Key
    - Google: 需要 Google Custom Search API Key 和 Search Engine ID
    - Bing: 需要 Bing Search API Key
    
    API Key 配置：
    - 在 config/config.json 中配置默认值
    - 在 config/secrets.json 中配置敏感信息（不应提交到 git）
    - 环境变量优先级最高
    
    搜索结果解析：
    - 使用 SearchResultParser 解析不同搜索引擎的响应
    - 提取标题、URL、摘要等信息
    - 支持 JSON 格式输出
    """
    
    def __init__(
        self,
        settings: Optional[Settings] = None,
        default_provider: Optional[str] = None,
        google_api_key: Optional[str] = None,
        google_cx: Optional[str] = None,
        bing_api_key: Optional[str] = None,
        timeout: Optional[int] = None
    ):
        """初始化工具
        
        Args:
            settings: 应用配置对象，如果提供则从中读取 API Key
            default_provider: 默认搜索引擎（覆盖配置）
            google_api_key: Google Custom Search API Key（覆盖配置）
            google_cx: Google Custom Search Engine ID（覆盖配置）
            bing_api_key: Bing Search API Key（覆盖配置）
            timeout: 请求超时时间（秒）（覆盖配置）
        """
        super().__init__(
            name="web_search",
            description="使用搜索引擎搜索网络内容，支持 DuckDuckGo、Google、Bing"
        )
        
        # 从配置中读取 API Key
        if settings is None:
            settings = Settings.load_from_file()
        
        web_search_config = settings.web_search
        
        # 优先级：参数 > 环境变量 > 配置文件
        self._default_provider = (
            default_provider or 
            web_search_config.default_provider or 
            DEFAULT_PROVIDER
        )
        
        self._google_api_key = (
            google_api_key or 
            web_search_config.google.api_key
        )
        
        self._google_cx = (
            google_cx or 
            web_search_config.google.search_engine_id
        )
        
        self._bing_api_key = (
            bing_api_key or 
            web_search_config.bing.api_key
        )
        
        self._timeout = (
            timeout or 
            web_search_config.timeout or 
            DEFAULT_TIMEOUT_SECONDS
        )
        
        # 初始化解析器工厂
        self._parser_factory = SearchResultParserFactory
    
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义"""
        return [
            ToolParameter(
                name="query",
                type="string",
                description="搜索查询字符串",
                required=True
            ),
            ToolParameter(
                name="provider",
                type="string",
                description=f"搜索引擎: {', '.join(SUPPORTED_PROVIDERS)}。默认 {DEFAULT_PROVIDER}",
                required=False,
                default=DEFAULT_PROVIDER
            ),
            ToolParameter(
                name="count",
                type="integer",
                description=f"返回结果数量 (1-{MAX_SEARCH_COUNT})，默认 {DEFAULT_SEARCH_COUNT}",
                required=False,
                default=DEFAULT_SEARCH_COUNT
            ),
            ToolParameter(
                name="region",
                type="string",
                description="地区代码，如 'cn', 'us', 'uk'。用于本地化搜索结果",
                required=False,
                default=None
            ),
            ToolParameter(
                name="language",
                type="string",
                description="语言代码，如 'zh', 'en', 'ja'。用于过滤搜索结果语言",
                required=False,
                default=None
            ),
            ToolParameter(
                name="safe_search",
                type="boolean",
                description="是否启用安全搜索，默认 True",
                required=False,
                default=True
            ),
            ToolParameter(
                name="sort_by",
                type="string",
                description=f"排序方式: {', '.join(SUPPORTED_SORT_BY)}。默认 {DEFAULT_SORT_BY}",
                required=False,
                default=DEFAULT_SORT_BY
            ),
            ToolParameter(
                name="sort_descending",
                type="boolean",
                description="是否降序排列，默认 True（相关性最高/最新的在前）",
                required=False,
                default=True
            ),
            ToolParameter(
                name="include_domains",
                type="string",
                description="只包含这些域名的结果，多个域名用逗号分隔",
                required=False,
                default=None
            ),
            ToolParameter(
                name="exclude_domains",
                type="string",
                description="排除这些域名的结果，多个域名用逗号分隔",
                required=False,
                default=None
            )
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行搜索
        
        Args:
            parameters: 搜索参数
            
        Returns:
            JSON 格式的搜索结果
        """
        query = parameters.get("query")
        if not query:
            return self._error_response("缺少 query 参数")
        
        query = str(query).strip()
        if not query:
            return self._error_response("query 参数不能为空")
        
        # 解析参数
        provider = self._resolve_provider(parameters.get("provider"))
        count = self._resolve_count(parameters.get("count"))
        region = parameters.get("region")
        language = parameters.get("language")
        safe_search = parameters.get("safe_search", True)
        
        # 解析排序和过滤参数
        sort_by = self._resolve_sort_by(parameters.get("sort_by"))
        sort_descending = parameters.get("sort_descending", True)
        include_domains = self._parse_domain_list(parameters.get("include_domains"))
        exclude_domains = self._parse_domain_list(parameters.get("exclude_domains"))
        
        # 检查 API Key
        if provider == "google" and (not self._google_api_key or not self._google_cx):
            return self._error_response(
                "Google 搜索需要配置 API Key 和 Search Engine ID",
                provider=provider
            )
        
        if provider == "bing" and not self._bing_api_key:
            return self._error_response(
                "Bing 搜索需要配置 API Key",
                provider=provider
            )
        
        # 执行搜索
        try:
            if provider == "duckduckgo":
                response = self._search_duckduckgo(
                    query=query,
                    count=count,
                    region=region,
                    safe_search=safe_search
                )
            elif provider == "google":
                response = self._search_google(
                    query=query,
                    count=count,
                    region=region,
                    language=language,
                    safe_search=safe_search
                )
            elif provider == "bing":
                response = self._search_bing(
                    query=query,
                    count=count,
                    region=region,
                    language=language,
                    safe_search=safe_search
                )
            else:
                return self._error_response(f"不支持的搜索引擎: {provider}")
            
            # 应用过滤
            if include_domains or exclude_domains:
                response.results = SearchResultFilter.filter_by_domains(
                    response.results,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains
                )
            
            # 应用排序
            response.results = SearchResultSorter.sort(
                response.results,
                query=query,
                sort_by=sort_by,
                descending=sort_descending
            )
            
            # 限制结果数量（过滤后可能超出）
            response.results = SearchResultFilter.limit_results(response.results, count)
            response.count = len(response.results)
            
            return self._format_response(response)
        
        except urllib.error.URLError as e:
            logger.error(f"搜索请求失败: {e}")
            return self._error_response(f"网络请求失败: {e}", provider=provider)
        except urllib.error.HTTPError as e:
            logger.error(f"搜索 API 错误: {e.code} - {e.reason}")
            return self._error_response(f"API 错误 ({e.code}): {e.reason}", provider=provider)
        except json.JSONDecodeError as e:
            logger.error(f"解析搜索结果失败: {e}")
            return self._error_response("解析搜索结果失败", provider=provider)
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return self._error_response(f"搜索失败: {e}", provider=provider)
    
    def _resolve_provider(self, provider: Optional[str]) -> SearchProvider:
        """解析搜索引擎
        
        Args:
            provider: 搜索引擎名称
            
        Returns:
            有效的搜索引擎名称
        """
        if not provider:
            return self._default_provider
        
        provider = str(provider).strip().lower()
        if provider in SUPPORTED_PROVIDERS:
            return provider  # type: ignore
        
        return self._default_provider
    
    def _resolve_count(self, count: Optional[Any]) -> int:
        """解析结果数量
        
        Args:
            count: 结果数量
            
        Returns:
            有效的结果数量
        """
        if count is None:
            return DEFAULT_SEARCH_COUNT
        
        try:
            count = int(count)
            return max(1, min(count, MAX_SEARCH_COUNT))
        except (ValueError, TypeError):
            return DEFAULT_SEARCH_COUNT
    
    def _resolve_sort_by(self, sort_by: Optional[str]) -> SortBy:
        """解析排序方式
        
        Args:
            sort_by: 排序方式
            
        Returns:
            有效的排序方式
        """
        if not sort_by:
            return DEFAULT_SORT_BY
        
        sort_by = str(sort_by).strip().lower()
        if sort_by in SUPPORTED_SORT_BY:
            return sort_by  # type: ignore
        
        return DEFAULT_SORT_BY
    
    def _parse_domain_list(self, domains: Optional[str]) -> Optional[List[str]]:
        """解析域名列表
        
        Args:
            domains: 逗号分隔的域名字符串
            
        Returns:
            域名列表，如果输入为空则返回 None
        """
        if not domains:
            return None
        
        domain_list = [d.strip() for d in str(domains).split(",") if d.strip()]
        return domain_list if domain_list else None
    
    def _search_duckduckgo(
        self,
        query: str,
        count: int,
        region: Optional[str] = None,
        safe_search: bool = True
    ) -> SearchResponse:
        """使用 DuckDuckGo 搜索
        
        DuckDuckGo Instant Answer API 返回即时答案和相关主题。
        注意：此 API 主要用于即时答案，不是传统的网页搜索结果。
        
        Args:
            query: 搜索查询
            count: 结果数量
            region: 地区代码
            safe_search: 是否启用安全搜索
            
        Returns:
            搜索响应
        """
        # 构建请求参数
        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1"
        }
        
        # 安全搜索
        if safe_search:
            params["kp"] = "1"  # Safe search on
        else:
            params["kp"] = "-1"  # Safe search off
        
        # 地区设置
        if region:
            params["kl"] = region
        
        # 发送请求
        url = f"{DUCKDUCKGO_API_URL}?{urllib.parse.urlencode(params)}"
        
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Kaiwu/1.0 (Web Search Tool)",
                "Accept": "application/json"
            }
        )
        
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        # 解析结果
        results: List[SearchResult] = []
        
        # 主要结果（Abstract）
        if data.get("Abstract"):
            results.append(SearchResult(
                title=data.get("Heading", query),
                url=data.get("AbstractURL", ""),
                description=data.get("Abstract", ""),
                site_name=data.get("AbstractSource")
            ))
        
        # 相关主题
        for topic in data.get("RelatedTopics", [])[:count - len(results)]:
            if isinstance(topic, dict):
                # 普通主题
                if "Text" in topic:
                    results.append(SearchResult(
                        title=topic.get("Text", "")[:100],
                        url=topic.get("FirstURL", ""),
                        description=topic.get("Text", "")
                    ))
                # 子主题组
                elif "Topics" in topic:
                    for subtopic in topic.get("Topics", []):
                        if len(results) >= count:
                            break
                        if isinstance(subtopic, dict) and "Text" in subtopic:
                            results.append(SearchResult(
                                title=subtopic.get("Text", "")[:100],
                                url=subtopic.get("FirstURL", ""),
                                description=subtopic.get("Text", "")
                            ))
        
        # 结果
        for result_item in data.get("Results", [])[:count - len(results)]:
            if isinstance(result_item, dict):
                results.append(SearchResult(
                    title=result_item.get("Text", "")[:100],
                    url=result_item.get("FirstURL", ""),
                    description=result_item.get("Text", "")
                ))
        
        return SearchResponse(
            query=query,
            provider="duckduckgo",
            count=len(results),
            results=results[:count]
        )
    
    def _search_google(
        self,
        query: str,
        count: int,
        region: Optional[str] = None,
        language: Optional[str] = None,
        safe_search: bool = True
    ) -> SearchResponse:
        """使用 Google Custom Search 搜索
        
        Args:
            query: 搜索查询
            count: 结果数量
            region: 地区代码
            language: 语言代码
            safe_search: 是否启用安全搜索
            
        Returns:
            搜索响应
        """
        # 构建请求参数
        params = {
            "key": self._google_api_key,
            "cx": self._google_cx,
            "q": query,
            "num": min(count, 10)  # Google API 最多返回 10 个结果
        }
        
        # 安全搜索
        if safe_search:
            params["safe"] = "active"
        else:
            params["safe"] = "off"
        
        # 地区设置
        if region:
            params["gl"] = region.upper()
        
        # 语言设置
        if language:
            params["lr"] = f"lang_{language}"
            params["hl"] = language
        
        # 发送请求
        url = f"{GOOGLE_SEARCH_API_URL}?{urllib.parse.urlencode(params)}"
        
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Kaiwu/1.0 (Web Search Tool)",
                "Accept": "application/json"
            }
        )
        
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        # 解析结果
        results: List[SearchResult] = []
        
        for item in data.get("items", [])[:count]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                description=item.get("snippet", ""),
                site_name=item.get("displayLink")
            ))
        
        return SearchResponse(
            query=query,
            provider="google",
            count=len(results),
            results=results
        )
    
    def _search_bing(
        self,
        query: str,
        count: int,
        region: Optional[str] = None,
        language: Optional[str] = None,
        safe_search: bool = True
    ) -> SearchResponse:
        """使用 Bing Web Search 搜索
        
        Args:
            query: 搜索查询
            count: 结果数量
            region: 地区代码
            language: 语言代码
            safe_search: 是否启用安全搜索
            
        Returns:
            搜索响应
        """
        # 构建请求参数
        params = {
            "q": query,
            "count": count,
            "responseFilter": "Webpages"
        }
        
        # 安全搜索
        if safe_search:
            params["safeSearch"] = "Moderate"
        else:
            params["safeSearch"] = "Off"
        
        # 地区和语言设置
        if region:
            params["cc"] = region.upper()
        
        if language:
            params["setLang"] = language
        
        # 发送请求
        url = f"{BING_SEARCH_API_URL}?{urllib.parse.urlencode(params)}"
        
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Kaiwu/1.0 (Web Search Tool)",
                "Accept": "application/json",
                "Ocp-Apim-Subscription-Key": self._bing_api_key
            }
        )
        
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        # 解析结果
        results: List[SearchResult] = []
        
        web_pages = data.get("webPages", {})
        for item in web_pages.get("value", [])[:count]:
            results.append(SearchResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                description=item.get("snippet", ""),
                published=item.get("dateLastCrawled"),
                site_name=item.get("displayUrl", "").split("/")[0] if item.get("displayUrl") else None
            ))
        
        return SearchResponse(
            query=query,
            provider="bing",
            count=len(results),
            results=results
        )
    
    def _format_response(self, response: SearchResponse) -> str:
        """格式化搜索响应为 JSON 字符串
        
        Args:
            response: 搜索响应
            
        Returns:
            JSON 格式的响应字符串
        """
        result = {
            "query": response.query,
            "provider": response.provider,
            "count": response.count,
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "description": r.description,
                    **({"published": r.published} if r.published else {}),
                    **({"site_name": r.site_name} if r.site_name else {})
                }
                for r in response.results
            ]
        }
        
        if response.error:
            result["error"] = response.error
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    def _error_response(
        self,
        message: str,
        provider: Optional[str] = None
    ) -> str:
        """生成错误响应
        
        Args:
            message: 错误消息
            provider: 搜索引擎名称
            
        Returns:
            JSON 格式的错误响应
        """
        result = {
            "error": message,
            "provider": provider or self._default_provider,
            "count": 0,
            "results": []
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
