"""MCP 客户端模块

实现 MCP (Model Context Protocol) 客户端，支持连接 MCP 服务器并调用其工具。
参考: https://modelcontextprotocol.io/docs/tutorials/building-a-client/

主要功能:
- 支持 stdio 传输方式连接 MCP 服务器
- 支持工具发现和调用
- 支持资源读取
- 支持提示词获取
- 连接状态管理和重连机制
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


class MCPConnectionState(Enum):
    """MCP 连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class MCPServerConfig:
    """MCP 服务器配置
    
    Attributes:
        name: 服务器名称（唯一标识）
        command: 启动命令（如 "python", "node", "uvx"）
        args: 命令参数列表
        env: 环境变量（可选）
        disabled: 是否禁用
        auto_approve: 自动批准的工具列表
        timeout: 连接超时时间（秒）
    """
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    disabled: bool = False
    auto_approve: List[str] = field(default_factory=list)
    timeout: int = 30
    
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MCPServerConfig":
        """从字典创建配置
        
        Args:
            name: 服务器名称
            data: 配置字典
            
        Returns:
            MCPServerConfig 实例
        """
        return cls(
            name=name,
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env"),
            disabled=data.get("disabled", False),
            auto_approve=data.get("autoApprove", []),
            timeout=data.get("timeout", 30),
        )


@dataclass
class MCPToolInfo:
    """MCP 工具信息
    
    Attributes:
        name: 工具名称
        description: 工具描述
        input_schema: 输入参数 schema
        server_name: 所属服务器名称
    """
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str


@dataclass
class MCPResourceInfo:
    """MCP 资源信息
    
    Attributes:
        uri: 资源 URI
        name: 资源名称
        description: 资源描述
        mime_type: MIME 类型
        server_name: 所属服务器名称
    """
    uri: str
    name: str
    description: Optional[str]
    mime_type: Optional[str]
    server_name: str


@dataclass
class MCPPromptInfo:
    """MCP 提示词信息
    
    Attributes:
        name: 提示词名称
        description: 提示词描述
        arguments: 参数列表
        server_name: 所属服务器名称
    """
    name: str
    description: Optional[str]
    arguments: List[Dict[str, Any]]
    server_name: str


class MCPClient:
    """MCP 客户端
    
    支持连接 MCP 服务器，发现和调用工具、资源、提示词。
    
    使用示例:
    ```python
    client = MCPClient()
    
    # 添加服务器配置
    config = MCPServerConfig(
        name="filesystem",
        command="uvx",
        args=["mcp-server-filesystem", "--root", "."]
    )
    client.add_server(config)
    
    # 连接服务器
    await client.connect("filesystem")
    
    # 获取工具列表
    tools = await client.list_tools("filesystem")
    
    # 调用工具
    result = await client.call_tool("filesystem", "read_file", {"path": "test.txt"})
    
    # 断开连接
    await client.disconnect("filesystem")
    ```
    """
    
    def __init__(self):
        """初始化 MCP 客户端"""
        self._servers: Dict[str, MCPServerConfig] = {}
        self._connections: Dict[str, "_MCPConnection"] = {}
        self._state_callbacks: List[Callable[[str, MCPConnectionState], None]] = []
    
    def add_server(self, config: MCPServerConfig) -> None:
        """添加服务器配置
        
        Args:
            config: 服务器配置
        """
        self._servers[config.name] = config
        logger.debug(f"添加 MCP 服务器配置: {config.name}")
    
    def remove_server(self, name: str) -> bool:
        """移除服务器配置
        
        Args:
            name: 服务器名称
            
        Returns:
            是否成功移除
        """
        if name in self._servers:
            # 如果已连接，先断开
            if name in self._connections:
                asyncio.create_task(self.disconnect(name))
            del self._servers[name]
            logger.debug(f"移除 MCP 服务器配置: {name}")
            return True
        return False
    
    def get_server_config(self, name: str) -> Optional[MCPServerConfig]:
        """获取服务器配置
        
        Args:
            name: 服务器名称
            
        Returns:
            服务器配置，不存在则返回 None
        """
        return self._servers.get(name)
    
    def list_servers(self) -> List[str]:
        """列出所有服务器名称
        
        Returns:
            服务器名称列表
        """
        return list(self._servers.keys())
    
    def get_connection_state(self, name: str) -> MCPConnectionState:
        """获取服务器连接状态
        
        Args:
            name: 服务器名称
            
        Returns:
            连接状态
        """
        if name not in self._connections:
            return MCPConnectionState.DISCONNECTED
        return self._connections[name].state
    
    def on_state_change(self, callback: Callable[[str, MCPConnectionState], None]) -> None:
        """注册状态变化回调
        
        Args:
            callback: 回调函数，接收 (server_name, state) 参数
        """
        self._state_callbacks.append(callback)
    
    def _notify_state_change(self, name: str, state: MCPConnectionState) -> None:
        """通知状态变化
        
        Args:
            name: 服务器名称
            state: 新状态
        """
        for callback in self._state_callbacks:
            try:
                callback(name, state)
            except Exception as e:
                logger.error(f"状态变化回调执行失败: {e}")
    
    async def connect(self, name: str) -> bool:
        """连接到 MCP 服务器
        
        Args:
            name: 服务器名称
            
        Returns:
            是否成功连接
        """
        config = self._servers.get(name)
        if not config:
            logger.error(f"未找到服务器配置: {name}")
            return False
        
        if config.disabled:
            logger.warning(f"服务器已禁用: {name}")
            return False
        
        # 如果已连接，先断开
        if name in self._connections:
            await self.disconnect(name)
        
        self._notify_state_change(name, MCPConnectionState.CONNECTING)
        
        try:
            connection = _MCPConnection(config)
            await connection.connect()
            self._connections[name] = connection
            self._notify_state_change(name, MCPConnectionState.CONNECTED)
            logger.info(f"已连接到 MCP 服务器: {name}")
            return True
        except Exception as e:
            logger.error(f"连接 MCP 服务器失败 {name}: {e}")
            self._notify_state_change(name, MCPConnectionState.ERROR)
            return False
    
    async def disconnect(self, name: str) -> bool:
        """断开与 MCP 服务器的连接
        
        Args:
            name: 服务器名称
            
        Returns:
            是否成功断开
        """
        if name not in self._connections:
            return False
        
        try:
            await self._connections[name].disconnect()
            del self._connections[name]
            self._notify_state_change(name, MCPConnectionState.DISCONNECTED)
            logger.info(f"已断开 MCP 服务器: {name}")
            return True
        except Exception as e:
            logger.error(f"断开 MCP 服务器失败 {name}: {e}")
            return False
    
    async def connect_all(self) -> Dict[str, bool]:
        """连接所有已配置的服务器
        
        Returns:
            服务器名称到连接结果的映射
        """
        results = {}
        for name in self._servers:
            results[name] = await self.connect(name)
        return results
    
    async def disconnect_all(self) -> None:
        """断开所有连接"""
        for name in list(self._connections.keys()):
            await self.disconnect(name)
    
    async def list_tools(self, server_name: Optional[str] = None) -> List[MCPToolInfo]:
        """列出可用工具
        
        Args:
            server_name: 服务器名称，None 则列出所有服务器的工具
            
        Returns:
            工具信息列表
        """
        tools = []
        
        if server_name:
            if server_name not in self._connections:
                logger.warning(f"服务器未连接: {server_name}")
                return []
            server_tools = await self._connections[server_name].list_tools()
            tools.extend(server_tools)
        else:
            for name, conn in self._connections.items():
                try:
                    server_tools = await conn.list_tools()
                    tools.extend(server_tools)
                except Exception as e:
                    logger.error(f"获取服务器 {name} 工具列表失败: {e}")
        
        return tools
    
    async def call_tool(
        self, 
        server_name: str, 
        tool_name: str, 
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用工具
        
        Args:
            server_name: 服务器名称
            tool_name: 工具名称
            arguments: 工具参数
            
        Returns:
            工具执行结果
            
        Raises:
            ValueError: 服务器未连接
            RuntimeError: 工具调用失败
        """
        if server_name not in self._connections:
            raise ValueError(f"服务器未连接: {server_name}")
        
        return await self._connections[server_name].call_tool(tool_name, arguments)
    
    async def list_resources(self, server_name: Optional[str] = None) -> List[MCPResourceInfo]:
        """列出可用资源
        
        Args:
            server_name: 服务器名称，None 则列出所有服务器的资源
            
        Returns:
            资源信息列表
        """
        resources = []
        
        if server_name:
            if server_name not in self._connections:
                logger.warning(f"服务器未连接: {server_name}")
                return []
            server_resources = await self._connections[server_name].list_resources()
            resources.extend(server_resources)
        else:
            for name, conn in self._connections.items():
                try:
                    server_resources = await conn.list_resources()
                    resources.extend(server_resources)
                except Exception as e:
                    logger.error(f"获取服务器 {name} 资源列表失败: {e}")
        
        return resources
    
    async def read_resource(self, server_name: str, uri: str) -> Tuple[str, Optional[str]]:
        """读取资源
        
        Args:
            server_name: 服务器名称
            uri: 资源 URI
            
        Returns:
            (内容, MIME类型) 元组
            
        Raises:
            ValueError: 服务器未连接
        """
        if server_name not in self._connections:
            raise ValueError(f"服务器未连接: {server_name}")
        
        return await self._connections[server_name].read_resource(uri)
    
    async def list_prompts(self, server_name: Optional[str] = None) -> List[MCPPromptInfo]:
        """列出可用提示词
        
        Args:
            server_name: 服务器名称，None 则列出所有服务器的提示词
            
        Returns:
            提示词信息列表
        """
        prompts = []
        
        if server_name:
            if server_name not in self._connections:
                logger.warning(f"服务器未连接: {server_name}")
                return []
            server_prompts = await self._connections[server_name].list_prompts()
            prompts.extend(server_prompts)
        else:
            for name, conn in self._connections.items():
                try:
                    server_prompts = await conn.list_prompts()
                    prompts.extend(server_prompts)
                except Exception as e:
                    logger.error(f"获取服务器 {name} 提示词列表失败: {e}")
        
        return prompts
    
    async def get_prompt(
        self, 
        server_name: str, 
        prompt_name: str, 
        arguments: Optional[Dict[str, str]] = None
    ) -> str:
        """获取提示词内容
        
        Args:
            server_name: 服务器名称
            prompt_name: 提示词名称
            arguments: 提示词参数
            
        Returns:
            提示词内容
            
        Raises:
            ValueError: 服务器未连接
        """
        if server_name not in self._connections:
            raise ValueError(f"服务器未连接: {server_name}")
        
        return await self._connections[server_name].get_prompt(prompt_name, arguments)
    
    def get_tools_for_llm(self, server_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取 OpenAI function calling 格式的工具列表（同步版本）
        
        注意：此方法使用缓存的工具列表，需要先调用 list_tools() 更新缓存。
        
        Args:
            server_name: 服务器名称，None 则获取所有服务器的工具
            
        Returns:
            符合 OpenAI function calling 格式的工具定义列表
        """
        tools = []
        
        if server_name:
            if server_name in self._connections:
                tools.extend(self._connections[server_name].get_cached_tools_for_llm())
        else:
            for conn in self._connections.values():
                tools.extend(conn.get_cached_tools_for_llm())
        
        return tools


class _MCPConnection:
    """MCP 服务器连接
    
    管理与单个 MCP 服务器的连接，处理 JSON-RPC 通信。
    """
    
    def __init__(self, config: MCPServerConfig):
        """初始化连接
        
        Args:
            config: 服务器配置
        """
        self.config = config
        self.state = MCPConnectionState.DISCONNECTED
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._server_capabilities: Dict[str, Any] = {}
        self._cached_tools: List[MCPToolInfo] = []
        self._initialized = False
    
    async def connect(self) -> None:
        """建立连接"""
        self.state = MCPConnectionState.CONNECTING
        
        # 准备环境变量
        env = os.environ.copy()
        if self.config.env:
            for key, value in self.config.env.items():
                # 支持环境变量引用 ${VAR}
                if value.startswith("${") and value.endswith("}"):
                    var_name = value[2:-1]
                    env[key] = os.environ.get(var_name, "")
                else:
                    env[key] = value
        
        # 启动服务器进程
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.config.command,
                *self.config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            
            self._reader = self._process.stdout
            self._writer = self._process.stdin
            
            # 启动读取任务
            self._read_task = asyncio.create_task(self._read_loop())
            
            # 初始化连接
            await self._initialize()
            
            self.state = MCPConnectionState.CONNECTED
            logger.info(f"MCP 服务器 {self.config.name} 连接成功")
            
        except Exception as e:
            self.state = MCPConnectionState.ERROR
            await self._cleanup()
            raise RuntimeError(f"连接 MCP 服务器失败: {e}")
    
    async def disconnect(self) -> None:
        """断开连接"""
        await self._cleanup()
        self.state = MCPConnectionState.DISCONNECTED
    
    async def _cleanup(self) -> None:
        """清理资源"""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None
        
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            except Exception:
                pass
            self._process = None
        
        self._reader = None
        self._writer = None
        self._pending_requests.clear()
        self._initialized = False
    
    async def _initialize(self) -> None:
        """初始化 MCP 连接"""
        # 发送 initialize 请求
        result = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {"listChanged": True},
                "sampling": {},
            },
            "clientInfo": {
                "name": "kaiwu-mcp-client",
                "version": "1.0.0",
            },
        })
        
        self._server_capabilities = result.get("capabilities", {})
        
        # 发送 initialized 通知
        await self._send_notification("notifications/initialized", {})
        
        self._initialized = True
        logger.debug(f"MCP 服务器 {self.config.name} 初始化完成")
    
    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """发送 JSON-RPC 请求
        
        Args:
            method: 方法名
            params: 参数
            
        Returns:
            响应结果
        """
        self._request_id += 1
        request_id = self._request_id
        
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        
        # 创建 Future 等待响应
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future
        
        try:
            # 发送请求
            await self._write_message(request)
            
            # 等待响应
            result = await asyncio.wait_for(future, timeout=self.config.timeout)
            return result
            
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise RuntimeError(f"请求超时: {method}")
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            raise
    
    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """发送 JSON-RPC 通知（无响应）
        
        Args:
            method: 方法名
            params: 参数
        """
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._write_message(notification)
    
    async def _write_message(self, message: Dict[str, Any]) -> None:
        """写入消息
        
        Args:
            message: 消息字典
        """
        if not self._writer:
            raise RuntimeError("连接未建立")
        
        content = json.dumps(message)
        # MCP 使用 Content-Length 头部
        header = f"Content-Length: {len(content)}\r\n\r\n"
        
        self._writer.write(header.encode() + content.encode())
        await self._writer.drain()
    
    async def _read_loop(self) -> None:
        """读取循环"""
        try:
            while self._reader:
                message = await self._read_message()
                if message:
                    await self._handle_message(message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"MCP 读取循环错误: {e}")
            self.state = MCPConnectionState.ERROR
    
    async def _read_message(self) -> Optional[Dict[str, Any]]:
        """读取消息
        
        Returns:
            消息字典，读取失败返回 None
        """
        if not self._reader:
            return None
        
        try:
            # 读取头部
            headers = {}
            while True:
                line = await self._reader.readline()
                if not line:
                    return None
                line = line.decode().strip()
                if not line:
                    break
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            
            # 获取内容长度
            content_length = int(headers.get("content-length", 0))
            if content_length == 0:
                return None
            
            # 读取内容
            content = await self._reader.read(content_length)
            return json.loads(content.decode())
            
        except Exception as e:
            logger.error(f"读取 MCP 消息失败: {e}")
            return None
    
    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """处理消息
        
        Args:
            message: 消息字典
        """
        # 检查是否是响应
        if "id" in message and message["id"] in self._pending_requests:
            request_id = message["id"]
            future = self._pending_requests.pop(request_id)
            
            if "error" in message:
                error = message["error"]
                future.set_exception(RuntimeError(f"MCP 错误: {error.get('message', 'Unknown error')}"))
            else:
                future.set_result(message.get("result", {}))
        
        # 检查是否是通知
        elif "method" in message and "id" not in message:
            await self._handle_notification(message)
    
    async def _handle_notification(self, message: Dict[str, Any]) -> None:
        """处理通知
        
        Args:
            message: 通知消息
        """
        method = message.get("method", "")
        params = message.get("params", {})
        
        logger.debug(f"收到 MCP 通知: {method}")
        
        # 可以在这里处理各种通知
        # 例如: notifications/resources/list_changed, notifications/tools/list_changed
    
    async def list_tools(self) -> List[MCPToolInfo]:
        """列出工具
        
        Returns:
            工具信息列表
        """
        result = await self._send_request("tools/list", {})
        tools = []
        
        for tool_data in result.get("tools", []):
            tool = MCPToolInfo(
                name=tool_data.get("name", ""),
                description=tool_data.get("description", ""),
                input_schema=tool_data.get("inputSchema", {}),
                server_name=self.config.name,
            )
            tools.append(tool)
        
        # 缓存工具列表
        self._cached_tools = tools
        
        return tools
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用工具
        
        Args:
            name: 工具名称
            arguments: 工具参数
            
        Returns:
            工具执行结果
        """
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        
        # 处理结果
        content = result.get("content", [])
        if content:
            # 返回第一个内容块
            first_content = content[0]
            if first_content.get("type") == "text":
                return {"result": first_content.get("text", "")}
            elif first_content.get("type") == "image":
                return {
                    "result": first_content.get("data", ""),
                    "mime_type": first_content.get("mimeType", ""),
                }
        
        return {"result": result}
    
    async def list_resources(self) -> List[MCPResourceInfo]:
        """列出资源
        
        Returns:
            资源信息列表
        """
        result = await self._send_request("resources/list", {})
        resources = []
        
        for res_data in result.get("resources", []):
            resource = MCPResourceInfo(
                uri=res_data.get("uri", ""),
                name=res_data.get("name", ""),
                description=res_data.get("description"),
                mime_type=res_data.get("mimeType"),
                server_name=self.config.name,
            )
            resources.append(resource)
        
        return resources
    
    async def read_resource(self, uri: str) -> Tuple[str, Optional[str]]:
        """读取资源
        
        Args:
            uri: 资源 URI
            
        Returns:
            (内容, MIME类型) 元组
        """
        result = await self._send_request("resources/read", {"uri": uri})
        
        contents = result.get("contents", [])
        if contents:
            first_content = contents[0]
            text = first_content.get("text", "")
            mime_type = first_content.get("mimeType")
            return text, mime_type
        
        return "", None
    
    async def list_prompts(self) -> List[MCPPromptInfo]:
        """列出提示词
        
        Returns:
            提示词信息列表
        """
        result = await self._send_request("prompts/list", {})
        prompts = []
        
        for prompt_data in result.get("prompts", []):
            prompt = MCPPromptInfo(
                name=prompt_data.get("name", ""),
                description=prompt_data.get("description"),
                arguments=prompt_data.get("arguments", []),
                server_name=self.config.name,
            )
            prompts.append(prompt)
        
        return prompts
    
    async def get_prompt(self, name: str, arguments: Optional[Dict[str, str]] = None) -> str:
        """获取提示词内容
        
        Args:
            name: 提示词名称
            arguments: 提示词参数
            
        Returns:
            提示词内容
        """
        result = await self._send_request("prompts/get", {
            "name": name,
            "arguments": arguments or {},
        })
        
        messages = result.get("messages", [])
        if messages:
            # 合并所有消息内容
            contents = []
            for msg in messages:
                content = msg.get("content", {})
                if content.get("type") == "text":
                    contents.append(content.get("text", ""))
            return "\n".join(contents)
        
        return ""
    
    def get_cached_tools_for_llm(self) -> List[Dict[str, Any]]:
        """获取缓存的 OpenAI function calling 格式工具列表
        
        Returns:
            工具定义列表
        """
        tools = []
        for tool in self._cached_tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": f"{self.config.name}.{tool.name}",
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            })
        return tools
