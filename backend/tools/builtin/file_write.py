"""文件写入工具

写入内容到指定路径的文件。
"""

from pathlib import Path
from typing import Any, Dict, List

from core.tool import Tool, ToolParameter


class FileWriteTool(Tool):
    """写入文件内容工具
    
    支持写入内容到指定路径的文件，自动创建父目录。
    """
    
    def __init__(self):
        super().__init__(
            name="file_write",
            description="写入内容到指定路径的文件"
        )
    
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义"""
        return [
            ToolParameter(
                name="path",
                type="string",
                description="文件路径",
                required=True
            ),
            ToolParameter(
                name="content",
                type="string",
                description="文件内容",
                required=True
            ),
            ToolParameter(
                name="encoding",
                type="string",
                description="文件编码，默认 utf-8",
                required=False,
                default="utf-8"
            )
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行文件写入
        
        Args:
            parameters: 包含 path, content 和可选 encoding 的参数字典
            
        Returns:
            成功信息或错误信息
        """
        path_str = parameters.get("path")
        if not path_str:
            return "错误: 缺少 path 参数"
        
        content = parameters.get("content")
        if content is None:
            return "错误: 缺少 content 参数"
        
        encoding = parameters.get("encoding", "utf-8")
        path = Path(path_str)
        
        try:
            # 自动创建父目录
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
            return f"文件已写入: {path}"
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 写入文件失败 - {e}"
