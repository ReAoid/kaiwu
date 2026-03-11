"""工具注册表模块

管理工具的注册、扫描和查找。
"""

import importlib
import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.tool import Tool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册表
    
    管理工具的注册和查找，支持自动扫描目录加载工具。
    """
    
    def __init__(self):
        """初始化工具注册表"""
        self.tools: Dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        """注册单个工具
        
        Args:
            tool: 工具实例
        """
        self.tools[tool.name] = tool
        logger.debug(f"已注册工具: {tool.name}")
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """获取工具
        
        Args:
            name: 工具名称
            
        Returns:
            工具实例，不存在则返回 None
        """
        return self.tools.get(name)
    
    def get_all_tools(self) -> List[Tool]:
        """获取所有工具
        
        Returns:
            所有已注册工具的列表
        """
        return list(self.tools.values())
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """获取 OpenAI function calling 格式的工具列表
        
        Returns:
            符合 OpenAI function calling 格式的工具定义列表
        """
        return [tool.to_openai_function() for tool in self.tools.values()]
    
    def scan_and_register(self, tools_dir: Path) -> None:
        """扫描目录并注册所有工具
        
        扫描指定目录下的所有 Python 文件，查找 Tool 子类并实例化注册。
        
        Args:
            tools_dir: 工具目录路径
        """
        if not tools_dir.exists():
            logger.warning(f"工具目录不存在: {tools_dir}")
            return
        
        if not tools_dir.is_dir():
            logger.warning(f"路径不是目录: {tools_dir}")
            return
        
        for py_file in tools_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            
            try:
                self._load_tools_from_file(py_file)
            except Exception as e:
                logger.error(f"加载工具文件失败 {py_file}: {e}")
    
    def _load_tools_from_file(self, py_file: Path) -> None:
        """从 Python 文件加载工具
        
        Args:
            py_file: Python 文件路径
        """
        module_name = py_file.stem
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        
        if spec is None or spec.loader is None:
            logger.warning(f"无法加载模块: {py_file}")
            return
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # 查找所有 Tool 子类
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Tool) and obj is not Tool:
                try:
                    tool_instance = obj()
                    self.register(tool_instance)
                except Exception as e:
                    logger.error(f"实例化工具失败 {name}: {e}")
