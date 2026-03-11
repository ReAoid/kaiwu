"""消息模型模块

定义对话消息的数据结构和类型。
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# 消息角色类型
MessageRole = Literal["user", "assistant", "system", "tool"]


class Message(BaseModel):
    """对话消息模型
    
    Attributes:
        content: 消息内容
        role: 消息角色 (user, assistant, system, tool)
        timestamp: 消息时间戳
        metadata: 额外元数据
        tool_call_id: 工具消息的调用 ID (用于 tool 角色)
        tool_calls: assistant 消息的工具调用列表
    """
    
    content: str
    role: MessageRole
    timestamp: Optional[datetime] = Field(default_factory=datetime.now)
    metadata: Optional[Dict[str, Any]] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI API 格式
        
        Returns:
            符合 OpenAI Chat Completion API 格式的字典
        """
        result: Dict[str, Any] = {
            "role": self.role,
            "content": self.content
        }
        
        # tool 消息需要 tool_call_id
        if self.role == "tool" and self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        
        # assistant 消息可能包含 tool_calls
        if self.role == "assistant" and self.tool_calls:
            result["tool_calls"] = self.tool_calls
            # 当有 tool_calls 时，content 可以为空字符串
            if not self.content:
                result["content"] = ""
        
        return result
