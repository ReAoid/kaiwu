"""工具策略模块

管理工具的白名单/黑名单权限控制。
支持基于用户角色和工具类型的权限检查。
参考: openclaw/src/agents/tool-policy.ts
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union

from core.tool import Tool

logger = logging.getLogger(__name__)


# ============================================================================
# 用户角色定义
# ============================================================================

class UserRole(Enum):
    """用户角色枚举
    
    定义系统中的用户角色层级，从高到低：
    - ADMIN: 管理员，拥有所有权限
    - OPERATOR: 操作员，可执行大部分操作
    - USER: 普通用户，受限访问
    - GUEST: 访客，只读访问
    """
    ADMIN = "admin"
    OPERATOR = "operator"
    USER = "user"
    GUEST = "guest"
    
    @classmethod
    def from_string(cls, role_str: str) -> "UserRole":
        """从字符串创建角色
        
        Args:
            role_str: 角色字符串
            
        Returns:
            对应的 UserRole 枚举值
            
        Raises:
            ValueError: 未知的角色字符串
        """
        role_str = role_str.strip().lower()
        for role in cls:
            if role.value == role_str:
                return role
        raise ValueError(f"未知的用户角色: {role_str}，可用选项: {[r.value for r in cls]}")
    
    def __ge__(self, other: "UserRole") -> bool:
        """比较角色权限级别（>=）"""
        order = [UserRole.GUEST, UserRole.USER, UserRole.OPERATOR, UserRole.ADMIN]
        return order.index(self) >= order.index(other)
    
    def __gt__(self, other: "UserRole") -> bool:
        """比较角色权限级别（>）"""
        order = [UserRole.GUEST, UserRole.USER, UserRole.OPERATOR, UserRole.ADMIN]
        return order.index(self) > order.index(other)
    
    def __le__(self, other: "UserRole") -> bool:
        """比较角色权限级别（<=）"""
        return not self > other
    
    def __lt__(self, other: "UserRole") -> bool:
        """比较角色权限级别（<）"""
        return not self >= other


# ============================================================================
# 工具类型定义
# ============================================================================

class ToolType(Enum):
    """工具类型枚举
    
    按功能分类工具：
    - READ: 只读操作（文件读取、搜索等）
    - WRITE: 写入操作（文件写入、创建等）
    - EXECUTE: 执行操作（命令执行、进程管理等）
    - NETWORK: 网络操作（HTTP 请求、搜索等）
    - MEDIA: 媒体处理（图像、PDF、音频等）
    - SYSTEM: 系统操作（配置、管理等）
    """
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    MEDIA = "media"
    SYSTEM = "system"
    
    @classmethod
    def from_string(cls, type_str: str) -> "ToolType":
        """从字符串创建工具类型
        
        Args:
            type_str: 类型字符串
            
        Returns:
            对应的 ToolType 枚举值
            
        Raises:
            ValueError: 未知的类型字符串
        """
        type_str = type_str.strip().lower()
        for tool_type in cls:
            if tool_type.value == type_str:
                return tool_type
        raise ValueError(f"未知的工具类型: {type_str}，可用选项: {[t.value for t in cls]}")


# 工具到类型的映射
TOOL_TYPE_MAPPING: Dict[str, ToolType] = {
    # 只读工具
    "file_read": ToolType.READ,
    # 写入工具
    "file_write": ToolType.WRITE,
    "file_delete": ToolType.WRITE,
    "code_edit": ToolType.WRITE,
    # 执行工具
    "bash_exec": ToolType.EXECUTE,
    "process_manager": ToolType.EXECUTE,
    # 网络工具
    "web_search": ToolType.NETWORK,
    "web_fetch": ToolType.NETWORK,
    # 媒体工具
    "image_tool": ToolType.MEDIA,
    "pdf_tool": ToolType.MEDIA,
    "tts_tool": ToolType.MEDIA,
}


def get_tool_type(tool_name: str) -> Optional[ToolType]:
    """获取工具的类型
    
    Args:
        tool_name: 工具名称
        
    Returns:
        工具类型，如果未知则返回 None
    """
    normalized = tool_name.strip().lower()
    # 先检查别名
    normalized = TOOL_NAME_ALIASES.get(normalized, normalized)
    return TOOL_TYPE_MAPPING.get(normalized)


def get_tools_by_type(tool_type: ToolType) -> List[str]:
    """获取指定类型的所有工具
    
    Args:
        tool_type: 工具类型
        
    Returns:
        该类型的工具名称列表
    """
    return [name for name, t in TOOL_TYPE_MAPPING.items() if t == tool_type]


# ============================================================================
# 角色权限配置
# ============================================================================

# 角色对工具类型的默认权限
# True 表示允许，False 表示禁止
ROLE_TYPE_PERMISSIONS: Dict[UserRole, Dict[ToolType, bool]] = {
    UserRole.ADMIN: {
        ToolType.READ: True,
        ToolType.WRITE: True,
        ToolType.EXECUTE: True,
        ToolType.NETWORK: True,
        ToolType.MEDIA: True,
        ToolType.SYSTEM: True,
    },
    UserRole.OPERATOR: {
        ToolType.READ: True,
        ToolType.WRITE: True,
        ToolType.EXECUTE: True,
        ToolType.NETWORK: True,
        ToolType.MEDIA: True,
        ToolType.SYSTEM: False,
    },
    UserRole.USER: {
        ToolType.READ: True,
        ToolType.WRITE: True,
        ToolType.EXECUTE: False,
        ToolType.NETWORK: True,
        ToolType.MEDIA: True,
        ToolType.SYSTEM: False,
    },
    UserRole.GUEST: {
        ToolType.READ: True,
        ToolType.WRITE: False,
        ToolType.EXECUTE: False,
        ToolType.NETWORK: False,
        ToolType.MEDIA: False,
        ToolType.SYSTEM: False,
    },
}

# 角色对特定工具的权限覆盖
# 可以覆盖类型级别的权限
ROLE_TOOL_OVERRIDES: Dict[UserRole, Dict[str, bool]] = {
    UserRole.ADMIN: {},  # 管理员无需覆盖
    UserRole.OPERATOR: {},
    UserRole.USER: {
        # 用户可以使用 bash_exec 但需要审批（这里先允许）
        # 实际审批逻辑在其他地方处理
    },
    UserRole.GUEST: {
        # 访客可以使用 web_search（覆盖 NETWORK 类型的禁止）
        "web_search": True,
    },
}


# ============================================================================
# 工具名称别名和分组
# ============================================================================

# 工具名称别名映射
TOOL_NAME_ALIASES: Dict[str, str] = {
    "bash": "bash_exec",
    "shell": "bash_exec",
    "read": "file_read",
    "write": "file_write",
    "delete": "file_delete",
}

# 工具分组定义
TOOL_GROUPS: Dict[str, List[str]] = {
    "group:fs": ["file_read", "file_write", "file_delete"],
    "group:runtime": ["bash_exec", "process_manager"],
    "group:web": ["web_search", "web_fetch"],
    "group:media": ["image_tool", "pdf_tool", "tts_tool"],
    "group:code": ["code_edit"],
    "group:all": [],  # 动态填充
    # 按工具类型的分组
    "group:read": get_tools_by_type(ToolType.READ),
    "group:write": get_tools_by_type(ToolType.WRITE),
    "group:execute": get_tools_by_type(ToolType.EXECUTE),
    "group:network": get_tools_by_type(ToolType.NETWORK),
}

# 预定义的工具配置文件
TOOL_PROFILES: Dict[str, Dict[str, Optional[List[str]]]] = {
    "minimal": {
        "allow": ["file_read"],
        "deny": None,
    },
    "coding": {
        "allow": ["file_read", "file_write", "file_delete", "bash_exec", "code_edit"],
        "deny": None,
    },
    "full": {
        "allow": None,  # None 表示允许所有
        "deny": None,
    },
    "safe": {
        "allow": ["file_read", "web_search", "web_fetch"],
        "deny": ["bash_exec", "file_write", "file_delete"],
    },
}


def normalize_tool_name(name: str) -> str:
    """规范化工具名称
    
    Args:
        name: 原始工具名称
        
    Returns:
        规范化后的工具名称
    """
    normalized = name.strip().lower()
    return TOOL_NAME_ALIASES.get(normalized, normalized)


def normalize_tool_list(tools: Optional[List[str]]) -> List[str]:
    """规范化工具名称列表
    
    Args:
        tools: 工具名称列表
        
    Returns:
        规范化后的工具名称列表
    """
    if not tools:
        return []
    return [normalize_tool_name(t) for t in tools if t and t.strip()]


def expand_tool_groups(tools: Optional[List[str]], all_tools: Optional[Set[str]] = None) -> List[str]:
    """展开工具分组
    
    将工具分组名称展开为具体的工具名称列表。
    
    Args:
        tools: 工具名称列表（可能包含分组名称）
        all_tools: 所有可用工具的集合（用于展开 group:all）
        
    Returns:
        展开后的工具名称列表
    """
    if not tools:
        return []
    
    normalized = normalize_tool_list(tools)
    expanded: List[str] = []
    
    for tool in normalized:
        if tool == "group:all" and all_tools:
            expanded.extend(all_tools)
        elif tool in TOOL_GROUPS:
            group_tools = TOOL_GROUPS[tool]
            if group_tools:
                expanded.extend(group_tools)
            else:
                # 空分组，保留原名
                expanded.append(tool)
        else:
            expanded.append(tool)
    
    # 去重并保持顺序
    seen: Set[str] = set()
    result: List[str] = []
    for tool in expanded:
        if tool not in seen:
            seen.add(tool)
            result.append(tool)
    
    return result


@dataclass
class ToolPolicy:
    """工具策略
    
    管理工具的白名单和黑名单，支持工具分组和配置文件。
    
    Attributes:
        allow: 允许的工具列表（白名单），None 表示允许所有
        deny: 禁止的工具列表（黑名单），None 表示不禁止任何工具
        owner_only_tools: 仅所有者可用的工具集合
    """
    
    allow: Optional[List[str]] = None
    deny: Optional[List[str]] = None
    owner_only_tools: Set[str] = field(default_factory=set)
    
    def __post_init__(self):
        """初始化后处理"""
        # 规范化白名单和黑名单
        if self.allow is not None:
            self.allow = normalize_tool_list(self.allow)
        if self.deny is not None:
            self.deny = normalize_tool_list(self.deny)
    
    @classmethod
    def from_profile(cls, profile: str) -> "ToolPolicy":
        """从预定义配置文件创建策略
        
        Args:
            profile: 配置文件名称 (minimal, coding, full, safe)
            
        Returns:
            工具策略实例
            
        Raises:
            ValueError: 未知的配置文件名称
        """
        if profile not in TOOL_PROFILES:
            raise ValueError(f"未知的工具配置文件: {profile}，可用选项: {list(TOOL_PROFILES.keys())}")
        
        config = TOOL_PROFILES[profile]
        return cls(
            allow=config.get("allow"),
            deny=config.get("deny"),
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolPolicy":
        """从字典创建策略
        
        Args:
            data: 包含 allow 和 deny 键的字典
            
        Returns:
            工具策略实例
        """
        return cls(
            allow=data.get("allow"),
            deny=data.get("deny"),
            owner_only_tools=set(data.get("owner_only_tools", [])),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典
        
        Returns:
            策略的字典表示
        """
        return {
            "allow": self.allow,
            "deny": self.deny,
            "owner_only_tools": list(self.owner_only_tools),
        }
    
    def is_tool_allowed(self, tool_name: str, all_tools: Optional[Set[str]] = None) -> bool:
        """检查工具是否被允许
        
        Args:
            tool_name: 工具名称
            all_tools: 所有可用工具的集合（用于展开 group:all）
            
        Returns:
            工具是否被允许使用
        """
        normalized_name = normalize_tool_name(tool_name)
        
        # 首先检查黑名单
        if self.deny is not None:
            expanded_deny = expand_tool_groups(self.deny, all_tools)
            if normalized_name in expanded_deny:
                logger.debug(f"工具 {tool_name} 在黑名单中，拒绝访问")
                return False
        
        # 然后检查白名单
        if self.allow is not None:
            expanded_allow = expand_tool_groups(self.allow, all_tools)
            if normalized_name not in expanded_allow:
                logger.debug(f"工具 {tool_name} 不在白名单中，拒绝访问")
                return False
        
        return True
    
    def is_owner_only(self, tool_name: str) -> bool:
        """检查工具是否仅所有者可用
        
        Args:
            tool_name: 工具名称
            
        Returns:
            工具是否仅所有者可用
        """
        normalized_name = normalize_tool_name(tool_name)
        return normalized_name in self.owner_only_tools
    
    def filter_tools(
        self,
        tools: List[Tool],
        is_owner: bool = True,
    ) -> List[Tool]:
        """根据策略过滤工具列表
        
        Args:
            tools: 工具列表
            is_owner: 当前用户是否为所有者
            
        Returns:
            过滤后的工具列表
        """
        all_tool_names = {normalize_tool_name(t.name) for t in tools}
        filtered: List[Tool] = []
        
        for tool in tools:
            normalized_name = normalize_tool_name(tool.name)
            
            # 检查是否仅所有者可用
            if self.is_owner_only(tool.name) and not is_owner:
                logger.debug(f"工具 {tool.name} 仅所有者可用，当前用户非所有者，跳过")
                continue
            
            # 检查是否被策略允许
            if not self.is_tool_allowed(tool.name, all_tool_names):
                continue
            
            filtered.append(tool)
        
        return filtered
    
    def merge(self, other: "ToolPolicy") -> "ToolPolicy":
        """合并两个策略
        
        合并规则：
        - 白名单取交集（更严格）
        - 黑名单取并集（更严格）
        - 所有者专属工具取并集
        
        Args:
            other: 另一个策略
            
        Returns:
            合并后的新策略
        """
        # 合并白名单（取交集）
        merged_allow: Optional[List[str]] = None
        if self.allow is not None and other.allow is not None:
            set_self = set(self.allow)
            set_other = set(other.allow)
            merged_allow = list(set_self & set_other)
        elif self.allow is not None:
            merged_allow = self.allow.copy()
        elif other.allow is not None:
            merged_allow = other.allow.copy()
        
        # 合并黑名单（取并集）
        merged_deny: Optional[List[str]] = None
        if self.deny is not None or other.deny is not None:
            set_self = set(self.deny) if self.deny else set()
            set_other = set(other.deny) if other.deny else set()
            merged_deny = list(set_self | set_other)
        
        # 合并所有者专属工具（取并集）
        merged_owner_only = self.owner_only_tools | other.owner_only_tools
        
        return ToolPolicy(
            allow=merged_allow,
            deny=merged_deny,
            owner_only_tools=merged_owner_only,
        )
    
    def add_to_allow(self, tools: List[str]) -> None:
        """添加工具到白名单
        
        Args:
            tools: 要添加的工具名称列表
        """
        normalized = normalize_tool_list(tools)
        if self.allow is None:
            self.allow = normalized
        else:
            existing = set(self.allow)
            for tool in normalized:
                if tool not in existing:
                    self.allow.append(tool)
                    existing.add(tool)
    
    def add_to_deny(self, tools: List[str]) -> None:
        """添加工具到黑名单
        
        Args:
            tools: 要添加的工具名称列表
        """
        normalized = normalize_tool_list(tools)
        if self.deny is None:
            self.deny = normalized
        else:
            existing = set(self.deny)
            for tool in normalized:
                if tool not in existing:
                    self.deny.append(tool)
                    existing.add(tool)
    
    def remove_from_allow(self, tools: List[str]) -> None:
        """从白名单移除工具
        
        Args:
            tools: 要移除的工具名称列表
        """
        if self.allow is None:
            return
        normalized = set(normalize_tool_list(tools))
        self.allow = [t for t in self.allow if t not in normalized]
        if not self.allow:
            self.allow = None
    
    def remove_from_deny(self, tools: List[str]) -> None:
        """从黑名单移除工具
        
        Args:
            tools: 要移除的工具名称列表
        """
        if self.deny is None:
            return
        normalized = set(normalize_tool_list(tools))
        self.deny = [t for t in self.deny if t not in normalized]
        if not self.deny:
            self.deny = None
    
    def set_owner_only(self, tools: List[str]) -> None:
        """设置仅所有者可用的工具
        
        Args:
            tools: 工具名称列表
        """
        normalized = normalize_tool_list(tools)
        self.owner_only_tools = set(normalized)
    
    def __repr__(self) -> str:
        """字符串表示"""
        return f"ToolPolicy(allow={self.allow}, deny={self.deny}, owner_only={self.owner_only_tools})"


def apply_tool_policy(
    tools: List[Tool],
    policy: Optional[ToolPolicy] = None,
    is_owner: bool = True,
) -> List[Tool]:
    """应用工具策略过滤工具列表
    
    便捷函数，用于快速应用策略过滤工具。
    
    Args:
        tools: 工具列表
        policy: 工具策略，None 表示不过滤
        is_owner: 当前用户是否为所有者
        
    Returns:
        过滤后的工具列表
    """
    if policy is None:
        return tools
    return policy.filter_tools(tools, is_owner)


def get_profile_names() -> List[str]:
    """获取所有可用的配置文件名称
    
    Returns:
        配置文件名称列表
    """
    return list(TOOL_PROFILES.keys())


def get_tool_groups() -> Dict[str, List[str]]:
    """获取所有工具分组
    
    Returns:
        工具分组字典
    """
    return TOOL_GROUPS.copy()


# ============================================================================
# 权限检查器
# ============================================================================

@dataclass
class PermissionContext:
    """权限检查上下文
    
    包含进行权限检查所需的所有上下文信息。
    
    Attributes:
        user_role: 用户角色
        is_owner: 是否为所有者
        session_id: 会话 ID（可选）
        metadata: 额外的元数据
    """
    user_role: UserRole = UserRole.USER
    is_owner: bool = False
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def for_owner(cls, role: UserRole = UserRole.ADMIN) -> "PermissionContext":
        """创建所有者上下文"""
        return cls(user_role=role, is_owner=True)
    
    @classmethod
    def for_guest(cls) -> "PermissionContext":
        """创建访客上下文"""
        return cls(user_role=UserRole.GUEST, is_owner=False)


@dataclass
class PermissionCheckResult:
    """权限检查结果
    
    Attributes:
        allowed: 是否允许
        reason: 拒绝原因（如果不允许）
        checked_by: 检查方式（role, type, policy, owner_only）
    """
    allowed: bool
    reason: Optional[str] = None
    checked_by: Optional[str] = None
    
    @classmethod
    def allow(cls, checked_by: str = "default") -> "PermissionCheckResult":
        """创建允许结果"""
        return cls(allowed=True, checked_by=checked_by)
    
    @classmethod
    def deny(cls, reason: str, checked_by: str = "default") -> "PermissionCheckResult":
        """创建拒绝结果"""
        return cls(allowed=False, reason=reason, checked_by=checked_by)


class PermissionChecker:
    """权限检查器
    
    提供基于用户角色和工具类型的权限检查功能。
    
    支持：
    - 基于用户角色的权限检查
    - 基于工具类型的权限检查
    - 自定义权限规则
    - 权限覆盖
    """
    
    def __init__(
        self,
        role_type_permissions: Optional[Dict[UserRole, Dict[ToolType, bool]]] = None,
        role_tool_overrides: Optional[Dict[UserRole, Dict[str, bool]]] = None,
        custom_checkers: Optional[List[Callable[[str, PermissionContext], Optional[PermissionCheckResult]]]] = None,
    ):
        """初始化权限检查器
        
        Args:
            role_type_permissions: 角色对工具类型的权限配置
            role_tool_overrides: 角色对特定工具的权限覆盖
            custom_checkers: 自定义权限检查函数列表
        """
        self.role_type_permissions = role_type_permissions or ROLE_TYPE_PERMISSIONS.copy()
        self.role_tool_overrides = role_tool_overrides or ROLE_TOOL_OVERRIDES.copy()
        self.custom_checkers = custom_checkers or []
    
    def check_role_permission(
        self,
        tool_name: str,
        context: PermissionContext,
    ) -> PermissionCheckResult:
        """检查基于角色的权限
        
        Args:
            tool_name: 工具名称
            context: 权限检查上下文
            
        Returns:
            权限检查结果
        """
        normalized_name = normalize_tool_name(tool_name)
        role = context.user_role
        
        # 1. 首先检查角色对特定工具的覆盖
        if role in self.role_tool_overrides:
            overrides = self.role_tool_overrides[role]
            if normalized_name in overrides:
                if overrides[normalized_name]:
                    logger.debug(f"工具 {tool_name} 被角色 {role.value} 的覆盖规则允许")
                    return PermissionCheckResult.allow("role_override")
                else:
                    logger.debug(f"工具 {tool_name} 被角色 {role.value} 的覆盖规则禁止")
                    return PermissionCheckResult.deny(
                        f"工具 {tool_name} 被角色 {role.value} 的覆盖规则禁止",
                        "role_override"
                    )
        
        # 2. 然后检查角色对工具类型的权限
        tool_type = get_tool_type(normalized_name)
        if tool_type is not None and role in self.role_type_permissions:
            type_permissions = self.role_type_permissions[role]
            if tool_type in type_permissions:
                if type_permissions[tool_type]:
                    logger.debug(f"工具 {tool_name} (类型: {tool_type.value}) 被角色 {role.value} 允许")
                    return PermissionCheckResult.allow("role_type")
                else:
                    logger.debug(f"工具 {tool_name} (类型: {tool_type.value}) 被角色 {role.value} 禁止")
                    return PermissionCheckResult.deny(
                        f"角色 {role.value} 不允许使用 {tool_type.value} 类型的工具",
                        "role_type"
                    )
        
        # 3. 默认允许（如果没有明确的规则）
        return PermissionCheckResult.allow("default")
    
    def check_type_permission(
        self,
        tool_name: str,
        allowed_types: Optional[Set[ToolType]] = None,
        denied_types: Optional[Set[ToolType]] = None,
    ) -> PermissionCheckResult:
        """检查基于工具类型的权限
        
        Args:
            tool_name: 工具名称
            allowed_types: 允许的工具类型集合
            denied_types: 禁止的工具类型集合
            
        Returns:
            权限检查结果
        """
        normalized_name = normalize_tool_name(tool_name)
        tool_type = get_tool_type(normalized_name)
        
        if tool_type is None:
            # 未知类型的工具，默认允许
            return PermissionCheckResult.allow("unknown_type")
        
        # 首先检查禁止列表
        if denied_types and tool_type in denied_types:
            return PermissionCheckResult.deny(
                f"工具类型 {tool_type.value} 被禁止",
                "type_deny"
            )
        
        # 然后检查允许列表
        if allowed_types is not None and tool_type not in allowed_types:
            return PermissionCheckResult.deny(
                f"工具类型 {tool_type.value} 不在允许列表中",
                "type_allow"
            )
        
        return PermissionCheckResult.allow("type")
    
    def check_permission(
        self,
        tool_name: str,
        context: PermissionContext,
        policy: Optional["ToolPolicy"] = None,
        allowed_types: Optional[Set[ToolType]] = None,
        denied_types: Optional[Set[ToolType]] = None,
    ) -> PermissionCheckResult:
        """综合权限检查
        
        按以下顺序检查权限：
        1. 自定义检查器
        2. 所有者专属工具检查
        3. 策略白名单/黑名单检查
        4. 工具类型检查
        5. 角色权限检查
        
        Args:
            tool_name: 工具名称
            context: 权限检查上下文
            policy: 工具策略（可选）
            allowed_types: 允许的工具类型（可选）
            denied_types: 禁止的工具类型（可选）
            
        Returns:
            权限检查结果
        """
        normalized_name = normalize_tool_name(tool_name)
        
        # 1. 运行自定义检查器
        for checker in self.custom_checkers:
            result = checker(normalized_name, context)
            if result is not None:
                return result
        
        # 2. 检查所有者专属工具
        if policy and policy.is_owner_only(normalized_name):
            if not context.is_owner:
                return PermissionCheckResult.deny(
                    f"工具 {tool_name} 仅所有者可用",
                    "owner_only"
                )
        
        # 3. 检查策略白名单/黑名单
        if policy:
            if not policy.is_tool_allowed(normalized_name):
                return PermissionCheckResult.deny(
                    f"工具 {tool_name} 被策略禁止",
                    "policy"
                )
        
        # 4. 检查工具类型
        type_result = self.check_type_permission(normalized_name, allowed_types, denied_types)
        if not type_result.allowed:
            return type_result
        
        # 5. 检查角色权限
        role_result = self.check_role_permission(normalized_name, context)
        if not role_result.allowed:
            return role_result
        
        return PermissionCheckResult.allow("all_checks_passed")
    
    def filter_tools_by_permission(
        self,
        tools: List[Tool],
        context: PermissionContext,
        policy: Optional["ToolPolicy"] = None,
        allowed_types: Optional[Set[ToolType]] = None,
        denied_types: Optional[Set[ToolType]] = None,
    ) -> List[Tool]:
        """根据权限过滤工具列表
        
        Args:
            tools: 工具列表
            context: 权限检查上下文
            policy: 工具策略（可选）
            allowed_types: 允许的工具类型（可选）
            denied_types: 禁止的工具类型（可选）
            
        Returns:
            过滤后的工具列表
        """
        filtered: List[Tool] = []
        
        for tool in tools:
            result = self.check_permission(
                tool.name,
                context,
                policy,
                allowed_types,
                denied_types,
            )
            if result.allowed:
                filtered.append(tool)
            else:
                logger.debug(f"工具 {tool.name} 被过滤: {result.reason}")
        
        return filtered
    
    def add_custom_checker(
        self,
        checker: Callable[[str, PermissionContext], Optional[PermissionCheckResult]],
    ) -> None:
        """添加自定义权限检查器
        
        Args:
            checker: 检查函数，接收工具名称和上下文，返回检查结果或 None
        """
        self.custom_checkers.append(checker)
    
    def set_role_type_permission(
        self,
        role: UserRole,
        tool_type: ToolType,
        allowed: bool,
    ) -> None:
        """设置角色对工具类型的权限
        
        Args:
            role: 用户角色
            tool_type: 工具类型
            allowed: 是否允许
        """
        if role not in self.role_type_permissions:
            self.role_type_permissions[role] = {}
        self.role_type_permissions[role][tool_type] = allowed
    
    def set_role_tool_override(
        self,
        role: UserRole,
        tool_name: str,
        allowed: bool,
    ) -> None:
        """设置角色对特定工具的权限覆盖
        
        Args:
            role: 用户角色
            tool_name: 工具名称
            allowed: 是否允许
        """
        normalized_name = normalize_tool_name(tool_name)
        if role not in self.role_tool_overrides:
            self.role_tool_overrides[role] = {}
        self.role_tool_overrides[role][normalized_name] = allowed


# 默认权限检查器实例
default_permission_checker = PermissionChecker()


def check_tool_permission(
    tool_name: str,
    context: PermissionContext,
    policy: Optional[ToolPolicy] = None,
) -> PermissionCheckResult:
    """检查工具权限（便捷函数）
    
    Args:
        tool_name: 工具名称
        context: 权限检查上下文
        policy: 工具策略（可选）
        
    Returns:
        权限检查结果
    """
    return default_permission_checker.check_permission(tool_name, context, policy)


def filter_tools_by_role(
    tools: List[Tool],
    role: UserRole,
    is_owner: bool = False,
    policy: Optional[ToolPolicy] = None,
) -> List[Tool]:
    """根据角色过滤工具列表（便捷函数）
    
    Args:
        tools: 工具列表
        role: 用户角色
        is_owner: 是否为所有者
        policy: 工具策略（可选）
        
    Returns:
        过滤后的工具列表
    """
    context = PermissionContext(user_role=role, is_owner=is_owner)
    return default_permission_checker.filter_tools_by_permission(tools, context, policy)


def filter_tools_by_type(
    tools: List[Tool],
    allowed_types: Optional[Set[ToolType]] = None,
    denied_types: Optional[Set[ToolType]] = None,
) -> List[Tool]:
    """根据工具类型过滤工具列表（便捷函数）
    
    Args:
        tools: 工具列表
        allowed_types: 允许的工具类型
        denied_types: 禁止的工具类型
        
    Returns:
        过滤后的工具列表
    """
    context = PermissionContext()
    return default_permission_checker.filter_tools_by_permission(
        tools, context, None, allowed_types, denied_types
    )
