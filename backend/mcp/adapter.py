"""MCP 工具适配器模块

将 MCP 工具转换为本地 Tool 接口，支持通过统一的工具注册表调用。

主要功能:
- MCPToolAdapter: 将单个 MCP 工具包装为 Tool 实例
- MCPToolRegistry: 管理 MCP 工具的发现、注册和调用
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from core.tool import Tool, ToolParameter
from mcp.client import MCPClient, MCPToolInfo, MCPServerConfig

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class MCPToolAdapter(Tool):
    """MCP 工具适配器
    
    将 MCP 工具包装为本地 Tool 接口，使其可以通过统一的工具注册表调用。
    
    特点:
    - 实现 Tool 抽象基类接口
    - 支持同步和异步调用
    - 自动处理参数转换
    - 保留 MCP 工具的完整 schema
    
    使用示例:
    ```python
    # 从 MCPToolInfo 创建适配器
    tool_info = MCPToolInfo(
        name="read_file",
        description="Read file content",
        input_schema={"type": "object", "properties": {...}},
        server_name="filesystem"
    )
    client = MCPClient()
    adapter = MCPToolAdapter(tool_info, client)
    
    # 调用工具
    result = adapter.run({"path": "/tmp/test.txt"})
    ```
    """
    
    def __init__(
        self, 
        tool_info: MCPToolInfo, 
        client: MCPClient,
        name_prefix: bool = True
    ):
        """初始化 MCP 工具适配器
        
        Args:
            tool_info: MCP 工具信息
            client: MCP 客户端实例
            name_prefix: 是否在工具名称前添加服务器名称前缀
        """
        # 构建工具名称（可选添加服务器前缀）
        if name_prefix:
            tool_name = f"{tool_info.server_name}.{tool_info.name}"
        else:
            tool_name = tool_info.name
        
        super().__init__(
            name=tool_name,
            description=tool_info.description or f"MCP tool: {tool_info.name}"
        )
        
        self._tool_info = tool_info
        self._client = client
        self._server_name = tool_info.server_name
        self._original_name = tool_info.name
        self._input_schema = tool_info.input_schema
        self._parameters: Optional[List[ToolParameter]] = None
    
    @property
    def server_name(self) -> str:
        """获取 MCP 服务器名称"""
        return self._server_name
    
    @property
    def original_name(self) -> str:
        """获取原始工具名称（不含服务器前缀）"""
        return self._original_name
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        """获取原始输入 schema"""
        return self._input_schema
    
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义
        
        从 MCP 工具的 input_schema 解析参数定义。
        
        Returns:
            参数定义列表
        """
        if self._parameters is not None:
            return self._parameters
        
        self._parameters = []
        
        # 解析 JSON Schema 格式的 input_schema
        properties = self._input_schema.get("properties", {})
        required = set(self._input_schema.get("required", []))
        
        for param_name, param_schema in properties.items():
            param_type = param_schema.get("type", "string")
            param_desc = param_schema.get("description", "")
            param_default = param_schema.get("default")
            
            self._parameters.append(ToolParameter(
                name=param_name,
                type=param_type,
                description=param_desc,
                required=param_name in required,
                default=param_default
            ))
        
        return self._parameters
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """同步执行工具
        
        通过事件循环调用异步方法。
        
        Args:
            parameters: 工具参数字典
            
        Returns:
            执行结果字符串
        """
        try:
            # 尝试获取当前事件循环
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环正在运行，创建新任务
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run, 
                        self.arun(parameters)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(self.arun(parameters))
        except RuntimeError:
            # 没有事件循环，创建新的
            return asyncio.run(self.arun(parameters))
    
    async def arun(self, parameters: Dict[str, Any]) -> str:
        """异步执行工具
        
        Args:
            parameters: 工具参数字典
            
        Returns:
            执行结果字符串
        """
        try:
            result = await self._client.call_tool(
                self._server_name,
                self._original_name,
                parameters
            )
            
            # 处理结果
            if isinstance(result, dict):
                if "result" in result:
                    result_value = result["result"]
                    if isinstance(result_value, str):
                        return result_value
                    return json.dumps(result_value, ensure_ascii=False, indent=2)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            return str(result)
            
        except ValueError as e:
            return f"错误: {e}"
        except RuntimeError as e:
            return f"MCP 工具调用失败: {e}"
        except Exception as e:
            logger.error(f"MCP 工具 {self.name} 执行失败: {e}")
            return f"执行失败: {e}"
    
    def to_openai_function(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式
        
        直接使用 MCP 工具的 input_schema，保留完整的参数定义。
        
        Returns:
            符合 OpenAI function calling 格式的字典
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._input_schema
            }
        }


class MCPToolRegistry:
    """MCP 工具注册表
    
    管理 MCP 工具的发现、注册和调用，支持与本地 ToolRegistry 集成。
    
    主要功能:
    - 从 MCP 服务器发现工具
    - 将 MCP 工具转换为 Tool 实例
    - 注册到本地 ToolRegistry
    - 支持工具刷新和重新发现
    
    使用示例:
    ```python
    # 创建 MCP 客户端和工具注册表
    client = MCPClient()
    mcp_registry = MCPToolRegistry(client)
    
    # 添加服务器配置
    config = MCPServerConfig(name="filesystem", command="uvx", args=["mcp-server-filesystem"])
    client.add_server(config)
    
    # 连接并发现工具
    await client.connect("filesystem")
    await mcp_registry.discover_tools("filesystem")
    
    # 获取所有 MCP 工具
    tools = mcp_registry.get_all_tools()
    
    # 集成到本地 ToolRegistry
    local_registry = ToolRegistry()
    mcp_registry.register_to_local(local_registry)
    ```
    """
    
    def __init__(self, client: MCPClient, name_prefix: bool = True):
        """初始化 MCP 工具注册表
        
        Args:
            client: MCP 客户端实例
            name_prefix: 是否在工具名称前添加服务器名称前缀
        """
        self._client = client
        self._name_prefix = name_prefix
        self._tools: Dict[str, MCPToolAdapter] = {}
        self._tools_by_server: Dict[str, List[str]] = {}
    
    @property
    def client(self) -> MCPClient:
        """获取 MCP 客户端"""
        return self._client
    
    async def discover_tools(self, server_name: Optional[str] = None) -> List[MCPToolAdapter]:
        """发现并注册 MCP 工具
        
        从指定服务器或所有已连接服务器发现工具。
        
        Args:
            server_name: 服务器名称，None 则发现所有服务器的工具
            
        Returns:
            新发现的工具适配器列表
        """
        discovered = []
        
        # 获取工具信息
        tool_infos = await self._client.list_tools(server_name)
        
        for tool_info in tool_infos:
            adapter = MCPToolAdapter(
                tool_info=tool_info,
                client=self._client,
                name_prefix=self._name_prefix
            )
            
            # 注册工具
            self._tools[adapter.name] = adapter
            
            # 按服务器分组
            if tool_info.server_name not in self._tools_by_server:
                self._tools_by_server[tool_info.server_name] = []
            if adapter.name not in self._tools_by_server[tool_info.server_name]:
                self._tools_by_server[tool_info.server_name].append(adapter.name)
            
            discovered.append(adapter)
            logger.debug(f"发现 MCP 工具: {adapter.name}")
        
        logger.info(f"发现 {len(discovered)} 个 MCP 工具")
        return discovered
    
    async def refresh_tools(self, server_name: Optional[str] = None) -> List[MCPToolAdapter]:
        """刷新 MCP 工具
        
        清除指定服务器的工具缓存并重新发现。
        
        Args:
            server_name: 服务器名称，None 则刷新所有服务器
            
        Returns:
            刷新后的工具适配器列表
        """
        # 清除旧工具
        if server_name:
            if server_name in self._tools_by_server:
                for tool_name in self._tools_by_server[server_name]:
                    self._tools.pop(tool_name, None)
                self._tools_by_server[server_name] = []
        else:
            self._tools.clear()
            self._tools_by_server.clear()
        
        # 重新发现
        return await self.discover_tools(server_name)
    
    def get_tool(self, name: str) -> Optional[MCPToolAdapter]:
        """获取 MCP 工具
        
        Args:
            name: 工具名称
            
        Returns:
            工具适配器，不存在则返回 None
        """
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[MCPToolAdapter]:
        """获取所有 MCP 工具
        
        Returns:
            所有已注册的工具适配器列表
        """
        return list(self._tools.values())
    
    def get_tools_by_server(self, server_name: str) -> List[MCPToolAdapter]:
        """获取指定服务器的工具
        
        Args:
            server_name: 服务器名称
            
        Returns:
            该服务器的工具适配器列表
        """
        tool_names = self._tools_by_server.get(server_name, [])
        return [self._tools[name] for name in tool_names if name in self._tools]
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """获取 OpenAI function calling 格式的工具列表
        
        Returns:
            符合 OpenAI function calling 格式的工具定义列表
        """
        return [tool.to_openai_function() for tool in self._tools.values()]
    
    def register_to_local(
        self, 
        local_registry: "ToolRegistry",
        server_name: Optional[str] = None
    ) -> int:
        """将 MCP 工具注册到本地 ToolRegistry
        
        Args:
            local_registry: 本地工具注册表
            server_name: 服务器名称，None 则注册所有工具
            
        Returns:
            注册的工具数量
        """
        from tools.registry import PluginInfo
        from pathlib import Path
        
        count = 0
        tools = (
            self.get_tools_by_server(server_name) 
            if server_name 
            else self.get_all_tools()
        )
        
        for tool in tools:
            # 创建插件信息
            plugin_info = PluginInfo(
                name=tool.name,
                source_file=Path(__file__),
                source_dir=Path(__file__).parent,
                module_name="mcp.adapter",
                class_name="MCPToolAdapter",
                version="1.0.0",
                is_builtin=False
            )
            
            local_registry.register(tool, plugin_info)
            count += 1
            logger.debug(f"已注册 MCP 工具到本地: {tool.name}")
        
        logger.info(f"已注册 {count} 个 MCP 工具到本地注册表")
        return count
    
    def unregister_from_local(
        self, 
        local_registry: "ToolRegistry",
        server_name: Optional[str] = None
    ) -> int:
        """从本地 ToolRegistry 注销 MCP 工具
        
        Args:
            local_registry: 本地工具注册表
            server_name: 服务器名称，None 则注销所有工具
            
        Returns:
            注销的工具数量
        """
        count = 0
        tools = (
            self.get_tools_by_server(server_name) 
            if server_name 
            else self.get_all_tools()
        )
        
        for tool in tools:
            if local_registry.unregister(tool.name):
                count += 1
                logger.debug(f"已从本地注销 MCP 工具: {tool.name}")
        
        logger.info(f"已从本地注销 {count} 个 MCP 工具")
        return count
