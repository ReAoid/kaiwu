"""文件读取工具

读取指定路径的文件内容。
"""

from pathlib import Path
from typing import Any, Dict, List

from core.tool import Tool, ToolParameter


class FileReadTool(Tool):
    """读取文件内容工具
    
    支持读取指定路径的文件，可配置编码格式。
    """
    
    def __init__(self):
        super().__init__(
            name="file_read",
            description="读取指定路径的文件内容"
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
                name="encoding",
                type="string",
                description="文件编码，默认 utf-8",
                required=False,
                default="utf-8"
            )
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行文件读取
        
        Args:
            parameters: 包含 path 和可选 encoding 的参数字典
            
        Returns:
            文件内容或错误信息
        """
        path_str = parameters.get("path")
        if not path_str:
            return "错误: 缺少 path 参数"
        
        encoding = parameters.get("encoding", "utf-8")
        path = Path(path_str)
        
        if not path.exists():
            return f"错误: 文件不存在 - {path}"
        
        if not path.is_file():
            return f"错误: 路径不是文件 - {path}"
        
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as e:
            return f"错误: 编码错误 - {e}"
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 读取文件失败 - {e}"
