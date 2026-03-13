"""MCP (Model Context Protocol) 模块

提供 MCP 客户端功能，支持连接 MCP 服务器并调用其工具。

主要组件:
- MCPClient: MCP 客户端，管理服务器连接和工具调用
- MCPServerConfig: MCP 服务器配置
- MCPToolAdapter: MCP 工具适配器，将 MCP 工具转换为本地 Tool 接口
- MCPToolRegistry: MCP 工具注册表，管理 MCP 工具的发现和注册
- MCPRegistry: MCP 服务器注册表，管理服务器发现和生命周期
- MCPPolicy: MCP 策略配置，控制黑白名单和自动批准
"""

from .client import (
    MCPClient, 
    MCPServerConfig, 
    MCPConnectionState,
    MCPToolInfo,
    MCPResourceInfo,
    MCPPromptInfo,
)
from .adapter import MCPToolAdapter, MCPToolRegistry
from .registry import MCPRegistry, MCPServerStatus
from .mcp_policy import MCPPolicy, load_mcp_policy

__all__ = [
    # Client
    "MCPClient",
    "MCPServerConfig", 
    "MCPConnectionState",
    "MCPToolInfo",
    "MCPResourceInfo",
    "MCPPromptInfo",
    # Adapter
    "MCPToolAdapter",
    "MCPToolRegistry",
    # Registry
    "MCPRegistry",
    "MCPServerStatus",
    # Policy
    "MCPPolicy",
    "load_mcp_policy",
]
