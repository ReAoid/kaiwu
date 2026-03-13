"""工具依赖检查模块

提供工具依赖检查功能，支持检查：
- 二进制文件依赖（如 tesseract, gh, ffmpeg）
- Python 包依赖（如 pillow, pymupdf）
- 可选依赖和必需依赖

参考: openclaw/src/agents/skills-install.ts
"""

import importlib
import importlib.metadata
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


class DependencyType(Enum):
    """依赖类型"""
    BINARY = "binary"      # 二进制文件/命令行工具
    PYTHON = "python"      # Python 包
    CUSTOM = "custom"      # 自定义检查函数


class DependencyStatus(Enum):
    """依赖状态"""
    AVAILABLE = "available"      # 可用
    MISSING = "missing"          # 缺失
    VERSION_MISMATCH = "version_mismatch"  # 版本不匹配
    CHECK_FAILED = "check_failed"  # 检查失败


@dataclass
class Dependency:
    """依赖定义
    
    Attributes:
        name: 依赖名称（二进制命令名或 Python 包名）
        type: 依赖类型
        required: 是否必需（False 表示可选依赖）
        min_version: 最低版本要求（可选）
        description: 依赖描述
        install_hint: 安装提示
        check_func: 自定义检查函数（仅用于 CUSTOM 类型）
        alternatives: 替代依赖列表（任一满足即可）
    """
    name: str
    type: DependencyType = DependencyType.PYTHON
    required: bool = True
    min_version: Optional[str] = None
    description: str = ""
    install_hint: str = ""
    check_func: Optional[Callable[[], bool]] = None
    alternatives: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """初始化后处理"""
        if not self.description:
            self.description = f"{self.type.value} 依赖: {self.name}"
        if not self.install_hint:
            self.install_hint = self._generate_install_hint()
    
    def _generate_install_hint(self) -> str:
        """生成安装提示"""
        if self.type == DependencyType.PYTHON:
            return f"pip install {self.name}"
        elif self.type == DependencyType.BINARY:
            return f"请安装 {self.name} 命令行工具"
        return ""


@dataclass
class DependencyCheckResult:
    """依赖检查结果
    
    Attributes:
        dependency: 依赖定义
        status: 检查状态
        installed_version: 已安装版本（如果可获取）
        error_message: 错误信息（如果检查失败）
        alternative_used: 使用的替代依赖（如果有）
    """
    dependency: Dependency
    status: DependencyStatus
    installed_version: Optional[str] = None
    error_message: Optional[str] = None
    alternative_used: Optional[str] = None
    
    @property
    def is_satisfied(self) -> bool:
        """依赖是否满足"""
        return self.status == DependencyStatus.AVAILABLE
    
    @property
    def is_required_missing(self) -> bool:
        """是否为缺失的必需依赖"""
        return self.dependency.required and not self.is_satisfied
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "name": self.dependency.name,
            "type": self.dependency.type.value,
            "required": self.dependency.required,
            "status": self.status.value,
            "satisfied": self.is_satisfied,
        }
        if self.installed_version:
            result["installedVersion"] = self.installed_version
        if self.dependency.min_version:
            result["minVersion"] = self.dependency.min_version
        if self.error_message:
            result["error"] = self.error_message
        if self.alternative_used:
            result["alternativeUsed"] = self.alternative_used
        if not self.is_satisfied and self.dependency.install_hint:
            result["installHint"] = self.dependency.install_hint
        return result


@dataclass
class ToolDependencyReport:
    """工具依赖检查报告
    
    Attributes:
        tool_name: 工具名称
        results: 各依赖的检查结果
        all_satisfied: 所有依赖是否满足
        required_satisfied: 所有必需依赖是否满足
        missing_required: 缺失的必需依赖列表
        missing_optional: 缺失的可选依赖列表
    """
    tool_name: str
    results: List[DependencyCheckResult] = field(default_factory=list)
    
    @property
    def all_satisfied(self) -> bool:
        """所有依赖是否满足"""
        return all(r.is_satisfied for r in self.results)
    
    @property
    def required_satisfied(self) -> bool:
        """所有必需依赖是否满足"""
        return all(r.is_satisfied for r in self.results if r.dependency.required)
    
    @property
    def missing_required(self) -> List[DependencyCheckResult]:
        """缺失的必需依赖"""
        return [r for r in self.results if r.is_required_missing]
    
    @property
    def missing_optional(self) -> List[DependencyCheckResult]:
        """缺失的可选依赖"""
        return [r for r in self.results 
                if not r.dependency.required and not r.is_satisfied]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "toolName": self.tool_name,
            "allSatisfied": self.all_satisfied,
            "requiredSatisfied": self.required_satisfied,
            "dependencies": [r.to_dict() for r in self.results],
            "missingRequired": [r.dependency.name for r in self.missing_required],
            "missingOptional": [r.dependency.name for r in self.missing_optional],
        }
    
    def get_summary(self) -> str:
        """获取摘要信息"""
        if self.all_satisfied:
            return f"工具 {self.tool_name}: 所有依赖满足"
        
        lines = [f"工具 {self.tool_name} 依赖检查:"]
        
        if self.missing_required:
            lines.append("  缺失的必需依赖:")
            for r in self.missing_required:
                hint = f" ({r.dependency.install_hint})" if r.dependency.install_hint else ""
                lines.append(f"    - {r.dependency.name}{hint}")
        
        if self.missing_optional:
            lines.append("  缺失的可选依赖:")
            for r in self.missing_optional:
                lines.append(f"    - {r.dependency.name}")
        
        return "\n".join(lines)


class DependencyChecker:
    """依赖检查器
    
    提供检查二进制文件和 Python 包依赖的功能。
    支持版本检查、替代依赖和自定义检查函数。
    """
    
    # 缓存已检查的依赖结果
    _cache: Dict[str, DependencyCheckResult] = {}
    _cache_enabled: bool = True
    
    @classmethod
    def clear_cache(cls) -> None:
        """清除缓存"""
        cls._cache.clear()
    
    @classmethod
    def disable_cache(cls) -> None:
        """禁用缓存"""
        cls._cache_enabled = False
        cls._cache.clear()
    
    @classmethod
    def enable_cache(cls) -> None:
        """启用缓存"""
        cls._cache_enabled = True
    
    @classmethod
    def check(cls, dependency: Dependency) -> DependencyCheckResult:
        """检查单个依赖
        
        Args:
            dependency: 依赖定义
            
        Returns:
            检查结果
        """
        # 检查缓存
        cache_key = f"{dependency.type.value}:{dependency.name}"
        if cls._cache_enabled and cache_key in cls._cache:
            return cls._cache[cache_key]
        
        # 执行检查
        if dependency.type == DependencyType.BINARY:
            result = cls._check_binary(dependency)
        elif dependency.type == DependencyType.PYTHON:
            result = cls._check_python(dependency)
        elif dependency.type == DependencyType.CUSTOM:
            result = cls._check_custom(dependency)
        else:
            result = DependencyCheckResult(
                dependency=dependency,
                status=DependencyStatus.CHECK_FAILED,
                error_message=f"未知的依赖类型: {dependency.type}"
            )
        
        # 如果主依赖不满足，检查替代依赖
        if not result.is_satisfied and dependency.alternatives:
            for alt_name in dependency.alternatives:
                alt_dep = Dependency(
                    name=alt_name,
                    type=dependency.type,
                    required=dependency.required,
                    min_version=None,  # 替代依赖不检查版本
                )
                alt_result = cls.check(alt_dep)
                if alt_result.is_satisfied:
                    result = DependencyCheckResult(
                        dependency=dependency,
                        status=DependencyStatus.AVAILABLE,
                        installed_version=alt_result.installed_version,
                        alternative_used=alt_name
                    )
                    break
        
        # 缓存结果
        if cls._cache_enabled:
            cls._cache[cache_key] = result
        
        return result
    
    @classmethod
    def check_all(cls, dependencies: List[Dependency]) -> List[DependencyCheckResult]:
        """检查多个依赖
        
        Args:
            dependencies: 依赖列表
            
        Returns:
            检查结果列表
        """
        return [cls.check(dep) for dep in dependencies]
    
    @classmethod
    def check_tool(cls, tool_name: str, dependencies: List[Dependency]) -> ToolDependencyReport:
        """检查工具的所有依赖
        
        Args:
            tool_name: 工具名称
            dependencies: 依赖列表
            
        Returns:
            工具依赖检查报告
        """
        results = cls.check_all(dependencies)
        return ToolDependencyReport(tool_name=tool_name, results=results)

    
    @classmethod
    def _check_binary(cls, dependency: Dependency) -> DependencyCheckResult:
        """检查二进制文件依赖
        
        Args:
            dependency: 依赖定义
            
        Returns:
            检查结果
        """
        try:
            # 使用 shutil.which 检查命令是否存在
            path = shutil.which(dependency.name)
            
            if path is None:
                return DependencyCheckResult(
                    dependency=dependency,
                    status=DependencyStatus.MISSING,
                    error_message=f"命令 '{dependency.name}' 未找到"
                )
            
            # 尝试获取版本
            version = cls._get_binary_version(dependency.name)
            
            # 检查版本要求
            if dependency.min_version and version:
                if not cls._compare_versions(version, dependency.min_version):
                    return DependencyCheckResult(
                        dependency=dependency,
                        status=DependencyStatus.VERSION_MISMATCH,
                        installed_version=version,
                        error_message=f"版本 {version} 低于要求的 {dependency.min_version}"
                    )
            
            return DependencyCheckResult(
                dependency=dependency,
                status=DependencyStatus.AVAILABLE,
                installed_version=version
            )
            
        except Exception as e:
            logger.debug(f"检查二进制依赖 {dependency.name} 失败: {e}")
            return DependencyCheckResult(
                dependency=dependency,
                status=DependencyStatus.CHECK_FAILED,
                error_message=str(e)
            )
    
    @classmethod
    def _check_python(cls, dependency: Dependency) -> DependencyCheckResult:
        """检查 Python 包依赖
        
        Args:
            dependency: 依赖定义
            
        Returns:
            检查结果
        """
        try:
            # 尝试导入模块
            # 处理包名和模块名不一致的情况
            module_name = cls._get_module_name(dependency.name)
            
            try:
                importlib.import_module(module_name)
            except ImportError:
                return DependencyCheckResult(
                    dependency=dependency,
                    status=DependencyStatus.MISSING,
                    error_message=f"Python 包 '{dependency.name}' 未安装"
                )
            
            # 获取已安装版本
            version = cls._get_python_package_version(dependency.name)
            
            # 检查版本要求
            if dependency.min_version and version:
                if not cls._compare_versions(version, dependency.min_version):
                    return DependencyCheckResult(
                        dependency=dependency,
                        status=DependencyStatus.VERSION_MISMATCH,
                        installed_version=version,
                        error_message=f"版本 {version} 低于要求的 {dependency.min_version}"
                    )
            
            return DependencyCheckResult(
                dependency=dependency,
                status=DependencyStatus.AVAILABLE,
                installed_version=version
            )
            
        except Exception as e:
            logger.debug(f"检查 Python 依赖 {dependency.name} 失败: {e}")
            return DependencyCheckResult(
                dependency=dependency,
                status=DependencyStatus.CHECK_FAILED,
                error_message=str(e)
            )
    
    @classmethod
    def _check_custom(cls, dependency: Dependency) -> DependencyCheckResult:
        """执行自定义检查函数
        
        Args:
            dependency: 依赖定义
            
        Returns:
            检查结果
        """
        if not dependency.check_func:
            return DependencyCheckResult(
                dependency=dependency,
                status=DependencyStatus.CHECK_FAILED,
                error_message="自定义依赖缺少检查函数"
            )
        
        try:
            is_available = dependency.check_func()
            return DependencyCheckResult(
                dependency=dependency,
                status=DependencyStatus.AVAILABLE if is_available else DependencyStatus.MISSING
            )
        except Exception as e:
            return DependencyCheckResult(
                dependency=dependency,
                status=DependencyStatus.CHECK_FAILED,
                error_message=str(e)
            )

    
    @classmethod
    def _get_binary_version(cls, command: str) -> Optional[str]:
        """获取二进制文件版本
        
        尝试多种常见的版本参数获取版本信息。
        
        Args:
            command: 命令名称
            
        Returns:
            版本字符串，无法获取则返回 None
        """
        version_args = ["--version", "-version", "-v", "version"]
        
        for arg in version_args:
            try:
                result = subprocess.run(
                    [command, arg],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                output = result.stdout or result.stderr
                if output:
                    # 尝试从输出中提取版本号
                    version = cls._extract_version_from_output(output)
                    if version:
                        return version
            except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
                continue
            except Exception:
                continue
        
        return None
    
    @classmethod
    def _extract_version_from_output(cls, output: str) -> Optional[str]:
        """从命令输出中提取版本号
        
        Args:
            output: 命令输出
            
        Returns:
            版本字符串
        """
        import re
        
        # 常见的版本号模式
        patterns = [
            r'(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)',  # 1.2.3 或 1.2.3-beta
            r'(\d+\.\d+)',  # 1.2
            r'version\s+(\d+(?:\.\d+)*)',  # version 1.2.3
            r'v(\d+(?:\.\d+)*)',  # v1.2.3
        ]
        
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    @classmethod
    def _get_python_package_version(cls, package_name: str) -> Optional[str]:
        """获取 Python 包版本
        
        Args:
            package_name: 包名称
            
        Returns:
            版本字符串
        """
        try:
            return importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            # 尝试使用常见的别名
            aliases = cls._get_package_aliases(package_name)
            for alias in aliases:
                try:
                    return importlib.metadata.version(alias)
                except importlib.metadata.PackageNotFoundError:
                    continue
        return None
    
    @classmethod
    def _get_module_name(cls, package_name: str) -> str:
        """获取包对应的模块名
        
        处理包名和模块名不一致的情况。
        
        Args:
            package_name: 包名称
            
        Returns:
            模块名称
        """
        # 常见的包名到模块名映射
        mapping = {
            "pillow": "PIL",
            "pil": "PIL",
            "opencv-python": "cv2",
            "opencv-python-headless": "cv2",
            "scikit-learn": "sklearn",
            "scikit-image": "skimage",
            "pyyaml": "yaml",
            "pymupdf": "fitz",
            "beautifulsoup4": "bs4",
            "python-dateutil": "dateutil",
            "python-dotenv": "dotenv",
            "paddleocr": "paddleocr",
            "paddlepaddle": "paddle",
        }
        
        return mapping.get(package_name.lower(), package_name.replace("-", "_"))
    
    @classmethod
    def _get_package_aliases(cls, package_name: str) -> List[str]:
        """获取包的别名列表
        
        Args:
            package_name: 包名称
            
        Returns:
            别名列表
        """
        # 常见的包别名
        aliases_map = {
            "PIL": ["pillow", "Pillow"],
            "pillow": ["Pillow", "PIL"],
            "cv2": ["opencv-python", "opencv-python-headless"],
            "yaml": ["pyyaml", "PyYAML"],
            "fitz": ["pymupdf", "PyMuPDF"],
        }
        
        return aliases_map.get(package_name, [])
    
    @classmethod
    def _compare_versions(cls, installed: str, required: str) -> bool:
        """比较版本号
        
        Args:
            installed: 已安装版本
            required: 要求的最低版本
            
        Returns:
            已安装版本是否满足要求
        """
        try:
            from packaging import version
            return version.parse(installed) >= version.parse(required)
        except ImportError:
            # 如果没有 packaging 库，使用简单的字符串比较
            return cls._simple_version_compare(installed, required)
    
    @classmethod
    def _simple_version_compare(cls, v1: str, v2: str) -> bool:
        """简单版本比较（不依赖 packaging 库）
        
        Args:
            v1: 版本 1
            v2: 版本 2
            
        Returns:
            v1 >= v2
        """
        def normalize(v: str) -> List[int]:
            # 移除非数字后缀
            import re
            v = re.split(r'[^0-9.]', v)[0]
            return [int(x) for x in v.split('.') if x.isdigit()]
        
        try:
            parts1 = normalize(v1)
            parts2 = normalize(v2)
            
            # 补齐长度
            max_len = max(len(parts1), len(parts2))
            parts1.extend([0] * (max_len - len(parts1)))
            parts2.extend([0] * (max_len - len(parts2)))
            
            return parts1 >= parts2
        except Exception:
            return True  # 无法比较时假设满足


# 便捷函数

def check_binary(name: str, required: bool = True, min_version: Optional[str] = None) -> DependencyCheckResult:
    """检查二进制文件依赖
    
    Args:
        name: 命令名称
        required: 是否必需
        min_version: 最低版本要求
        
    Returns:
        检查结果
    """
    dep = Dependency(
        name=name,
        type=DependencyType.BINARY,
        required=required,
        min_version=min_version
    )
    return DependencyChecker.check(dep)


def check_python_package(name: str, required: bool = True, min_version: Optional[str] = None) -> DependencyCheckResult:
    """检查 Python 包依赖
    
    Args:
        name: 包名称
        required: 是否必需
        min_version: 最低版本要求
        
    Returns:
        检查结果
    """
    dep = Dependency(
        name=name,
        type=DependencyType.PYTHON,
        required=required,
        min_version=min_version
    )
    return DependencyChecker.check(dep)


def is_binary_available(name: str) -> bool:
    """检查二进制文件是否可用
    
    Args:
        name: 命令名称
        
    Returns:
        是否可用
    """
    return check_binary(name, required=False).is_satisfied


def is_python_package_available(name: str) -> bool:
    """检查 Python 包是否可用
    
    Args:
        name: 包名称
        
    Returns:
        是否可用
    """
    return check_python_package(name, required=False).is_satisfied


def get_binary_version(name: str) -> Optional[str]:
    """获取二进制文件版本
    
    Args:
        name: 命令名称
        
    Returns:
        版本字符串，不可用则返回 None
    """
    result = check_binary(name, required=False)
    return result.installed_version if result.is_satisfied else None


def get_python_package_version(name: str) -> Optional[str]:
    """获取 Python 包版本
    
    Args:
        name: 包名称
        
    Returns:
        版本字符串，不可用则返回 None
    """
    result = check_python_package(name, required=False)
    return result.installed_version if result.is_satisfied else None
