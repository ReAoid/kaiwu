"""工具抽象基类模块

定义工具的抽象接口和参数模型。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ToolParameter(BaseModel):
    """工具参数定义
    
    Attributes:
        name: 参数名称
        type: 参数类型 (string, integer, boolean, array, object)
        description: 参数描述
        required: 是否必需
        default: 默认值
    """
    
    name: str
    type: str
    description: str
    required: bool = True
    default: Optional[Any] = None


class Tool(ABC):
    """工具抽象基类
    
    定义工具的标准接口，支持转换为 OpenAI function calling 格式。
    """
    
    def __init__(self, name: str, description: str):
        """初始化工具
        
        Args:
            name: 工具名称
            description: 工具描述
        """
        self.name = name
        self.description = description
    
    @abstractmethod
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行工具
        
        Args:
            parameters: 工具参数字典
            
        Returns:
            执行结果字符串
        """
        pass
    
    @abstractmethod
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义
        
        Returns:
            参数定义列表
        """
        pass
    
    def to_openai_function(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式
        
        Returns:
            符合 OpenAI function calling 格式的字典
        """
        params = self.get_parameters()
        properties: Dict[str, Any] = {}
        required: List[str] = []
        
        for p in params:
            properties[p.name] = {
                "type": p.type,
                "description": p.description
            }
            if p.required:
                required.append(p.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }
