"""MCP 注册表模块

管理 MCP 服务器的动态发现、连接和生命周期。

主要功能:
- MCPRegistry: MCP 服务器注册表
- 支持动态发现 MCP 服务器
- 支持黑白名单策略控制
- 管理服务器连接生命周期
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .client import MCPClient, MCPServerConfig, MCPConnectionState
from .mcp_policy import MCPPolicy, load_mcp_policy

logger = logging.getLogger(__name__)


@dataclass
class MCPServerStatus:
    """MCP 服务器状态
    
    Attributes:
        name: 服务器名称
        state: 连接状态
        tools_count: 工具数量
        resources_count: 资源数量
        prompts_count: 提示词数量
        error: 错误信息（如果有）
        source: 配置来源（discovered/manual）
    """
    name: str
    state: MCPConnectionState
    tools_count: int = 0
    resources_count: int = 0
    prompts_count: int = 0
    error: Optional[str] = None
    source: str = "manual"


class MCPRegistry:
    """MCP 服务器注册表
    
    管理 MCP 服务器的动态发现、连接和生命周期。支持黑白名单策略控制。
    
    主要功能:
    - 动态发现 MCP 服务器（通过 uvx/npx 等包管理器）
    - 黑白名单策略控制
    - 管理服务器连接生命周期
    - 提供服务器状态监控
    
    使用示例:
    ```python
    # 创建注册表
    policy = load_mcp_policy(config.get("mcp"))
    registry = MCPRegistry(policy=policy)
    
    # 动态添加服务器
    config = MCPServerConfig(
        name="filesystem",
        command="uvx",
        args=["mcp-server-filesystem", "--root", "."]
    )
    registry.add_server(config)
    
    # 或自动发现
    await registry.discover_servers()
    
    # 连接所有服务器
    await registry.connect_all()
    ```
    """
    
    def __init__(
        self, 
        client: Optional[MCPClient] = None,
        policy: Optional[MCPPolicy] = None
    ):
        """初始化 MCP 注册表
        
        Args:
            client: MCP 客户端实例，如果为 None 则创建新实例
            policy: MCP 策略配置，如果为 None 则使用默认策略
        """
        self._client = client or MCPClient()
        self._policy = policy or MCPPolicy()
        self._configs: Dict[str, MCPServerConfig] = {}
        self._sources: Dict[str, str] = {}  # 记录配置来源
        self._state_callbacks: List[Callable[[str, MCPConnectionState], None]] = []
        
        # 注册客户端状态回调
        self._client.on_state_change(self._on_client_state_change)
    
    @property
    def client(self) -> MCPClient:
        """获取 MCP 客户端"""
        return self._client
    
    @property
    def policy(self) -> MCPPolicy:
        """获取 MCP 策略"""
        return self._policy
    
    def _on_client_state_change(self, name: str, state: MCPConnectionState) -> None:
        """处理客户端状态变化"""
        for callback in self._state_callbacks:
            try:
                callback(name, state)
            except Exception as e:
                logger.error(f"状态变化回调执行失败: {e}")
    
    def on_state_change(self, callback: Callable[[str, MCPConnectionState], None]) -> None:
        """注册状态变化回调"""
        self._state_callbacks.append(callback)
    
    def add_server(
        self, 
        config: MCPServerConfig, 
        source: str = "manual"
    ) -> bool:
        """添加服务器配置
        
        会检查黑白名单策略。
        
        Args:
            config: 服务器配置
            source: 配置来源标识
            
        Returns:
            是否成功添加（可能因策略被拒绝）
        """
        # 检查策略
        if not self._policy.is_server_allowed(config.name):
            logger.warning(f"服务器 {config.name} 被策略拒绝")
            return False
        
        # 应用默认超时
        if config.timeout == 30:  # 默认值
            config.timeout = self._policy.timeout
        
        self._configs[config.name] = config
        self._sources[config.name] = source
        self._client.add_server(config)
        logger.debug(f"添加 MCP 服务器: {config.name} (来源: {source})")
        return True
    
    def remove_server(self, name: str) -> bool:
        """移除服务器配置"""
        if name in self._configs:
            del self._configs[name]
            self._sources.pop(name, None)
            result = self._client.remove_server(name)
            logger.debug(f"移除 MCP 服务器: {name}")
            return result
        return False
    
    def get_server_config(self, name: str) -> Optional[MCPServerConfig]:
        """获取服务器配置"""
        return self._configs.get(name)
    
    def list_servers(self) -> List[str]:
        """列出所有服务器名称"""
        return list(self._configs.keys())
    
    def list_enabled_servers(self) -> List[str]:
        """列出所有启用的服务器名称"""
        return [
            name for name, config in self._configs.items()
            if not config.disabled
        ]
    
    def get_connection_state(self, name: str) -> MCPConnectionState:
        """获取服务器连接状态"""
        return self._client.get_connection_state(name)
    
    async def connect(self, name: str) -> bool:
        """连接到指定服务器"""
        if name not in self._configs:
            logger.error(f"服务器配置不存在: {name}")
            return False
        return await self._client.connect(name)
    
    async def disconnect(self, name: str) -> bool:
        """断开与指定服务器的连接"""
        return await self._client.disconnect(name)
    
    async def connect_all(self, only_enabled: bool = True) -> Dict[str, bool]:
        """连接所有服务器"""
        results = {}
        servers = self.list_enabled_servers() if only_enabled else self.list_servers()
        for name in servers:
            results[name] = await self.connect(name)
        return results
    
    async def disconnect_all(self) -> None:
        """断开所有连接"""
        await self._client.disconnect_all()
    
    async def get_server_status(self, name: str) -> Optional[MCPServerStatus]:
        """获取服务器状态"""
        if name not in self._configs:
            return None
        
        state = self.get_connection_state(name)
        status = MCPServerStatus(
            name=name, 
            state=state,
            source=self._sources.get(name, "unknown")
        )
        
        if state == MCPConnectionState.CONNECTED:
            try:
                tools = await self._client.list_tools(name)
                status.tools_count = len(tools)
            except Exception as e:
                status.error = f"获取工具列表失败: {e}"
            
            try:
                resources = await self._client.list_resources(name)
                status.resources_count = len(resources)
            except Exception:
                pass
            
            try:
                prompts = await self._client.list_prompts(name)
                status.prompts_count = len(prompts)
            except Exception:
                pass
        
        return status
    
    async def get_all_server_status(self) -> List[MCPServerStatus]:
        """获取所有服务器状态"""
        statuses = []
        for name in self._configs:
            status = await self.get_server_status(name)
            if status:
                statuses.append(status)
        return statuses
    
    async def discover_servers(self, search_paths: Optional[List[Path]] = None) -> int:
        """发现 MCP 服务器
        
        从指定路径中搜索 MCP 服务器配置文件。
        
        支持的配置文件格式:
        - mcp.json: 标准 MCP 配置格式
        - package.json: 包含 mcp 字段的 npm 包
        
        Args:
            search_paths: 搜索路径列表，默认 ["~/.mcp-servers", "./mcp-servers"]
        
        Returns:
            发现并加载的服务器数量
        """
        if search_paths is None:
            search_paths = [
                Path.home() / ".mcp-servers",
                Path("./mcp-servers"),
            ]
        
        total_count = 0
        discovered_files: Set[str] = set()
        
        for search_path in search_paths:
            if not search_path.exists():
                continue
            
            # 搜索 mcp.json 文件
            for config_file in search_path.rglob("mcp.json"):
                file_str = str(config_file.resolve())
                if file_str in discovered_files:
                    continue
                
                try:
                    count = self._load_config_file(config_file)
                    total_count += count
                    discovered_files.add(file_str)
                except Exception as e:
                    logger.error(f"加载配置失败 {config_file}: {e}")
            
            # 搜索 package.json（可能包含 mcp 配置）
            for pkg_file in search_path.rglob("package.json"):
                file_str = str(pkg_file.resolve())
                if file_str in discovered_files:
                    continue
                
                try:
                    count = self._load_package_json(pkg_file)
                    total_count += count
                    discovered_files.add(file_str)
                except Exception as e:
                    logger.debug(f"跳过 package.json {pkg_file}: {e}")
        
        logger.info(f"发现 {total_count} 个 MCP 服务器")
        return total_count
    
    def _load_config_file(self, config_path: Path) -> int:
        """从 mcp.json 加载配置"""
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        servers_data = data.get("mcpServers", {})
        count = 0
        
        for name, server_data in servers_data.items():
            try:
                config = MCPServerConfig.from_dict(name, server_data)
                if self.add_server(config, source=str(config_path)):
                    count += 1
            except Exception as e:
                logger.error(f"加载服务器配置失败 {name}: {e}")
        
        return count
    
    def _load_package_json(self, pkg_path: Path) -> int:
        """从 package.json 加载 MCP 配置"""
        with open(pkg_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 检查是否有 mcp 字段
        mcp_data = data.get("mcp")
        if not mcp_data:
            return 0
        
        # 如果是 MCP 服务器包，自动创建配置
        if "bin" in data and data.get("name", "").startswith("mcp-server-"):
            name = data["name"].replace("mcp-server-", "")
            config = MCPServerConfig(
                name=name,
                command="npx",
                args=[data["name"]],
                timeout=self._policy.timeout
            )
            if self.add_server(config, source=str(pkg_path)):
                return 1
        
        return 0
    
    def is_server_connected(self, name: str) -> bool:
        """检查服务器是否已连接"""
        return self.get_connection_state(name) == MCPConnectionState.CONNECTED
    
    def get_connected_servers(self) -> List[str]:
        """获取所有已连接的服务器名称"""
        return [
            name for name in self._configs
            if self.is_server_connected(name)
        ]
    
    def to_dict(self) -> Dict[str, Any]:
        """导出配置为字典"""
        servers = {}
        for name, config in self._configs.items():
            servers[name] = {
                "command": config.command,
                "args": config.args,
                "env": config.env or {},
                "disabled": config.disabled,
                "autoApprove": config.auto_approve,
                "timeout": config.timeout,
            }
        return {"mcpServers": servers}
