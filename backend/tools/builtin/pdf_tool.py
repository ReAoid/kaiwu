"""PDF 处理工具

支持 PDF 读取、文本提取和元数据获取。
参考: openclaw/src/agents/tools/pdf-tool.ts

功能：
- 支持从文件路径或 URL 读取 PDF
- 提取 PDF 文本内容
- 支持页码范围选择
- 提取 PDF 元数据（页数、标题、作者等）
- 支持多种 PDF 库（PyMuPDF, pypdf）
"""

import base64
import io
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from core.tool import Tool, ToolParameter

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_MAX_PAGES = 50
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class PDFMetadata:
    """PDF 元数据
    
    Attributes:
        page_count: 总页数
        title: 文档标题
        author: 作者
        subject: 主题
        creator: 创建程序
        producer: PDF 生成器
        creation_date: 创建日期
        modification_date: 修改日期
        keywords: 关键词
        encrypted: 是否加密
        file_size: 文件大小（字节）
    """
    page_count: int
    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    creator: Optional[str] = None
    producer: Optional[str] = None
    creation_date: Optional[str] = None
    modification_date: Optional[str] = None
    keywords: Optional[str] = None
    encrypted: bool = False
    file_size: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（只包含非空值）"""
        result: Dict[str, Any] = {
            "pageCount": self.page_count,
            "fileSize": self.file_size,
            "encrypted": self.encrypted,
        }
        
        if self.title:
            result["title"] = self.title
        if self.author:
            result["author"] = self.author
        if self.subject:
            result["subject"] = self.subject
        if self.creator:
            result["creator"] = self.creator
        if self.producer:
            result["producer"] = self.producer
        if self.creation_date:
            result["creationDate"] = self.creation_date
        if self.modification_date:
            result["modificationDate"] = self.modification_date
        if self.keywords:
            result["keywords"] = self.keywords
        
        return result


@dataclass
class PDFPage:
    """PDF 页面内容
    
    Attributes:
        page_number: 页码（从 1 开始）
        text: 页面文本内容
        width: 页面宽度（点）
        height: 页面高度（点）
    """
    page_number: int
    text: str
    width: float = 0.0
    height: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "pageNumber": self.page_number,
            "text": self.text,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class PDFResult:
    """PDF 处理结果
    
    Attributes:
        source: PDF 来源（文件路径或 URL）
        source_type: 来源类型（file, url）
        metadata: PDF 元数据
        pages: 提取的页面列表
        full_text: 完整文本内容
        error: 错误信息（可选）
    """
    source: str
    source_type: Literal["file", "url"]
    metadata: Optional[PDFMetadata] = None
    pages: List[PDFPage] = field(default_factory=list)
    full_text: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result: Dict[str, Any] = {
            "source": self.source,
            "sourceType": self.source_type,
        }
        if self.metadata:
            result["metadata"] = self.metadata.to_dict()
        if self.pages:
            result["pages"] = [p.to_dict() for p in self.pages]
        if self.full_text:
            result["fullText"] = self.full_text
        if self.error:
            result["error"] = self.error
        return result
    
    def to_json(self, indent: Optional[int] = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class PDFLoader:
    """PDF 加载器
    
    支持从文件路径或 URL 加载 PDF。
    """
    
    def __init__(
        self,
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT
    ):
        """初始化加载器
        
        Args:
            max_bytes: 最大文件大小（字节）
            timeout: 网络请求超时（秒）
            user_agent: User-Agent 字符串
        """
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.user_agent = user_agent
    
    def load(self, source: str) -> Tuple[bytes, Literal["file", "url"]]:
        """加载 PDF 数据
        
        Args:
            source: PDF 来源（文件路径或 URL）
            
        Returns:
            (pdf_bytes, source_type) 元组
            
        Raises:
            ValueError: 无效的来源
            FileNotFoundError: 文件不存在
            urllib.error.URLError: 网络错误
        """
        source = source.strip()
        
        # 判断来源类型
        if source.startswith(("http://", "https://")):
            return self._load_url(source), "url"
        elif source.startswith("file://"):
            file_path = source[7:]  # 移除 file:// 前缀
            return self._load_file(file_path), "file"
        else:
            # 假设是文件路径
            return self._load_file(source), "file"
    
    def _load_file(self, path: str) -> bytes:
        """从文件加载 PDF
        
        Args:
            path: 文件路径
            
        Returns:
            PDF 字节数据
        """
        # 展开 ~ 路径
        if path.startswith("~"):
            path = str(Path(path).expanduser())
        
        file_path = Path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        
        if not file_path.is_file():
            raise ValueError(f"路径不是文件: {path}")
        
        # 检查文件大小
        file_size = file_path.stat().st_size
        if file_size > self.max_bytes:
            raise ValueError(
                f"文件过大: {file_size} 字节，最大允许 {self.max_bytes} 字节"
            )
        
        # 检查文件扩展名
        if file_path.suffix.lower() != ".pdf":
            logger.warning(f"文件扩展名不是 .pdf: {path}")
        
        return file_path.read_bytes()
    
    def _load_url(self, url: str) -> bytes:
        """从 URL 加载 PDF
        
        Args:
            url: PDF URL
            
        Returns:
            PDF 字节数据
        """
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/pdf,*/*",
            }
        )
        
        ssl_context = ssl.create_default_context()
        
        with urllib.request.urlopen(
            request, timeout=self.timeout, context=ssl_context
        ) as response:
            # 检查内容类型
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
                logger.warning(f"URL 内容类型可能不是 PDF: {content_type}")
            
            # 检查内容大小
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > self.max_bytes:
                raise ValueError(
                    f"PDF 过大: {content_length} 字节，最大允许 {self.max_bytes} 字节"
                )
            
            # 读取内容（限制大小）
            data = response.read(self.max_bytes + 1)
            if len(data) > self.max_bytes:
                raise ValueError(
                    f"PDF 过大: 超过 {self.max_bytes} 字节"
                )
            
            return data


def parse_page_range(page_range: str, max_pages: int) -> List[int]:
    """解析页码范围字符串
    
    支持格式：
    - "1" - 单页
    - "1-5" - 范围
    - "1,3,5" - 列表
    - "1-3,5,7-9" - 混合
    
    Args:
        page_range: 页码范围字符串
        max_pages: 最大页数限制
        
    Returns:
        页码列表（从 1 开始）
    """
    pages: List[int] = []
    
    for part in page_range.split(","):
        part = part.strip()
        if not part:
            continue
        
        if "-" in part:
            # 范围格式
            try:
                start, end = part.split("-", 1)
                start_num = int(start.strip())
                end_num = int(end.strip())
                if start_num > 0 and end_num >= start_num:
                    pages.extend(range(start_num, min(end_num + 1, max_pages + 1)))
            except ValueError:
                logger.warning(f"无效的页码范围: {part}")
        else:
            # 单页
            try:
                page_num = int(part)
                if 0 < page_num <= max_pages:
                    pages.append(page_num)
            except ValueError:
                logger.warning(f"无效的页码: {part}")
    
    # 去重并排序
    return sorted(set(pages))


class PDFExtractor:
    """PDF 文本提取器
    
    支持使用 PyMuPDF (fitz) 或 pypdf 进行文本提取。
    优先使用 PyMuPDF，如果不可用则尝试 pypdf。
    """
    
    _pymupdf_available: Optional[bool] = None
    _pypdf_available: Optional[bool] = None
    
    @classmethod
    def _check_pymupdf(cls) -> bool:
        """检查 PyMuPDF 是否可用"""
        if cls._pymupdf_available is None:
            try:
                import fitz
                cls._pymupdf_available = True
                logger.debug("PyMuPDF (fitz) 已加载")
            except ImportError:
                cls._pymupdf_available = False
                logger.debug("PyMuPDF (fitz) 不可用")
        return cls._pymupdf_available
    
    @classmethod
    def _check_pypdf(cls) -> bool:
        """检查 pypdf 是否可用"""
        if cls._pypdf_available is None:
            try:
                import pypdf
                cls._pypdf_available = True
                logger.debug("pypdf 已加载")
            except ImportError:
                cls._pypdf_available = False
                logger.debug("pypdf 不可用")
        return cls._pypdf_available
    
    @classmethod
    def is_available(cls) -> bool:
        """检查是否有可用的 PDF 库"""
        return cls._check_pymupdf() or cls._check_pypdf()
    
    @classmethod
    def get_available_library(cls) -> Optional[str]:
        """获取可用的 PDF 库名称"""
        if cls._check_pymupdf():
            return "pymupdf"
        elif cls._check_pypdf():
            return "pypdf"
        return None
    
    @classmethod
    def extract(
        cls,
        pdf_data: bytes,
        pages: Optional[List[int]] = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        library: Optional[str] = None
    ) -> Tuple[PDFMetadata, List[PDFPage]]:
        """提取 PDF 内容
        
        Args:
            pdf_data: PDF 字节数据
            pages: 要提取的页码列表（从 1 开始），None 表示所有页
            max_pages: 最大页数限制
            library: 指定 PDF 库（pymupdf, pypdf），None 则自动选择
            
        Returns:
            (metadata, pages) 元组
            
        Raises:
            RuntimeError: 没有可用的 PDF 库
        """
        # 确定使用的库
        if library:
            if library == "pymupdf" and not cls._check_pymupdf():
                raise RuntimeError("PyMuPDF 不可用，请安装 pymupdf 包")
            elif library == "pypdf" and not cls._check_pypdf():
                raise RuntimeError("pypdf 不可用，请安装 pypdf 包")
        else:
            library = cls.get_available_library()
            if not library:
                raise RuntimeError(
                    "没有可用的 PDF 库。请安装 pymupdf 或 pypdf"
                )
        
        # 执行提取
        if library == "pymupdf":
            return cls._extract_with_pymupdf(pdf_data, pages, max_pages)
        elif library == "pypdf":
            return cls._extract_with_pypdf(pdf_data, pages, max_pages)
        else:
            raise RuntimeError(f"未知的 PDF 库: {library}")
    
    @classmethod
    def _extract_with_pymupdf(
        cls,
        pdf_data: bytes,
        pages: Optional[List[int]],
        max_pages: int
    ) -> Tuple[PDFMetadata, List[PDFPage]]:
        """使用 PyMuPDF 提取 PDF 内容
        
        Args:
            pdf_data: PDF 字节数据
            pages: 要提取的页码列表
            max_pages: 最大页数限制
            
        Returns:
            (metadata, pages) 元组
        """
        import fitz
        
        # 打开 PDF
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        
        try:
            # 提取元数据
            pdf_metadata = doc.metadata or {}
            metadata = PDFMetadata(
                page_count=doc.page_count,
                title=pdf_metadata.get("title") or None,
                author=pdf_metadata.get("author") or None,
                subject=pdf_metadata.get("subject") or None,
                creator=pdf_metadata.get("creator") or None,
                producer=pdf_metadata.get("producer") or None,
                creation_date=pdf_metadata.get("creationDate") or None,
                modification_date=pdf_metadata.get("modDate") or None,
                keywords=pdf_metadata.get("keywords") or None,
                encrypted=doc.is_encrypted,
                file_size=len(pdf_data),
            )
            
            # 确定要提取的页码
            if pages:
                page_nums = [p for p in pages if 0 < p <= doc.page_count][:max_pages]
            else:
                page_nums = list(range(1, min(doc.page_count + 1, max_pages + 1)))
            
            # 提取页面内容
            extracted_pages: List[PDFPage] = []
            for page_num in page_nums:
                page = doc[page_num - 1]  # fitz 使用 0-based 索引
                text = page.get_text()
                rect = page.rect
                
                extracted_pages.append(PDFPage(
                    page_number=page_num,
                    text=text.strip(),
                    width=rect.width,
                    height=rect.height,
                ))
            
            return metadata, extracted_pages
            
        finally:
            doc.close()
    
    @classmethod
    def _extract_with_pypdf(
        cls,
        pdf_data: bytes,
        pages: Optional[List[int]],
        max_pages: int
    ) -> Tuple[PDFMetadata, List[PDFPage]]:
        """使用 pypdf 提取 PDF 内容
        
        Args:
            pdf_data: PDF 字节数据
            pages: 要提取的页码列表
            max_pages: 最大页数限制
            
        Returns:
            (metadata, pages) 元组
        """
        import pypdf
        
        # 打开 PDF
        reader = pypdf.PdfReader(io.BytesIO(pdf_data))
        
        # 提取元数据
        pdf_metadata = reader.metadata or {}
        
        # pypdf 元数据键可能带有 / 前缀
        def get_meta(key: str) -> Optional[str]:
            value = pdf_metadata.get(key) or pdf_metadata.get(f"/{key}")
            return str(value) if value else None
        
        metadata = PDFMetadata(
            page_count=len(reader.pages),
            title=get_meta("Title"),
            author=get_meta("Author"),
            subject=get_meta("Subject"),
            creator=get_meta("Creator"),
            producer=get_meta("Producer"),
            creation_date=get_meta("CreationDate"),
            modification_date=get_meta("ModDate"),
            keywords=get_meta("Keywords"),
            encrypted=reader.is_encrypted,
            file_size=len(pdf_data),
        )
        
        # 确定要提取的页码
        page_count = len(reader.pages)
        if pages:
            page_nums = [p for p in pages if 0 < p <= page_count][:max_pages]
        else:
            page_nums = list(range(1, min(page_count + 1, max_pages + 1)))
        
        # 提取页面内容
        extracted_pages: List[PDFPage] = []
        for page_num in page_nums:
            page = reader.pages[page_num - 1]  # pypdf 使用 0-based 索引
            text = page.extract_text() or ""
            
            # 获取页面尺寸
            mediabox = page.mediabox
            width = float(mediabox.width) if mediabox else 0.0
            height = float(mediabox.height) if mediabox else 0.0
            
            extracted_pages.append(PDFPage(
                page_number=page_num,
                text=text.strip(),
                width=width,
                height=height,
            ))
        
        return metadata, extracted_pages


class PDFTool(Tool):
    """PDF 处理工具
    
    支持 PDF 读取、文本提取和元数据获取。
    
    Parameters:
        path: PDF 文件路径或 URL
        pages: 页码范围（可选，如 "1-5", "1,3,5"）
        max_pages: 最大提取页数（可选，默认 50）
        metadata_only: 是否只提取元数据（可选，默认 False）
    """
    
    def __init__(
        self,
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout: int = DEFAULT_TIMEOUT_SECONDS
    ):
        """初始化 PDF 工具
        
        Args:
            max_bytes: 最大文件大小（字节）
            timeout: 网络请求超时（秒）
        """
        super().__init__(
            name="pdf_read",
            description="读取 PDF 文件并提取文本内容和元数据。支持从文件路径或 URL 读取，支持页码范围选择。"
        )
        self.loader = PDFLoader(max_bytes=max_bytes, timeout=timeout)
    
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义"""
        return [
            ToolParameter(
                name="path",
                type="string",
                description="PDF 文件路径或 URL",
                required=True
            ),
            ToolParameter(
                name="pages",
                type="string",
                description="页码范围，如 '1-5', '1,3,5-7'。不指定则提取所有页",
                required=False
            ),
            ToolParameter(
                name="max_pages",
                type="integer",
                description=f"最大提取页数，默认 {DEFAULT_MAX_PAGES}",
                required=False,
                default=DEFAULT_MAX_PAGES
            ),
            ToolParameter(
                name="metadata_only",
                type="boolean",
                description="是否只提取元数据，不提取文本内容",
                required=False,
                default=False
            ),
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行 PDF 读取
        
        Args:
            parameters: 工具参数
            
        Returns:
            JSON 格式的结果字符串
        """
        path = parameters.get("path", "").strip()
        if not path:
            return json.dumps({"error": "缺少必需参数: path"}, ensure_ascii=False)
        
        pages_str = parameters.get("pages", "")
        max_pages = parameters.get("max_pages", DEFAULT_MAX_PAGES)
        metadata_only = parameters.get("metadata_only", False)
        
        # 确保 max_pages 是整数
        try:
            max_pages = int(max_pages)
        except (TypeError, ValueError):
            max_pages = DEFAULT_MAX_PAGES
        
        try:
            # 检查 PDF 库是否可用
            if not PDFExtractor.is_available():
                return json.dumps({
                    "error": "没有可用的 PDF 库。请安装 pymupdf 或 pypdf",
                    "source": path
                }, ensure_ascii=False)
            
            # 加载 PDF
            pdf_data, source_type = self.loader.load(path)
            
            # 解析页码范围
            pages: Optional[List[int]] = None
            if pages_str:
                pages = parse_page_range(pages_str, max_pages)
            
            # 提取内容
            metadata, extracted_pages = PDFExtractor.extract(
                pdf_data,
                pages=pages,
                max_pages=max_pages
            )
            
            # 构建结果
            if metadata_only:
                result = PDFResult(
                    source=path,
                    source_type=source_type,
                    metadata=metadata,
                )
            else:
                # 合并所有页面文本
                full_text = "\n\n".join(
                    f"[Page {p.page_number}]\n{p.text}"
                    for p in extracted_pages
                    if p.text
                )
                
                result = PDFResult(
                    source=path,
                    source_type=source_type,
                    metadata=metadata,
                    pages=extracted_pages,
                    full_text=full_text,
                )
            
            return result.to_json()
            
        except FileNotFoundError as e:
            return json.dumps({
                "error": str(e),
                "source": path
            }, ensure_ascii=False)
        except ValueError as e:
            return json.dumps({
                "error": str(e),
                "source": path
            }, ensure_ascii=False)
        except Exception as e:
            logger.exception(f"PDF 处理失败: {path}")
            return json.dumps({
                "error": f"PDF 处理失败: {str(e)}",
                "source": path
            }, ensure_ascii=False)


# 导出工具实例（用于自动注册）
def create_tool() -> PDFTool:
    """创建 PDF 工具实例"""
    return PDFTool()
