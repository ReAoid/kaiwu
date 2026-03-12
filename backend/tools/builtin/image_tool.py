"""图像处理工具

支持图像读取、分析、元数据提取和 OCR 文字识别。
参考: openclaw/src/agents/tools/image-tool.ts

功能：
- 支持从文件路径或 URL 读取图像
- 提取图像元数据（尺寸、格式、模式等）
- 支持 Base64 编码输出（用于 LLM 消费）
- 支持多种图像格式（PNG, JPEG, GIF, WebP, BMP 等）
- 图像大小限制和验证
- OCR 文字识别（支持 Tesseract 和 PaddleOCR）
"""

import base64
import io
import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from core.tool import Tool, ToolParameter

logger = logging.getLogger(__name__)

# 支持的图像格式
SUPPORTED_FORMATS = {"png", "jpeg", "jpg", "gif", "webp", "bmp", "tiff", "ico"}

# MIME 类型映射
MIME_TYPE_MAP = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "ico": "image/x-icon",
}

# 默认配置
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_MAX_IMAGES = 20
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class ExifData:
    """EXIF 元数据
    
    Attributes:
        make: 相机制造商
        model: 相机型号
        datetime: 拍摄时间
        datetime_original: 原始拍摄时间
        software: 处理软件
        orientation: 图像方向（1-8）
        x_resolution: X 方向分辨率
        y_resolution: Y 方向分辨率
        resolution_unit: 分辨率单位（1=无单位, 2=英寸, 3=厘米）
        exposure_time: 曝光时间（秒）
        f_number: 光圈值
        iso_speed: ISO 感光度
        focal_length: 焦距（毫米）
        flash: 闪光灯状态
        gps_latitude: GPS 纬度
        gps_longitude: GPS 经度
        gps_altitude: GPS 海拔（米）
        image_description: 图像描述
        artist: 作者
        copyright: 版权信息
        raw_exif: 原始 EXIF 数据（所有标签）
    """
    make: Optional[str] = None
    model: Optional[str] = None
    datetime: Optional[str] = None
    datetime_original: Optional[str] = None
    software: Optional[str] = None
    orientation: Optional[int] = None
    x_resolution: Optional[float] = None
    y_resolution: Optional[float] = None
    resolution_unit: Optional[int] = None
    exposure_time: Optional[str] = None
    f_number: Optional[float] = None
    iso_speed: Optional[int] = None
    focal_length: Optional[float] = None
    flash: Optional[int] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    gps_altitude: Optional[float] = None
    image_description: Optional[str] = None
    artist: Optional[str] = None
    copyright: Optional[str] = None
    raw_exif: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（只包含非空值）"""
        result: Dict[str, Any] = {}
        
        if self.make:
            result["make"] = self.make
        if self.model:
            result["model"] = self.model
        if self.datetime:
            result["datetime"] = self.datetime
        if self.datetime_original:
            result["datetimeOriginal"] = self.datetime_original
        if self.software:
            result["software"] = self.software
        if self.orientation is not None:
            result["orientation"] = self.orientation
        if self.x_resolution is not None:
            result["xResolution"] = self.x_resolution
        if self.y_resolution is not None:
            result["yResolution"] = self.y_resolution
        if self.resolution_unit is not None:
            result["resolutionUnit"] = self.resolution_unit
        if self.exposure_time:
            result["exposureTime"] = self.exposure_time
        if self.f_number is not None:
            result["fNumber"] = self.f_number
        if self.iso_speed is not None:
            result["isoSpeed"] = self.iso_speed
        if self.focal_length is not None:
            result["focalLength"] = self.focal_length
        if self.flash is not None:
            result["flash"] = self.flash
        if self.gps_latitude is not None:
            result["gpsLatitude"] = self.gps_latitude
        if self.gps_longitude is not None:
            result["gpsLongitude"] = self.gps_longitude
        if self.gps_altitude is not None:
            result["gpsAltitude"] = self.gps_altitude
        if self.image_description:
            result["imageDescription"] = self.image_description
        if self.artist:
            result["artist"] = self.artist
        if self.copyright:
            result["copyright"] = self.copyright
        if self.raw_exif:
            result["rawExif"] = self.raw_exif
        
        return result
    
    def has_data(self) -> bool:
        """检查是否有任何 EXIF 数据"""
        return any([
            self.make, self.model, self.datetime, self.datetime_original,
            self.software, self.orientation is not None, self.x_resolution is not None,
            self.y_resolution is not None, self.exposure_time, self.f_number is not None,
            self.iso_speed is not None, self.focal_length is not None,
            self.flash is not None, self.gps_latitude is not None,
            self.gps_longitude is not None, self.gps_altitude is not None,
            self.image_description, self.artist, self.copyright
        ])


@dataclass
class ImageMetadata:
    """图像元数据
    
    Attributes:
        width: 图像宽度（像素）
        height: 图像高度（像素）
        format: 图像格式（如 PNG, JPEG）
        mode: 图像模式（如 RGB, RGBA, L）
        size_bytes: 文件大小（字节）
        has_alpha: 是否有透明通道
        is_animated: 是否为动画图像（GIF）
        frame_count: 帧数（动画图像）
        exif: EXIF 元数据（可选）
        color_profile: 颜色配置文件名称（可选）
        dpi: 图像 DPI（可选）
    """
    width: int
    height: int
    format: str
    mode: str
    size_bytes: int
    has_alpha: bool = False
    is_animated: bool = False
    frame_count: int = 1
    exif: Optional[ExifData] = None
    color_profile: Optional[str] = None
    dpi: Optional[Tuple[float, float]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "mode": self.mode,
            "sizeBytes": self.size_bytes,
            "hasAlpha": self.has_alpha,
            "isAnimated": self.is_animated,
            "frameCount": self.frame_count,
        }
        
        if self.exif and self.exif.has_data():
            result["exif"] = self.exif.to_dict()
        
        if self.color_profile:
            result["colorProfile"] = self.color_profile
        
        if self.dpi:
            result["dpi"] = {"x": self.dpi[0], "y": self.dpi[1]}
        
        return result


@dataclass
class OCRResult:
    """OCR 识别结果
    
    Attributes:
        text: 识别出的文本内容
        confidence: 置信度（0-100，可选）
        language: 识别使用的语言
        engine: 使用的 OCR 引擎
        error: 错误信息（可选）
    """
    text: str
    confidence: Optional[float] = None
    language: str = "eng"
    engine: str = "tesseract"
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result: Dict[str, Any] = {
            "text": self.text,
            "language": self.language,
            "engine": self.engine,
        }
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class ImageResult:
    """图像处理结果
    
    Attributes:
        source: 图像来源（文件路径或 URL）
        source_type: 来源类型（file, url, data_url）
        metadata: 图像元数据
        base64_data: Base64 编码的图像数据（可选）
        mime_type: MIME 类型
        ocr_result: OCR 识别结果（可选）
        error: 错误信息（可选）
    """
    source: str
    source_type: Literal["file", "url", "data_url"]
    metadata: Optional[ImageMetadata] = None
    base64_data: Optional[str] = None
    mime_type: Optional[str] = None
    ocr_result: Optional[OCRResult] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result: Dict[str, Any] = {
            "source": self.source,
            "sourceType": self.source_type,
        }
        if self.metadata:
            result["metadata"] = self.metadata.to_dict()
        if self.base64_data:
            result["base64Data"] = self.base64_data
        if self.mime_type:
            result["mimeType"] = self.mime_type
        if self.ocr_result:
            result["ocrResult"] = self.ocr_result.to_dict()
        if self.error:
            result["error"] = self.error
        return result
    
    def to_json(self, indent: Optional[int] = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class ImageLoader:
    """图像加载器
    
    支持从文件路径、URL 或 data URL 加载图像。
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
    
    def load(self, source: str) -> Tuple[bytes, str, Literal["file", "url", "data_url"]]:
        """加载图像数据
        
        Args:
            source: 图像来源（文件路径、URL 或 data URL）
            
        Returns:
            (image_bytes, source_type) 元组
            
        Raises:
            ValueError: 无效的来源
            FileNotFoundError: 文件不存在
            urllib.error.URLError: 网络错误
        """
        source = source.strip()
        
        # 处理 @ 前缀（某些 LLM 使用）
        if source.startswith("@"):
            source = source[1:].strip()
        
        # 判断来源类型
        if source.startswith("data:"):
            return self._load_data_url(source), "data_url"
        elif source.startswith(("http://", "https://")):
            return self._load_url(source), "url"
        elif source.startswith("file://"):
            file_path = source[7:]  # 移除 file:// 前缀
            return self._load_file(file_path), "file"
        else:
            # 假设是文件路径
            return self._load_file(source), "file"
    
    def _load_file(self, path: str) -> bytes:
        """从文件加载图像
        
        Args:
            path: 文件路径
            
        Returns:
            图像字节数据
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
        
        return file_path.read_bytes()
    
    def _load_url(self, url: str) -> bytes:
        """从 URL 加载图像
        
        Args:
            url: 图像 URL
            
        Returns:
            图像字节数据
        """
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "image/*",
            }
        )
        
        ssl_context = ssl.create_default_context()
        
        with urllib.request.urlopen(
            request, timeout=self.timeout, context=ssl_context
        ) as response:
            # 检查内容类型
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                raise ValueError(f"URL 不是图像: {content_type}")
            
            # 检查内容大小
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > self.max_bytes:
                raise ValueError(
                    f"图像过大: {content_length} 字节，最大允许 {self.max_bytes} 字节"
                )
            
            # 读取内容（限制大小）
            data = response.read(self.max_bytes + 1)
            if len(data) > self.max_bytes:
                raise ValueError(
                    f"图像过大: 超过 {self.max_bytes} 字节"
                )
            
            return data
    
    def _load_data_url(self, data_url: str) -> bytes:
        """从 data URL 加载图像
        
        Args:
            data_url: data URL 字符串
            
        Returns:
            图像字节数据
        """
        # 解析 data URL: data:[<mediatype>][;base64],<data>
        match = re.match(
            r'^data:([^;,]+)?(?:;([^,]+))?,(.+)$',
            data_url,
            re.DOTALL
        )
        
        if not match:
            raise ValueError("无效的 data URL 格式")
        
        media_type = match.group(1) or "application/octet-stream"
        encoding = match.group(2)
        data = match.group(3)
        
        if not media_type.startswith("image/"):
            raise ValueError(f"data URL 不是图像: {media_type}")
        
        if encoding == "base64":
            try:
                decoded = base64.b64decode(data)
            except Exception as e:
                raise ValueError(f"Base64 解码失败: {e}")
        else:
            # URL 编码
            decoded = urllib.parse.unquote(data).encode("latin-1")
        
        if len(decoded) > self.max_bytes:
            raise ValueError(
                f"图像过大: {len(decoded)} 字节，最大允许 {self.max_bytes} 字节"
            )
        
        return decoded


class ImageOCR:
    """图像 OCR 识别器
    
    支持使用 Tesseract OCR 或 PaddleOCR 进行文字识别。
    优先使用 Tesseract，如果不可用则尝试 PaddleOCR。
    """
    
    _tesseract_available: Optional[bool] = None
    _paddleocr_available: Optional[bool] = None
    
    # 支持的语言映射（Tesseract 语言代码）
    LANGUAGE_MAP = {
        "chinese": "chi_sim",
        "chinese_simplified": "chi_sim",
        "chinese_traditional": "chi_tra",
        "english": "eng",
        "japanese": "jpn",
        "korean": "kor",
        "french": "fra",
        "german": "deu",
        "spanish": "spa",
        "russian": "rus",
        "arabic": "ara",
        "auto": "eng+chi_sim",  # 自动检测时使用英文+简体中文
    }
    
    @classmethod
    def _check_tesseract(cls) -> bool:
        """检查 Tesseract 是否可用"""
        if cls._tesseract_available is None:
            try:
                import pytesseract
                # 尝试获取 Tesseract 版本以验证安装
                pytesseract.get_tesseract_version()
                cls._tesseract_available = True
                logger.debug("Tesseract OCR 已加载")
            except Exception as e:
                cls._tesseract_available = False
                logger.warning(f"Tesseract OCR 不可用: {e}")
        return cls._tesseract_available
    
    @classmethod
    def _check_paddleocr(cls) -> bool:
        """检查 PaddleOCR 是否可用"""
        if cls._paddleocr_available is None:
            try:
                from paddleocr import PaddleOCR
                cls._paddleocr_available = True
                logger.debug("PaddleOCR 已加载")
            except ImportError:
                cls._paddleocr_available = False
                logger.debug("PaddleOCR 不可用")
        return cls._paddleocr_available
    
    @classmethod
    def is_available(cls) -> bool:
        """检查是否有可用的 OCR 引擎"""
        return cls._check_tesseract() or cls._check_paddleocr()
    
    @classmethod
    def get_available_engine(cls) -> Optional[str]:
        """获取可用的 OCR 引擎名称"""
        if cls._check_tesseract():
            return "tesseract"
        elif cls._check_paddleocr():
            return "paddleocr"
        return None
    
    @classmethod
    def recognize(
        cls,
        image_data: bytes,
        language: str = "auto",
        engine: Optional[str] = None
    ) -> OCRResult:
        """识别图像中的文字
        
        Args:
            image_data: 图像字节数据
            language: 识别语言（auto, chinese, english, japanese 等）
            engine: 指定 OCR 引擎（tesseract, paddleocr），None 则自动选择
            
        Returns:
            OCR 识别结果
        """
        # 确定使用的引擎
        if engine:
            if engine == "tesseract" and not cls._check_tesseract():
                return OCRResult(
                    text="",
                    error="Tesseract OCR 不可用，请确保已安装 tesseract-ocr",
                    engine="tesseract"
                )
            elif engine == "paddleocr" and not cls._check_paddleocr():
                return OCRResult(
                    text="",
                    error="PaddleOCR 不可用，请安装 paddleocr 包",
                    engine="paddleocr"
                )
        else:
            engine = cls.get_available_engine()
            if not engine:
                return OCRResult(
                    text="",
                    error="没有可用的 OCR 引擎。请安装 tesseract-ocr 或 paddleocr",
                    engine="none"
                )
        
        # 执行 OCR
        if engine == "tesseract":
            return cls._recognize_with_tesseract(image_data, language)
        elif engine == "paddleocr":
            return cls._recognize_with_paddleocr(image_data, language)
        else:
            return OCRResult(
                text="",
                error=f"未知的 OCR 引擎: {engine}",
                engine=engine
            )
    
    @classmethod
    def _recognize_with_tesseract(cls, image_data: bytes, language: str) -> OCRResult:
        """使用 Tesseract 进行 OCR 识别
        
        Args:
            image_data: 图像字节数据
            language: 识别语言
            
        Returns:
            OCR 识别结果
        """
        try:
            import pytesseract
            from PIL import Image
            
            # 将字节数据转换为 PIL Image
            image = Image.open(io.BytesIO(image_data))
            
            # 转换语言代码
            lang_code = cls.LANGUAGE_MAP.get(language.lower(), language)
            
            # 执行 OCR
            # 使用 image_to_data 获取详细信息（包括置信度）
            try:
                data = pytesseract.image_to_data(
                    image,
                    lang=lang_code,
                    output_type=pytesseract.Output.DICT
                )
                
                # 提取文本和计算平均置信度
                texts = []
                confidences = []
                for i, text in enumerate(data['text']):
                    if text.strip():
                        texts.append(text)
                        conf = data['conf'][i]
                        if isinstance(conf, (int, float)) and conf >= 0:
                            confidences.append(conf)
                
                full_text = ' '.join(texts)
                avg_confidence = sum(confidences) / len(confidences) if confidences else None
                
            except Exception:
                # 回退到简单的 image_to_string
                full_text = pytesseract.image_to_string(image, lang=lang_code)
                avg_confidence = None
            
            return OCRResult(
                text=full_text.strip(),
                confidence=round(avg_confidence, 2) if avg_confidence else None,
                language=lang_code,
                engine="tesseract"
            )
            
        except Exception as e:
            logger.exception("Tesseract OCR 识别失败")
            return OCRResult(
                text="",
                error=f"Tesseract OCR 识别失败: {str(e)}",
                language=language,
                engine="tesseract"
            )
    
    @classmethod
    def _recognize_with_paddleocr(cls, image_data: bytes, language: str) -> OCRResult:
        """使用 PaddleOCR 进行 OCR 识别
        
        Args:
            image_data: 图像字节数据
            language: 识别语言
            
        Returns:
            OCR 识别结果
        """
        try:
            from paddleocr import PaddleOCR
            import numpy as np
            from PIL import Image
            
            # 将字节数据转换为 numpy 数组
            image = Image.open(io.BytesIO(image_data))
            image_array = np.array(image)
            
            # 确定 PaddleOCR 语言
            # PaddleOCR 使用不同的语言代码
            paddle_lang_map = {
                "chinese": "ch",
                "chinese_simplified": "ch",
                "chinese_traditional": "chinese_cht",
                "english": "en",
                "japanese": "japan",
                "korean": "korean",
                "french": "fr",
                "german": "german",
                "auto": "ch",  # 默认使用中文模型（支持中英文混合）
            }
            paddle_lang = paddle_lang_map.get(language.lower(), "ch")
            
            # 创建 PaddleOCR 实例
            ocr = PaddleOCR(
                use_angle_cls=True,
                lang=paddle_lang,
                show_log=False
            )
            
            # 执行 OCR
            result = ocr.ocr(image_array, cls=True)
            
            # 提取文本和置信度
            texts = []
            confidences = []
            
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2:
                        text_info = line[1]
                        if isinstance(text_info, tuple) and len(text_info) >= 2:
                            texts.append(text_info[0])
                            confidences.append(text_info[1])
            
            full_text = '\n'.join(texts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else None
            
            return OCRResult(
                text=full_text.strip(),
                confidence=round(avg_confidence * 100, 2) if avg_confidence else None,
                language=paddle_lang,
                engine="paddleocr"
            )
            
        except Exception as e:
            logger.exception("PaddleOCR 识别失败")
            return OCRResult(
                text="",
                error=f"PaddleOCR 识别失败: {str(e)}",
                language=language,
                engine="paddleocr"
            )


class ImageAnalyzer:
    """图像分析器
    
    提取图像元数据，支持使用 Pillow 库或回退到基本分析。
    """
    
    _pillow_available: Optional[bool] = None
    
    @classmethod
    def _check_pillow(cls) -> bool:
        """检查 Pillow 是否可用"""
        if cls._pillow_available is None:
            try:
                from PIL import Image
                cls._pillow_available = True
                logger.debug("Pillow 库已加载")
            except ImportError:
                cls._pillow_available = False
                logger.warning("Pillow 库不可用，将使用基本图像分析")
        return cls._pillow_available
    
    @classmethod
    def analyze(cls, image_data: bytes) -> ImageMetadata:
        """分析图像并提取元数据
        
        Args:
            image_data: 图像字节数据
            
        Returns:
            图像元数据
        """
        if cls._check_pillow():
            return cls._analyze_with_pillow(image_data)
        else:
            return cls._analyze_basic(image_data)
    
    @classmethod
    def _analyze_with_pillow(cls, image_data: bytes) -> ImageMetadata:
        """使用 Pillow 分析图像
        
        Args:
            image_data: 图像字节数据
            
        Returns:
            图像元数据
        """
        from PIL import Image
        
        with Image.open(io.BytesIO(image_data)) as img:
            # 基本信息
            width, height = img.size
            format_name = img.format or "UNKNOWN"
            mode = img.mode
            
            # 检查透明通道
            has_alpha = mode in ("RGBA", "LA", "PA") or (
                mode == "P" and "transparency" in img.info
            )
            
            # 检查动画
            is_animated = False
            frame_count = 1
            if format_name.upper() == "GIF":
                try:
                    frame_count = img.n_frames
                    is_animated = frame_count > 1
                except Exception:
                    pass
            
            # 提取 EXIF 数据
            exif_data = cls._extract_exif(img)
            
            # 提取颜色配置文件
            color_profile = None
            if "icc_profile" in img.info:
                try:
                    # 尝试获取配置文件名称
                    from PIL import ImageCms
                    icc_profile = img.info.get("icc_profile")
                    if icc_profile:
                        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
                        color_profile = ImageCms.getProfileDescription(profile)
                except Exception:
                    color_profile = "Unknown ICC Profile"
            
            # 提取 DPI
            dpi = None
            if "dpi" in img.info:
                dpi_info = img.info["dpi"]
                if isinstance(dpi_info, tuple) and len(dpi_info) >= 2:
                    dpi = (float(dpi_info[0]), float(dpi_info[1]))
            
            return ImageMetadata(
                width=width,
                height=height,
                format=format_name.upper(),
                mode=mode,
                size_bytes=len(image_data),
                has_alpha=has_alpha,
                is_animated=is_animated,
                frame_count=frame_count,
                exif=exif_data,
                color_profile=color_profile,
                dpi=dpi,
            )
    
    @classmethod
    def _extract_exif(cls, img) -> Optional[ExifData]:
        """从 PIL Image 提取 EXIF 数据
        
        Args:
            img: PIL Image 对象
            
        Returns:
            ExifData 对象，如果没有 EXIF 数据则返回 None
        """
        try:
            from PIL import ExifTags
            
            # 获取 EXIF 数据
            exif_dict = img.getexif()
            if not exif_dict:
                return None
            
            # EXIF 标签 ID 到名称的映射
            exif_tags = {v: k for k, v in ExifTags.TAGS.items()}
            
            # 提取常用 EXIF 字段
            raw_exif: Dict[str, Any] = {}
            
            for tag_id, value in exif_dict.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                # 转换值为可序列化格式
                try:
                    if isinstance(value, bytes):
                        # 尝试解码为字符串
                        try:
                            value = value.decode('utf-8', errors='ignore').strip('\x00')
                        except Exception:
                            value = value.hex()
                    elif hasattr(value, 'numerator') and hasattr(value, 'denominator'):
                        # IFDRational 类型
                        if value.denominator != 0:
                            value = float(value.numerator) / float(value.denominator)
                        else:
                            value = 0.0
                    raw_exif[tag_name] = value
                except Exception:
                    pass
            
            # 提取 GPS 信息（如果存在）
            gps_info = cls._extract_gps_info(exif_dict)
            
            # 构建 ExifData 对象
            exif_data = ExifData(
                make=cls._get_exif_value(raw_exif, "Make"),
                model=cls._get_exif_value(raw_exif, "Model"),
                datetime=cls._get_exif_value(raw_exif, "DateTime"),
                datetime_original=cls._get_exif_value(raw_exif, "DateTimeOriginal"),
                software=cls._get_exif_value(raw_exif, "Software"),
                orientation=cls._get_exif_int(raw_exif, "Orientation"),
                x_resolution=cls._get_exif_float(raw_exif, "XResolution"),
                y_resolution=cls._get_exif_float(raw_exif, "YResolution"),
                resolution_unit=cls._get_exif_int(raw_exif, "ResolutionUnit"),
                exposure_time=cls._format_exposure_time(raw_exif.get("ExposureTime")),
                f_number=cls._get_exif_float(raw_exif, "FNumber"),
                iso_speed=cls._get_exif_int(raw_exif, "ISOSpeedRatings") or cls._get_exif_int(raw_exif, "PhotographicSensitivity"),
                focal_length=cls._get_exif_float(raw_exif, "FocalLength"),
                flash=cls._get_exif_int(raw_exif, "Flash"),
                gps_latitude=gps_info.get("latitude") if gps_info else None,
                gps_longitude=gps_info.get("longitude") if gps_info else None,
                gps_altitude=gps_info.get("altitude") if gps_info else None,
                image_description=cls._get_exif_value(raw_exif, "ImageDescription"),
                artist=cls._get_exif_value(raw_exif, "Artist"),
                copyright=cls._get_exif_value(raw_exif, "Copyright"),
                raw_exif=raw_exif if raw_exif else None,
            )
            
            return exif_data if exif_data.has_data() else None
            
        except Exception as e:
            logger.debug(f"提取 EXIF 数据失败: {e}")
            return None
    
    @classmethod
    def _extract_gps_info(cls, exif_dict) -> Optional[Dict[str, float]]:
        """从 EXIF 数据提取 GPS 信息
        
        Args:
            exif_dict: EXIF 字典
            
        Returns:
            包含 latitude, longitude, altitude 的字典
        """
        try:
            from PIL import ExifTags
            
            # 获取 GPS IFD
            gps_ifd = exif_dict.get_ifd(ExifTags.IFD.GPSInfo)
            if not gps_ifd:
                return None
            
            result: Dict[str, float] = {}
            
            # GPS 标签 ID
            GPS_TAGS = {v: k for k, v in ExifTags.GPSTAGS.items()}
            
            # 提取纬度
            lat = gps_ifd.get(GPS_TAGS.get("GPSLatitude"))
            lat_ref = gps_ifd.get(GPS_TAGS.get("GPSLatitudeRef"))
            if lat and lat_ref:
                latitude = cls._convert_gps_coords(lat)
                if lat_ref in ("S", "s"):
                    latitude = -latitude
                result["latitude"] = latitude
            
            # 提取经度
            lon = gps_ifd.get(GPS_TAGS.get("GPSLongitude"))
            lon_ref = gps_ifd.get(GPS_TAGS.get("GPSLongitudeRef"))
            if lon and lon_ref:
                longitude = cls._convert_gps_coords(lon)
                if lon_ref in ("W", "w"):
                    longitude = -longitude
                result["longitude"] = longitude
            
            # 提取海拔
            alt = gps_ifd.get(GPS_TAGS.get("GPSAltitude"))
            alt_ref = gps_ifd.get(GPS_TAGS.get("GPSAltitudeRef"))
            if alt is not None:
                if hasattr(alt, 'numerator') and hasattr(alt, 'denominator'):
                    altitude = float(alt.numerator) / float(alt.denominator) if alt.denominator else 0.0
                else:
                    altitude = float(alt)
                # alt_ref: 0 = 海平面以上, 1 = 海平面以下
                if alt_ref == 1:
                    altitude = -altitude
                result["altitude"] = altitude
            
            return result if result else None
            
        except Exception as e:
            logger.debug(f"提取 GPS 信息失败: {e}")
            return None
    
    @staticmethod
    def _convert_gps_coords(coords) -> float:
        """将 GPS 坐标从度分秒格式转换为十进制度
        
        Args:
            coords: GPS 坐标元组 (度, 分, 秒)
            
        Returns:
            十进制度数
        """
        if not coords or len(coords) < 3:
            return 0.0
        
        def to_float(val):
            if hasattr(val, 'numerator') and hasattr(val, 'denominator'):
                return float(val.numerator) / float(val.denominator) if val.denominator else 0.0
            return float(val)
        
        degrees = to_float(coords[0])
        minutes = to_float(coords[1])
        seconds = to_float(coords[2])
        
        return degrees + minutes / 60.0 + seconds / 3600.0
    
    @staticmethod
    def _get_exif_value(exif: Dict[str, Any], key: str) -> Optional[str]:
        """获取 EXIF 字符串值"""
        value = exif.get(key)
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() if value.strip() else None
        return str(value).strip() if str(value).strip() else None
    
    @staticmethod
    def _get_exif_int(exif: Dict[str, Any], key: str) -> Optional[int]:
        """获取 EXIF 整数值"""
        value = exif.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _get_exif_float(exif: Dict[str, Any], key: str) -> Optional[float]:
        """获取 EXIF 浮点值"""
        value = exif.get(key)
        if value is None:
            return None
        try:
            if hasattr(value, 'numerator') and hasattr(value, 'denominator'):
                return float(value.numerator) / float(value.denominator) if value.denominator else None
            return float(value)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _format_exposure_time(value) -> Optional[str]:
        """格式化曝光时间为可读字符串
        
        Args:
            value: 曝光时间值
            
        Returns:
            格式化的曝光时间字符串（如 "1/125"）
        """
        if value is None:
            return None
        
        try:
            if hasattr(value, 'numerator') and hasattr(value, 'denominator'):
                num = value.numerator
                den = value.denominator
                if den == 0:
                    return None
                if num == 1:
                    return f"1/{den}"
                elif den == 1:
                    return f"{num}"
                else:
                    # 简化分数
                    ratio = num / den
                    if ratio >= 1:
                        return f"{ratio:.1f}"
                    else:
                        return f"1/{int(1/ratio)}"
            else:
                val = float(value)
                if val >= 1:
                    return f"{val:.1f}"
                else:
                    return f"1/{int(1/val)}"
        except Exception:
            return None
    
    @classmethod
    def _analyze_basic(cls, image_data: bytes) -> ImageMetadata:
        """基本图像分析（不依赖 Pillow）
        
        通过读取图像文件头来获取基本信息。
        
        Args:
            image_data: 图像字节数据
            
        Returns:
            图像元数据
        """
        format_name = "UNKNOWN"
        width = 0
        height = 0
        mode = "UNKNOWN"
        has_alpha = False
        
        # PNG 格式检测
        if image_data[:8] == b'\x89PNG\r\n\x1a\n':
            format_name = "PNG"
            if len(image_data) >= 24:
                width = int.from_bytes(image_data[16:20], 'big')
                height = int.from_bytes(image_data[20:24], 'big')
                # 检查颜色类型
                if len(image_data) >= 26:
                    color_type = image_data[25]
                    if color_type == 0:
                        mode = "L"
                    elif color_type == 2:
                        mode = "RGB"
                    elif color_type == 3:
                        mode = "P"
                    elif color_type == 4:
                        mode = "LA"
                        has_alpha = True
                    elif color_type == 6:
                        mode = "RGBA"
                        has_alpha = True
        
        # JPEG 格式检测
        elif image_data[:2] == b'\xff\xd8':
            format_name = "JPEG"
            mode = "RGB"
            # 查找 SOF 标记获取尺寸
            i = 2
            while i < len(image_data) - 9:
                if image_data[i] == 0xff:
                    marker = image_data[i + 1]
                    # SOF0, SOF1, SOF2 标记
                    if marker in (0xc0, 0xc1, 0xc2):
                        height = int.from_bytes(image_data[i + 5:i + 7], 'big')
                        width = int.from_bytes(image_data[i + 7:i + 9], 'big')
                        break
                    elif marker == 0xd9:  # EOI
                        break
                    elif marker not in (0x00, 0xd0, 0xd1, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7):
                        # 跳过段
                        if i + 3 < len(image_data):
                            length = int.from_bytes(image_data[i + 2:i + 4], 'big')
                            i += length + 2
                            continue
                i += 1
        
        # GIF 格式检测
        elif image_data[:6] in (b'GIF87a', b'GIF89a'):
            format_name = "GIF"
            mode = "P"
            if len(image_data) >= 10:
                width = int.from_bytes(image_data[6:8], 'little')
                height = int.from_bytes(image_data[8:10], 'little')
        
        # WebP 格式检测
        elif image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
            format_name = "WEBP"
            mode = "RGB"
            # VP8 chunk
            if len(image_data) >= 30 and image_data[12:16] == b'VP8 ':
                # 简化的 VP8 尺寸解析
                if image_data[23] == 0x9d and image_data[24] == 0x01 and image_data[25] == 0x2a:
                    width = int.from_bytes(image_data[26:28], 'little') & 0x3fff
                    height = int.from_bytes(image_data[28:30], 'little') & 0x3fff
            # VP8L chunk (lossless)
            elif len(image_data) >= 25 and image_data[12:16] == b'VP8L':
                if image_data[21] == 0x2f:
                    bits = int.from_bytes(image_data[22:26], 'little')
                    width = (bits & 0x3fff) + 1
                    height = ((bits >> 14) & 0x3fff) + 1
                    has_alpha = bool((bits >> 28) & 1)
                    if has_alpha:
                        mode = "RGBA"
        
        # BMP 格式检测
        elif image_data[:2] == b'BM':
            format_name = "BMP"
            mode = "RGB"
            if len(image_data) >= 26:
                width = int.from_bytes(image_data[18:22], 'little')
                height = abs(int.from_bytes(image_data[22:26], 'little', signed=True))
        
        return ImageMetadata(
            width=width,
            height=height,
            format=format_name,
            mode=mode,
            size_bytes=len(image_data),
            has_alpha=has_alpha,
            is_animated=False,
            frame_count=1,
        )
    
    @classmethod
    def get_mime_type(cls, image_data: bytes, format_hint: Optional[str] = None) -> str:
        """获取图像的 MIME 类型
        
        Args:
            image_data: 图像字节数据
            format_hint: 格式提示（如文件扩展名）
            
        Returns:
            MIME 类型字符串
        """
        # 通过文件头检测
        if image_data[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        elif image_data[:2] == b'\xff\xd8':
            return "image/jpeg"
        elif image_data[:6] in (b'GIF87a', b'GIF89a'):
            return "image/gif"
        elif image_data[:4] == b'RIFF' and len(image_data) >= 12 and image_data[8:12] == b'WEBP':
            return "image/webp"
        elif image_data[:2] == b'BM':
            return "image/bmp"
        elif image_data[:4] in (b'II*\x00', b'MM\x00*'):
            return "image/tiff"
        
        # 使用格式提示
        if format_hint:
            ext = format_hint.lower().lstrip(".")
            if ext in MIME_TYPE_MAP:
                return MIME_TYPE_MAP[ext]
        
        return "application/octet-stream"


class ImageTool(Tool):
    """图像处理工具
    
    读取和分析图像，提取元数据，支持 Base64 编码输出。
    
    功能：
    - 从文件路径、URL 或 data URL 读取图像
    - 提取图像元数据（尺寸、格式、模式等）
    - 支持 Base64 编码输出（用于 LLM 消费）
    - 支持多种图像格式
    
    参考: openclaw/src/agents/tools/image-tool.ts
    """
    
    def __init__(
        self,
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT
    ):
        """初始化工具
        
        Args:
            max_bytes: 最大文件大小（字节）
            timeout: 网络请求超时（秒）
            user_agent: User-Agent 字符串
        """
        super().__init__(
            name="image",
            description=(
                "读取和分析图像文件。支持从文件路径、URL 或 data URL 加载图像，"
                "提取元数据（尺寸、格式等），并可选择输出 Base64 编码数据。"
            )
        )
        
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.user_agent = user_agent
        
        self._loader = ImageLoader(
            max_bytes=max_bytes,
            timeout=timeout,
            user_agent=user_agent
        )
    
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义"""
        return [
            ToolParameter(
                name="image",
                type="string",
                description="单个图像路径或 URL",
                required=False
            ),
            ToolParameter(
                name="images",
                type="array",
                description=f"多个图像路径或 URL（最多 {DEFAULT_MAX_IMAGES} 个）",
                required=False
            ),
            ToolParameter(
                name="include_base64",
                type="boolean",
                description="是否在结果中包含 Base64 编码的图像数据，默认 false",
                required=False,
                default=False
            ),
            ToolParameter(
                name="ocr",
                type="boolean",
                description="是否执行 OCR 文字识别，默认 false",
                required=False,
                default=False
            ),
            ToolParameter(
                name="ocr_language",
                type="string",
                description="OCR 识别语言（auto, chinese, english, japanese 等），默认 auto",
                required=False,
                default="auto"
            ),
            ToolParameter(
                name="ocr_engine",
                type="string",
                description="OCR 引擎（tesseract, paddleocr），默认自动选择",
                required=False,
                default=None
            ),
            ToolParameter(
                name="max_bytes_mb",
                type="number",
                description=f"最大文件大小（MB），默认 {DEFAULT_MAX_BYTES // (1024 * 1024)}",
                required=False,
                default=DEFAULT_MAX_BYTES // (1024 * 1024)
            ),
            ToolParameter(
                name="max_images",
                type="integer",
                description=f"最大图像数量，默认 {DEFAULT_MAX_IMAGES}",
                required=False,
                default=DEFAULT_MAX_IMAGES
            )
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行图像处理
        
        Args:
            parameters: 工具参数
            
        Returns:
            JSON 格式的处理结果
        """
        # 收集图像来源
        image_sources: List[str] = []
        
        # 单个图像
        single_image = parameters.get("image")
        if isinstance(single_image, str) and single_image.strip():
            image_sources.append(single_image.strip())
        
        # 多个图像
        multiple_images = parameters.get("images")
        if isinstance(multiple_images, list):
            for img in multiple_images:
                if isinstance(img, str) and img.strip():
                    image_sources.append(img.strip())
        
        # 去重（保持顺序）
        seen = set()
        unique_sources: List[str] = []
        for source in image_sources:
            # 规范化来源用于去重
            normalized = source.lstrip("@").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_sources.append(source)
        
        if not unique_sources:
            return json.dumps({
                "error": "需要提供 image 或 images 参数",
                "results": []
            }, ensure_ascii=False, indent=2)
        
        # 检查图像数量限制
        max_images = parameters.get("max_images", DEFAULT_MAX_IMAGES)
        if not isinstance(max_images, int) or max_images <= 0:
            max_images = DEFAULT_MAX_IMAGES
        
        if len(unique_sources) > max_images:
            return json.dumps({
                "error": f"图像数量过多: {len(unique_sources)} 个，最多允许 {max_images} 个",
                "results": []
            }, ensure_ascii=False, indent=2)
        
        # 解析其他参数
        include_base64 = parameters.get("include_base64", False)
        if not isinstance(include_base64, bool):
            include_base64 = str(include_base64).lower() in ("true", "1", "yes")
        
        # OCR 参数
        do_ocr = parameters.get("ocr", False)
        if not isinstance(do_ocr, bool):
            do_ocr = str(do_ocr).lower() in ("true", "1", "yes")
        
        ocr_language = parameters.get("ocr_language", "auto")
        if not isinstance(ocr_language, str):
            ocr_language = "auto"
        
        ocr_engine = parameters.get("ocr_engine")
        if ocr_engine and not isinstance(ocr_engine, str):
            ocr_engine = None
        
        max_bytes_mb = parameters.get("max_bytes_mb")
        if isinstance(max_bytes_mb, (int, float)) and max_bytes_mb > 0:
            effective_max_bytes = int(max_bytes_mb * 1024 * 1024)
        else:
            effective_max_bytes = self.max_bytes
        
        # 更新加载器配置
        self._loader.max_bytes = effective_max_bytes
        
        # 处理每个图像
        results: List[Dict[str, Any]] = []
        
        for source in unique_sources:
            result = self._process_image(
                source,
                include_base64,
                do_ocr=do_ocr,
                ocr_language=ocr_language,
                ocr_engine=ocr_engine
            )
            results.append(result.to_dict())
        
        # 构建响应
        response: Dict[str, Any] = {
            "count": len(results),
            "results": results
        }
        
        # 检查是否有错误
        errors = [r for r in results if r.get("error")]
        if errors:
            response["hasErrors"] = True
            response["errorCount"] = len(errors)
        
        return json.dumps(response, ensure_ascii=False, indent=2)
    
    def _process_image(
        self,
        source: str,
        include_base64: bool,
        do_ocr: bool = False,
        ocr_language: str = "auto",
        ocr_engine: Optional[str] = None
    ) -> ImageResult:
        """处理单个图像
        
        Args:
            source: 图像来源
            include_base64: 是否包含 Base64 数据
            do_ocr: 是否执行 OCR
            ocr_language: OCR 识别语言
            ocr_engine: OCR 引擎
            
        Returns:
            图像处理结果
        """
        try:
            # 加载图像数据
            image_data, source_type = self._loader.load(source)
            
            # 分析图像
            metadata = ImageAnalyzer.analyze(image_data)
            
            # 获取 MIME 类型
            mime_type = ImageAnalyzer.get_mime_type(image_data)
            
            # 构建结果
            result = ImageResult(
                source=source,
                source_type=source_type,
                metadata=metadata,
                mime_type=mime_type
            )
            
            # 可选：包含 Base64 数据
            if include_base64:
                result.base64_data = base64.b64encode(image_data).decode("ascii")
            
            # 可选：执行 OCR
            if do_ocr:
                ocr_result = ImageOCR.recognize(
                    image_data,
                    language=ocr_language,
                    engine=ocr_engine
                )
                result.ocr_result = ocr_result
            
            return result
            
        except FileNotFoundError as e:
            return ImageResult(
                source=source,
                source_type="file",
                error=str(e)
            )
        except urllib.error.URLError as e:
            return ImageResult(
                source=source,
                source_type="url",
                error=f"网络错误: {e.reason}"
            )
        except urllib.error.HTTPError as e:
            return ImageResult(
                source=source,
                source_type="url",
                error=f"HTTP 错误 {e.code}: {e.reason}"
            )
        except ValueError as e:
            # 判断来源类型
            source_type: Literal["file", "url", "data_url"] = "file"
            if source.startswith("data:"):
                source_type = "data_url"
            elif source.startswith(("http://", "https://")):
                source_type = "url"
            
            return ImageResult(
                source=source,
                source_type=source_type,
                error=str(e)
            )
        except Exception as e:
            logger.exception(f"处理图像失败: {source}")
            
            source_type = "file"
            if source.startswith("data:"):
                source_type = "data_url"
            elif source.startswith(("http://", "https://")):
                source_type = "url"
            
            return ImageResult(
                source=source,
                source_type=source_type,
                error=f"处理失败: {str(e)}"
            )
