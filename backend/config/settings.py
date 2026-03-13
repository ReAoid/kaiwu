"""Configuration management using Pydantic."""
import json
from pathlib import Path
from typing import List, Optional, Set

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from .paths import CONFIG_DIR


class FSPolicyConfig(BaseModel):
    """文件系统策略配置
    
    控制文件系统访问权限，读取和写入/删除权限分开控制。
    支持 glob 模式匹配 (*, ?, [], **)。
    
    Attributes:
        read_allowed_paths: 允许读取的路径白名单（空=不限制）
        read_denied_paths: 禁止读取的路径黑名单
        write_allowed_paths: 允许写入/删除的路径白名单（空=不限制）
        write_denied_paths: 禁止写入/删除的路径黑名单
    
    示例配置:
    ```json
    {
      "fs_policy": {
        "read_allowed_paths": [],
        "read_denied_paths": [".env", ".env.*", "*.key", "secrets/", "~/.ssh/"],
        "write_allowed_paths": [],
        "write_denied_paths": [".git/", "*-lock.json", "*.lock"]
      }
    }
    ```
    
    Glob 模式:
    - `*`: 匹配任意字符
    - `?`: 匹配单个字符
    - `[seq]`: 匹配字符集
    - `**`: 匹配任意层级目录
    - `dir/`: 匹配目录及其所有内容
    """
    read_allowed_paths: List[str] = Field(default_factory=list)
    read_denied_paths: List[str] = Field(default_factory=list)
    write_allowed_paths: List[str] = Field(default_factory=list)
    write_denied_paths: List[str] = Field(default_factory=list)


class ToolPolicyConfig(BaseModel):
    """工具策略配置
    
    控制哪些工具可用，支持白名单/黑名单模式。
    
    Attributes:
        profile: 预定义配置文件 (minimal, coding, full, safe)
        allow: 白名单 - 只允许这些工具（空数组=未启用，支持分组如 group:fs）
        deny: 黑名单 - 禁止这些工具（空数组=未启用）
        owner_only: 仅所有者可用的工具列表
        plugin_dirs: 额外的插件目录列表（支持动态加载工具）
    
    优先级规则（从高到低）:
    1. deny (黑名单) - 最高优先级，无论其他规则如何，黑名单中的工具一定被禁止
    2. allow (白名单) - 如果启用，只有白名单中的工具才允许使用
    3. profile - 最低优先级，作为基础配置
    
    同时配置 allow 和 deny 的行为:
    - 工具在 deny 中 → 禁止（黑名单优先）
    - 工具在 allow 中但不在 deny 中 → 允许
    - 工具不在 allow 中 → 禁止（白名单生效时）
    
    示例配置:
    ```json
    {
      "tool_policy": {
        "allow": ["file_read", "file_write", "bash_exec"],
        "deny": ["bash_exec"],
        "plugin_dirs": ["~/.kaiwu/plugins", "./custom_tools"]
      }
    }
    ```
    结果: file_read ✓, file_write ✓, bash_exec ✗ (黑名单优先)
    
    可用分组:
    - group:fs - 文件操作 (file_read, file_write, file_delete)
    - group:runtime - 运行时 (bash_exec, process_manager)
    - group:web - 网络 (web_search, web_fetch)
    - group:media - 媒体 (image_tool, pdf_tool, tts_tool)
    - group:code - 代码 (code_edit)
    """
    profile: Optional[str] = None  # minimal, coding, full, safe
    allow: List[str] = Field(default_factory=list)  # 空数组=未启用白名单
    deny: List[str] = Field(default_factory=list)   # 空数组=未启用黑名单
    owner_only: List[str] = Field(default_factory=list)
    plugin_dirs: List[str] = Field(default_factory=list)  # 额外的插件目录


class LLMApiConfig(BaseModel):
    """LLM API configuration."""
    key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 60


class ChatLLMConfig(BaseModel):
    """Chat LLM configuration."""
    model: str = "gpt-3.5-turbo"
    provider: str = "openai"
    temperature: float = 0.7
    api: LLMApiConfig = Field(default_factory=LLMApiConfig)


class SystemConfig(BaseModel):
    """System configuration."""
    debug: bool = False
    log_level: str = "INFO"


class GoogleSearchConfig(BaseModel):
    """Google Custom Search API configuration."""
    api_key: Optional[str] = None
    search_engine_id: Optional[str] = None  # cx parameter


class BingSearchConfig(BaseModel):
    """Bing Web Search API configuration."""
    api_key: Optional[str] = None


class WebSearchConfig(BaseModel):
    """Web search configuration."""
    default_provider: str = "duckduckgo"  # duckduckgo, google, bing
    timeout: int = 30
    google: GoogleSearchConfig = Field(default_factory=GoogleSearchConfig)
    bing: BingSearchConfig = Field(default_factory=BingSearchConfig)


class MCPConfig(BaseModel):
    """MCP (Model Context Protocol) configuration."""
    timeout: int = 30


class Settings(BaseSettings):
    """Global application settings."""
    chat_llm: ChatLLMConfig = Field(default_factory=ChatLLMConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    tool_policy: ToolPolicyConfig = Field(default_factory=ToolPolicyConfig)
    fs_policy: FSPolicyConfig = Field(default_factory=FSPolicyConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    app_name: str = "Kaiwu"

    @classmethod
    def load_from_file(cls, config_path: Optional[Path] = None, secrets_path: Optional[Path] = None) -> "Settings":
        """Load settings from config.json and secrets.json.
        
        config.json: General settings (can be committed to git)
        secrets.json: Sensitive settings like API keys (should not be committed)
        
        secrets.json takes precedence over config.json for overlapping keys.
        """
        if config_path is None:
            config_path = CONFIG_DIR / "config.json"
        if secrets_path is None:
            secrets_path = CONFIG_DIR / "secrets.json"
        
        config_data = {}
        
        # Load general config
        if config_path.exists():
            config_data = json.loads(config_path.read_text(encoding="utf-8"))
        
        # Load and merge secrets (takes precedence)
        if secrets_path.exists():
            secrets_data = json.loads(secrets_path.read_text(encoding="utf-8"))
            config_data = cls._deep_merge(config_data, secrets_data)
        
        if not config_data:
            # No config files exist, create defaults
            default_settings = cls()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(default_settings.model_dump(exclude={"chat_llm"}), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            return default_settings
        
        return cls.model_validate(config_data)
    
    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Deep merge two dictionaries, override takes precedence."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Settings._deep_merge(result[key], value)
            else:
                result[key] = value
        return result


    def get_tool_policy(self) -> "ToolPolicy":
        """从配置创建 ToolPolicy 对象
        
        优先级规则:
        1. deny (黑名单) - 最高优先级
        2. allow (白名单) - 次优先级
        3. profile - 基础配置
        
        空数组 [] 表示未启用该规则。
        
        Returns:
            配置的 ToolPolicy 实例
        """
        from tools.tool_policy import ToolPolicy, TOOL_PROFILES
        
        config = self.tool_policy
        
        # 如果指定了 profile，从 profile 开始
        if config.profile:
            if config.profile not in TOOL_PROFILES:
                raise ValueError(f"未知的工具配置文件: {config.profile}")
            policy = ToolPolicy.from_profile(config.profile)
        else:
            policy = ToolPolicy()
        
        # 应用 allow 覆盖（空数组=未启用，None=允许所有）
        if config.allow:  # 非空数组才启用白名单
            policy.allow = config.allow.copy()
        # 如果 allow 是空数组，保持 policy.allow = None（允许所有）
        
        # 应用 deny 覆盖（空数组=未启用）
        if config.deny:  # 非空数组才启用黑名单
            if policy.deny is None:
                policy.deny = config.deny.copy()
            else:
                # 合并黑名单
                existing = set(policy.deny)
                for tool in config.deny:
                    if tool not in existing:
                        policy.deny.append(tool)
        
        # 应用 owner_only
        if config.owner_only:
            policy.owner_only_tools = set(config.owner_only)
        
        return policy

    def get_fs_policy(self) -> "FSPolicy":
        """从配置创建 FSPolicy 对象
        
        Returns:
            配置的 FSPolicy 实例
        """
        from tools.fs_policy import FSPolicy
        
        config = self.fs_policy
        
        return FSPolicy(
            read_allowed_paths=config.read_allowed_paths if config.read_allowed_paths else None,
            read_denied_paths=config.read_denied_paths if config.read_denied_paths else None,
            write_allowed_paths=config.write_allowed_paths if config.write_allowed_paths else None,
            write_denied_paths=config.write_denied_paths if config.write_denied_paths else None,
        )

    def get_plugin_dirs(self) -> List[Path]:
        """获取配置的插件目录列表
        
        支持路径扩展（~, 环境变量等）。
        
        Returns:
            插件目录 Path 列表
        """
        dirs = []
        for dir_str in self.tool_policy.plugin_dirs:
            # 扩展 ~ 和环境变量
            expanded = Path(dir_str).expanduser()
            dirs.append(expanded)
        return dirs
