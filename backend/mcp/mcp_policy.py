"""MCP 配置模块

提供 MCP 策略配置，支持黑白名单和自动批准工具。

主要功能:
- MCPPolicy: MCP 策略配置，控制服务器访问
- 从主配置文件 config.json 的 mcp 字段加载
- 支持环境变量覆盖
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class MCPPolicy(BaseModel):
    """MCP 策略配置
    
    控制 MCP 服务器的访问策略。大部分字段可省略，使用代码默认值。
    
    Attributes:
        timeout: 默认连接超时时间（秒），默认 30
        whitelist: 允许的服务器名称列表（空/省略表示允许所有）
        blacklist: 禁止的服务器名称列表（空/省略表示不禁止）
    
    配置示例 (config.json):
    ```json
    {
      "mcp": {
        "timeout": 30
      }
    }
    ```
    
    完整配置（仅在需要时使用）:
    ```json
    {
      "mcp": {
        "timeout": 60,
        "whitelist": ["filesystem", "github"],
        "blacklist": ["puppeteer"]
      }
    }
    ```
    """
    model_config = ConfigDict(populate_by_name=True)
    
    timeout: int = Field(default=30)
    whitelist: List[str] = Field(default_factory=list)
    blacklist: List[str] = Field(default_factory=list)
    
    def is_server_allowed(self, server_name: str) -> bool:
        """检查服务器是否被允许
        
        规则:
        1. 如果在黑名单中，拒绝
        2. 如果白名单为空，允许所有（除黑名单外）
        3. 如果白名单非空，只允许白名单中的服务器
        
        Args:
            server_name: 服务器名称
            
        Returns:
            是否允许
        """
        if server_name in self.blacklist:
            return False
        if not self.whitelist:
            return True
        return server_name in self.whitelist
    
    def apply_env_overrides(self, env_prefix: str = "MCP_") -> None:
        """应用环境变量覆盖
        
        支持的环境变量:
        - MCP_TIMEOUT=<seconds>
        - MCP_WHITELIST=server1,server2
        - MCP_BLACKLIST=server1,server2
        
        Args:
            env_prefix: 环境变量前缀
        """
        key = f"{env_prefix}TIMEOUT"
        if key in os.environ:
            try:
                self.timeout = int(os.environ[key])
            except ValueError:
                logger.warning(f"无效的超时值: {os.environ[key]}")
        
        key = f"{env_prefix}WHITELIST"
        if key in os.environ:
            value = os.environ[key].strip()
            if value:
                self.whitelist = [s.strip() for s in value.split(",")]
        
        key = f"{env_prefix}BLACKLIST"
        if key in os.environ:
            value = os.environ[key].strip()
            if value:
                self.blacklist = [s.strip() for s in value.split(",")]


def load_mcp_policy(config_data: Optional[Dict[str, Any]] = None) -> MCPPolicy:
    """加载 MCP 策略配置
    
    从配置字典加载 MCP 策略，支持环境变量覆盖。
    
    Args:
        config_data: 配置字典（config.json 的 mcp 字段），None 使用默认值
        
    Returns:
        MCPPolicy 实例
    
    示例:
    ```python
    # 最简配置
    policy = load_mcp_policy({"timeout": 60})
    
    # 使用默认值
    policy = load_mcp_policy()
    ```
    """
    if config_data:
        policy = MCPPolicy.model_validate(config_data)
    else:
        policy = MCPPolicy()
    
    policy.apply_env_overrides()
    return policy
