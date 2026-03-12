"""文件系统策略模块

管理文件系统访问控制，支持路径白名单/黑名单验证。

主要功能:
- 读取路径白名单/黑名单: 控制哪些路径可以读取
- 写入路径白名单/黑名单: 控制哪些路径可以写入/删除
- 目录遍历攻击防护: 防止通过 ../ 等方式访问危险路径
- Glob 模式匹配: 支持 *, ?, [], ** 等模式
"""

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ============================================================================
# 操作类型
# ============================================================================

class FSOperation(Enum):
    """文件系统操作类型"""
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    
    @classmethod
    def is_write_operation(cls, op: "FSOperation") -> bool:
        """检查是否为写入类操作（写入或删除）"""
        return op in (cls.WRITE, cls.DELETE)


# ============================================================================
# 路径验证结果
# ============================================================================

@dataclass
class PathValidationResult:
    """路径验证结果
    
    Attributes:
        allowed: 是否允许访问
        reason: 拒绝原因（如果不允许）
        resolved_path: 解析后的绝对路径
        checked_by: 检查方式
    """
    allowed: bool
    reason: Optional[str] = None
    resolved_path: Optional[Path] = None
    checked_by: Optional[str] = None
    
    @classmethod
    def allow(cls, resolved_path: Path, checked_by: str = "default") -> "PathValidationResult":
        """创建允许结果"""
        return cls(allowed=True, resolved_path=resolved_path, checked_by=checked_by)
    
    @classmethod
    def deny(cls, reason: str, checked_by: str = "default") -> "PathValidationResult":
        """创建拒绝结果"""
        return cls(allowed=False, reason=reason, checked_by=checked_by)


# ============================================================================
# 危险路径模式
# ============================================================================

# 危险的路径模式（正则表达式）
DANGEROUS_PATH_PATTERNS: List[str] = [
    r"\.\.[\\/]",           # 目录遍历 ../
    r"[\\/]\.\.[\\/]",      # 中间的目录遍历 /../
    r"[\\/]\.\.$",          # 结尾的目录遍历 /..
    r"^\.\.[\\/]",          # 开头的目录遍历 ../
    r"^\.\./?$",            # 单独的 .. 或 ../
]

# 编译正则表达式
_DANGEROUS_PATTERNS = [re.compile(p) for p in DANGEROUS_PATH_PATTERNS]


def is_dangerous_path(path: str) -> bool:
    """检查路径是否包含危险模式
    
    Args:
        path: 要检查的路径字符串
        
    Returns:
        如果路径包含危险模式返回 True
    """
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(path):
            return True
    return False


def match_glob_pattern(path: Union[str, Path], pattern: str, base_path: Optional[Path] = None) -> bool:
    """检查路径是否匹配 glob 模式
    
    支持的模式:
    - `*`: 匹配任意字符（不包括路径分隔符）
    - `?`: 匹配单个字符
    - `[seq]`: 匹配 seq 中的任意字符
    - `[!seq]`: 匹配不在 seq 中的任意字符
    - `**`: 匹配任意层级的目录
    
    Args:
        path: 要检查的路径
        pattern: glob 模式
        base_path: 基础路径（用于解析相对路径模式）
        
    Returns:
        如果路径匹配模式返回 True
    """
    path_str = str(path)
    path_obj = Path(path)
    
    # 标准化路径分隔符
    path_str = path_str.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    
    # 如果模式以 / 结尾，表示匹配目录及其所有内容
    if pattern.endswith("/"):
        pattern = pattern + "**"
    
    # 处理 ** 模式（匹配任意层级）
    if "**" in pattern:
        # 将 ** 转换为正则表达式
        regex_pattern = pattern.replace(".", r"\.")
        regex_pattern = regex_pattern.replace("**", ".*")
        regex_pattern = regex_pattern.replace("*", "[^/]*")
        regex_pattern = regex_pattern.replace("?", "[^/]")
        regex_pattern = "^" + regex_pattern + "$"
        
        try:
            if re.match(regex_pattern, path_str):
                return True
        except re.error:
            pass
    
    # 使用 fnmatch 进行标准 glob 匹配
    if fnmatch.fnmatch(path_str, pattern):
        return True
    
    # 检查路径的各个部分是否匹配
    # 例如: pattern="*.py" 应该匹配 "src/main.py"
    path_parts = path_str.split("/")
    for part in path_parts:
        if fnmatch.fnmatch(part, pattern):
            return True
    
    # 检查是否是子路径匹配
    # 例如: pattern="src/" 应该匹配 "src/main.py"
    pattern_clean = pattern.rstrip("/")
    if path_str.startswith(pattern_clean + "/") or path_str == pattern_clean:
        return True
    
    # 检查路径是否在模式指定的目录下
    # 例如: pattern="src/**" 应该匹配 "src/utils/helper.py"
    if pattern.endswith("/**"):
        dir_pattern = pattern[:-3]
        if path_str.startswith(dir_pattern + "/") or path_str == dir_pattern:
            return True
    
    return False


def matches_any_pattern(path: Union[str, Path], patterns: List[str], base_path: Optional[Path] = None) -> bool:
    """检查路径是否匹配任一 glob 模式
    
    Args:
        path: 要检查的路径
        patterns: glob 模式列表
        base_path: 基础路径
        
    Returns:
        如果路径匹配任一模式返回 True
    """
    for pattern in patterns:
        if match_glob_pattern(path, pattern, base_path):
            return True
    return False


# ============================================================================
# 文件系统策略
# ============================================================================

@dataclass
class FSPolicy:
    """文件系统策略
    
    管理文件系统访问控制，支持读写分离的路径白名单/黑名单。
    
    Attributes:
        read_allowed_paths: 允许读取的路径白名单（支持 glob 模式，空=不限制）
        read_denied_paths: 禁止读取的路径黑名单（支持 glob 模式）
        write_allowed_paths: 允许写入/删除的路径白名单（支持 glob 模式，空=不限制）
        write_denied_paths: 禁止写入/删除的路径黑名单（支持 glob 模式）
    
    Glob 模式支持:
        - `*`: 匹配任意字符（不包括路径分隔符）
        - `?`: 匹配单个字符
        - `[seq]`: 匹配 seq 中的任意字符
        - `**`: 匹配任意层级的目录
        - `dir/`: 匹配目录及其所有内容
    
    示例:
        - `*.py`: 匹配所有 Python 文件
        - `src/**`: 匹配 src 目录下所有文件
        - `.env*`: 匹配 .env, .env.local 等
        - `secrets/`: 匹配 secrets 目录及其所有内容
    """
    
    read_allowed_paths: Optional[List[str]] = None
    read_denied_paths: Optional[List[str]] = None
    write_allowed_paths: Optional[List[str]] = None
    write_denied_paths: Optional[List[str]] = None
    
    @classmethod
    def create(cls, **kwargs) -> "FSPolicy":
        """创建文件系统策略"""
        return cls(**kwargs)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FSPolicy":
        """从字典创建策略"""
        return cls(
            read_allowed_paths=data.get("read_allowed_paths"),
            read_denied_paths=data.get("read_denied_paths"),
            write_allowed_paths=data.get("write_allowed_paths"),
            write_denied_paths=data.get("write_denied_paths"),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "read_allowed_paths": self.read_allowed_paths,
            "read_denied_paths": self.read_denied_paths,
            "write_allowed_paths": self.write_allowed_paths,
            "write_denied_paths": self.write_denied_paths,
        }
    
    def _check_dangerous_patterns(self, path: str) -> PathValidationResult:
        """检查危险路径模式（目录遍历）"""
        if is_dangerous_path(path):
            return PathValidationResult.deny(
                f"路径包含危险模式（目录遍历）: {path}",
                "dangerous_pattern"
            )
        return PathValidationResult.allow(Path(path), "pattern_check")
    
    def _check_allowed_paths(self, path: Path, operation: FSOperation = None) -> PathValidationResult:
        """检查路径白名单"""
        # 确定使用哪个白名单
        allowed_list = None
        if operation == FSOperation.READ:
            allowed_list = self.read_allowed_paths
        elif operation and FSOperation.is_write_operation(operation):
            allowed_list = self.write_allowed_paths
        
        # 如果没有配置白名单，默认允许
        if not allowed_list:
            return PathValidationResult.allow(path, "no_whitelist")
        
        path_str = str(path)
        resolved = path.resolve()
        resolved_str = str(resolved)
        
        for allowed in allowed_list:
            if match_glob_pattern(path_str, allowed) or match_glob_pattern(resolved_str, allowed):
                return PathValidationResult.allow(resolved, "whitelist_glob")
            try:
                resolved.relative_to(Path(allowed).resolve())
                return PathValidationResult.allow(resolved, "whitelist_prefix")
            except ValueError:
                continue
        
        return PathValidationResult.deny(f"路径 {path} 不在允许的路径列表中", "whitelist")
    
    def _check_denied_paths(self, path: Path, operation: FSOperation = None) -> PathValidationResult:
        """检查路径黑名单"""
        # 确定使用哪个黑名单
        denied_list = None
        if operation == FSOperation.READ:
            denied_list = self.read_denied_paths
        elif operation and FSOperation.is_write_operation(operation):
            denied_list = self.write_denied_paths
        
        # 如果没有配置黑名单，默认允许
        if not denied_list:
            return PathValidationResult.allow(path, "no_blacklist")
        
        path_str = str(path)
        resolved = path.resolve()
        resolved_str = str(resolved)
        
        for denied in denied_list:
            if match_glob_pattern(path_str, denied) or match_glob_pattern(resolved_str, denied):
                return PathValidationResult.deny(f"路径 {path} 匹配禁止访问的模式: {denied}", "blacklist_glob")
            try:
                resolved.relative_to(Path(denied).resolve())
                return PathValidationResult.deny(f"路径 {path} 在禁止访问的路径列表中", "blacklist_prefix")
            except ValueError:
                continue
        
        return PathValidationResult.allow(resolved, "blacklist_check")
    
    def validate_path(
        self,
        path: Union[str, Path],
        operation: Union[str, FSOperation] = "access",
    ) -> PathValidationResult:
        """验证路径是否允许访问
        
        检查顺序: 危险模式 → 黑名单 → 白名单
        """
        path_str = str(path)
        
        # 转换操作类型
        fs_operation = None
        operation_name = "access"
        if isinstance(operation, FSOperation):
            fs_operation = operation
            operation_name = operation.value
        elif isinstance(operation, str):
            operation_name = operation
            try:
                fs_operation = FSOperation(operation.lower())
            except ValueError:
                pass
        
        # 1. 检查危险路径模式
        result = self._check_dangerous_patterns(path_str)
        if not result.allowed:
            logger.warning(f"[{operation_name}] {result.reason}")
            return result
        
        path_obj = Path(path)
        
        # 2. 检查黑名单
        result = self._check_denied_paths(path_obj, fs_operation)
        if not result.allowed:
            logger.warning(f"[{operation_name}] {result.reason}")
            return result
        
        # 3. 检查白名单
        result = self._check_allowed_paths(path_obj, fs_operation)
        if not result.allowed:
            logger.warning(f"[{operation_name}] {result.reason}")
            return result
        
        resolved = path_obj.resolve() if path_obj.exists() else path_obj
        logger.debug(f"[{operation_name}] 路径验证通过: {path} -> {resolved}")
        return PathValidationResult.allow(resolved, "all_checks_passed")
    
    def can_read(self, path: Union[str, Path]) -> bool:
        """检查路径是否可读"""
        return self.validate_path(path, FSOperation.READ).allowed
    
    def can_write(self, path: Union[str, Path]) -> bool:
        """检查路径是否可写"""
        return self.validate_path(path, FSOperation.WRITE).allowed
    
    def can_delete(self, path: Union[str, Path]) -> bool:
        """检查路径是否可删除"""
        return self.validate_path(path, FSOperation.DELETE).allowed
    
    def is_path_allowed(
        self,
        path: Union[str, Path],
        operation: Union[str, FSOperation] = "access",
    ) -> bool:
        """检查路径是否允许访问（简化版）
        
        Args:
            path: 要检查的路径
            operation: 操作类型
            
        Returns:
            是否允许访问
        """
        return self.validate_path(path, operation).allowed
    
    def resolve_safe_path(
        self,
        path: Union[str, Path],
        base_path: Optional[Union[str, Path]] = None,
    ) -> Optional[Path]:
        """安全地解析路径
        
        如果提供了 base_path，相对路径将相对于 base_path 解析。
        
        Args:
            path: 要解析的路径
            base_path: 基础路径（用于解析相对路径）
            
        Returns:
            解析后的安全路径，如果验证失败返回 None
        """
        path_obj = Path(path)
        
        # 如果是相对路径且提供了基础路径，则相对于基础路径解析
        if not path_obj.is_absolute() and base_path:
            path_obj = Path(base_path) / path_obj
        
        result = self.validate_path(path_obj)
        if result.allowed:
            return result.resolved_path
        return None
    
    def __repr__(self) -> str:
        """字符串表示"""
        read_allowed = len(self.read_allowed_paths) if self.read_allowed_paths else 0
        read_denied = len(self.read_denied_paths) if self.read_denied_paths else 0
        write_allowed = len(self.write_allowed_paths) if self.write_allowed_paths else 0
        write_denied = len(self.write_denied_paths) if self.write_denied_paths else 0
        
        return (
            f"FSPolicy(read_allowed={read_allowed}, read_denied={read_denied}, "
            f"write_allowed={write_allowed}, write_denied={write_denied})"
        )


# ============================================================================
# 便捷函数
# ============================================================================

def create_fs_policy(**kwargs) -> FSPolicy:
    """创建文件系统策略"""
    return FSPolicy(**kwargs)


def validate_path_safe(
    path: Union[str, Path],
    policy: Optional[FSPolicy] = None,
    operation: str = "access",
) -> PathValidationResult:
    """安全地验证路径"""
    if policy is None:
        policy = FSPolicy()
    return policy.validate_path(path, operation)


# 默认策略实例
default_fs_policy = FSPolicy()
