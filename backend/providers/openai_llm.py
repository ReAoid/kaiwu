"""OpenAI 兼容 LLM 实现模块

实现与 OpenAI API 兼容的 LLM 服务，支持同步/异步和流式/非流式生成，
以及工具调用功能。
"""

import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletionMessageToolCall

from core.llm import Llm
from core.message import Message


@dataclass
class ToolCallResult:
    """工具调用结果
    
    Attributes:
        tool_calls: 工具调用列表
        content: 响应文本内容
        is_tool_call: 是否为工具调用响应
    """
    tool_calls: List[ChatCompletionMessageToolCall] = field(default_factory=list)
    content: str = ""
    is_tool_call: bool = False


class OpenaiLlm(Llm):
    """OpenAI 兼容 LLM 实现
    
    支持 OpenAI API 及兼容接口（如阿里云 DashScope）。
    """
    
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: int = 60
    ):
        """初始化 OpenAI LLM
        
        Args:
            model: 模型名称
            api_key: API 密钥
            base_url: API 基础 URL（可选，用于兼容接口）
            timeout: 请求超时时间（秒）
        """
        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout
        )
        self.async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout
        )

    def _messages_to_openai_format(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """将消息列表转换为 OpenAI API 格式
        
        Args:
            messages: 消息列表
            
        Returns:
            OpenAI API 格式的消息列表
        """
        return [msg.to_openai_format() for msg in messages]
    
    def generate(self, messages: List[Message], **kwargs) -> Message:
        """同步生成响应
        
        Args:
            messages: 对话消息列表
            **kwargs: 额外参数 (如 temperature, max_tokens 等)
            
        Returns:
            生成的响应消息
        """
        openai_messages = self._messages_to_openai_format(messages)
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            **kwargs
        )
        
        content = response.choices[0].message.content or ""
        return Message(role="assistant", content=content)
    
    async def agenerate(self, messages: List[Message], **kwargs) -> Message:
        """异步生成响应
        
        Args:
            messages: 对话消息列表
            **kwargs: 额外参数
            
        Returns:
            生成的响应消息
        """
        openai_messages = self._messages_to_openai_format(messages)
        
        response = await self.async_client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            **kwargs
        )
        
        content = response.choices[0].message.content or ""
        return Message(role="assistant", content=content)
    
    def stream(self, messages: List[Message], **kwargs) -> Generator[str, None, None]:
        """同步流式生成
        
        Args:
            messages: 对话消息列表
            **kwargs: 额外参数
            
        Yields:
            响应文本片段
        """
        openai_messages = self._messages_to_openai_format(messages)
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            stream=True,
            **kwargs
        )
        
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    async def astream(self, messages: List[Message], **kwargs) -> AsyncGenerator[str, None]:
        """异步流式生成
        
        Args:
            messages: 对话消息列表
            **kwargs: 额外参数
            
        Yields:
            响应文本片段
        """
        openai_messages = self._messages_to_openai_format(messages)
        
        response = await self.async_client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            stream=True,
            **kwargs
        )
        
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def generate_with_tools(
        self,
        messages: List[Message],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto"
    ) -> ToolCallResult:
        """带工具的同步生成
        
        Args:
            messages: 对话消息列表
            tools: OpenAI function calling 格式的工具列表
            tool_choice: 工具选择策略 ("auto", "none", "required")
            
        Returns:
            ToolCallResult 包含工具调用信息或文本响应
        """
        openai_messages = self._messages_to_openai_format(messages)
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            tools=tools if tools else None,
            tool_choice=tool_choice if tools else None
        )
        
        message = response.choices[0].message
        
        if message.tool_calls:
            return ToolCallResult(
                tool_calls=list(message.tool_calls),
                content=message.content or "",
                is_tool_call=True
            )
        
        return ToolCallResult(
            tool_calls=[],
            content=message.content or "",
            is_tool_call=False
        )
    
    async def agenerate_with_tools(
        self,
        messages: List[Message],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto"
    ) -> ToolCallResult:
        """带工具的异步生成
        
        Args:
            messages: 对话消息列表
            tools: OpenAI function calling 格式的工具列表
            tool_choice: 工具选择策略 ("auto", "none", "required")
            
        Returns:
            ToolCallResult 包含工具调用信息或文本响应
        """
        openai_messages = self._messages_to_openai_format(messages)
        
        response = await self.async_client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            tools=tools if tools else None,
            tool_choice=tool_choice if tools else None
        )
        
        message = response.choices[0].message
        
        if message.tool_calls:
            return ToolCallResult(
                tool_calls=list(message.tool_calls),
                content=message.content or "",
                is_tool_call=True
            )
        
        return ToolCallResult(
            tool_calls=[],
            content=message.content or "",
            is_tool_call=False
        )
