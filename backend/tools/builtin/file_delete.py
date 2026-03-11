"""文件删除工具

删除指定路径的文件。
"""

from pathlib import Path
from typing import Any, Dict, List

from core.tool import Tool, ToolParameter


class FileDeleteTool(Tool):
    """删除文件工具
    
    删除指定路径的文件。
    """
    
    def __init__(self):
        super().__init__(
            name="file_delete",
            description="删除指定路径的文件"
        )
    
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义"""
        return [
            ToolParameter(
                name="path",
                type="string",
                description="文件路径",
                required=True
            )
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行文件删除
        
        Args:
            parameters: 包含 path 的参数字典
            
        Returns:
            成功信息或错误信息
        """
        path_str = parameters.get("path")
        if not path_str:
            return "错误: 缺少 path 参数"
        
        path = Path(path_str)
        
        if not path.exists():
            return f"文件不存在: {path}"
        
        if not path.is_file():
            return f"错误: 路径不是文件 - {path}"
        
        try:
            path.unlink()
            return f"文件已删除: {path}"
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 删除文件失败 - {e}"
