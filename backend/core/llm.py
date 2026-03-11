"""LLM 抽象基类模块

定义 LLM 服务的抽象接口。
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Generator, List

from .message import Message


class Llm(ABC):
    """LLM 抽象基类
    
    定义与大语言模型交互的标准接口，支持同步/异步和流式/非流式生成。
    """
    
    @abstractmethod
    def generate(self, messages: List[Message], **kwargs) -> Message:
        """同步生成响应
        
        Args:
            messages: 对话消息列表
            **kwargs: 额外参数 (如 temperature, max_tokens 等)
            
        Returns:
            生成的响应消息
        """
        pass
    
    @abstractmethod
    async def agenerate(self, messages: List[Message], **kwargs) -> Message:
        """异步生成响应
        
        Args:
            messages: 对话消息列表
            **kwargs: 额外参数
            
        Returns:
            生成的响应消息
        """
        pass
    
    @abstractmethod
    def stream(self, messages: List[Message], **kwargs) -> Generator[str, None, None]:
        """同步流式生成
        
        Args:
            messages: 对话消息列表
            **kwargs: 额外参数
            
        Yields:
            响应文本片段
        """
        pass
    
    @abstractmethod
    async def astream(self, messages: List[Message], **kwargs) -> AsyncGenerator[str, None]:
        """异步流式生成
        
        Args:
            messages: 对话消息列表
            **kwargs: 额外参数
            
        Yields:
            响应文本片段
        """
        pass
