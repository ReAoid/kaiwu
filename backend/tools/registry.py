"""工具注册表模块

管理工具的注册、扫描和查找，支持动态插件加载。
支持工具依赖检查功能。
"""

import importlib
import importlib.util
import inspect
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from core.tool import Tool

if TYPE_CHECKING:
    from tools.dependency_checker import ToolDependencyReport

logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """插件信息
    
    记录工具来源和元数据，用于管理动态加载的工具。
    
    Attributes:
        name: 工具名称
        source_file: 来源文件路径
        source_dir: 来源目录路径
        module_name: 模块名称
        class_name: 类名称
        version: 工具版本（如果定义）
        is_builtin: 是否为内置工具
        dependency_report: 依赖检查报告（如果进行了检查）
    """
    name: str
    source_file: Path
    source_dir: Path
    module_name: str
    class_name: str
    version: Optional[str] = None
    is_builtin: bool = False
    dependency_report: Optional["ToolDependencyReport"] = None


class ToolRegistry:
    """工具注册表
    
    管理工具的注册和查找，支持自动扫描目录加载工具。
    增强功能：
    - 多目录插件加载
    - 热重载支持
    - 工具来源追踪
    - 注册/注销事件回调
    - 工具依赖检查
    """
    
    def __init__(self, check_dependencies: bool = False):
        """初始化工具注册表
        
        Args:
            check_dependencies: 是否在注册时检查工具依赖
        """
        self.tools: Dict[str, Tool] = {}
        self._plugin_info: Dict[str, PluginInfo] = {}
        self._plugin_dirs: List[Path] = []
        self._loaded_modules: Dict[str, Any] = {}
        self._on_register_callbacks: List[Callable[[Tool, PluginInfo], None]] = []
        self._on_unregister_callbacks: List[Callable[[str, PluginInfo], None]] = []
        self._check_dependencies = check_dependencies
        self._dependency_reports: Dict[str, "ToolDependencyReport"] = {}
    
    def register(self, tool: Tool, plugin_info: Optional[PluginInfo] = None) -> None:
        """注册单个工具
        
        Args:
            tool: 工具实例
            plugin_info: 插件信息（可选）
        """
        self.tools[tool.name] = tool
        if plugin_info:
            self._plugin_info[tool.name] = plugin_info
        logger.debug(f"已注册工具: {tool.name}")
        
        # 触发注册回调
        for callback in self._on_register_callbacks:
            try:
                callback(tool, plugin_info)
            except Exception as e:
                logger.error(f"注册回调执行失败: {e}")
    
    def unregister(self, name: str) -> bool:
        """注销工具
        
        Args:
            name: 工具名称
            
        Returns:
            是否成功注销
        """
        if name not in self.tools:
            return False
        
        plugin_info = self._plugin_info.get(name)
        
        # 触发注销回调
        for callback in self._on_unregister_callbacks:
            try:
                callback(name, plugin_info)
            except Exception as e:
                logger.error(f"注销回调执行失败: {e}")
        
        del self.tools[name]
        if name in self._plugin_info:
            del self._plugin_info[name]
        
        logger.debug(f"已注销工具: {name}")
        return True
    
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
    
    def get_plugin_info(self, name: str) -> Optional[PluginInfo]:
        """获取工具的插件信息
        
        Args:
            name: 工具名称
            
        Returns:
            插件信息，不存在则返回 None
        """
        return self._plugin_info.get(name)
    
    def get_tools_by_source(self, source_dir: Path) -> List[str]:
        """获取指定目录加载的所有工具名称
        
        Args:
            source_dir: 来源目录
            
        Returns:
            工具名称列表
        """
        return [
            name for name, info in self._plugin_info.items()
            if info.source_dir == source_dir
        ]
    
    def check_tool_dependencies(self, tool_name: str) -> Optional["ToolDependencyReport"]:
        """检查指定工具的依赖
        
        Args:
            tool_name: 工具名称
            
        Returns:
            依赖检查报告，工具不存在或无依赖定义则返回 None
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return None
        
        # 检查工具是否定义了依赖
        dependencies = getattr(tool, 'get_dependencies', None)
        if not dependencies or not callable(dependencies):
            return None
        
        try:
            from tools.dependency_checker import DependencyChecker
            deps = dependencies()
            if not deps:
                return None
            
            report = DependencyChecker.check_tool(tool_name, deps)
            self._dependency_reports[tool_name] = report
            
            # 更新插件信息中的依赖报告
            if tool_name in self._plugin_info:
                self._plugin_info[tool_name].dependency_report = report
            
            return report
        except Exception as e:
            logger.error(f"检查工具 {tool_name} 依赖失败: {e}")
            return None
    
    def check_all_dependencies(self) -> Dict[str, "ToolDependencyReport"]:
        """检查所有已注册工具的依赖
        
        Returns:
            工具名称到依赖检查报告的映射
        """
        reports = {}
        for tool_name in self.tools:
            report = self.check_tool_dependencies(tool_name)
            if report:
                reports[tool_name] = report
        return reports
    
    def get_dependency_report(self, tool_name: str) -> Optional["ToolDependencyReport"]:
        """获取工具的依赖检查报告（已缓存的）
        
        Args:
            tool_name: 工具名称
            
        Returns:
            依赖检查报告，不存在则返回 None
        """
        return self._dependency_reports.get(tool_name)
    
    def get_tools_with_missing_dependencies(self) -> List[str]:
        """获取有缺失必需依赖的工具列表
        
        Returns:
            工具名称列表
        """
        missing = []
        for tool_name, report in self._dependency_reports.items():
            if not report.required_satisfied:
                missing.append(tool_name)
        return missing
    
    def get_dependency_summary(self) -> str:
        """获取所有工具依赖的摘要信息
        
        Returns:
            摘要字符串
        """
        if not self._dependency_reports:
            return "未进行依赖检查"
        
        lines = ["工具依赖检查摘要:"]
        for tool_name, report in self._dependency_reports.items():
            if report.all_satisfied:
                lines.append(f"  ✓ {tool_name}: 所有依赖满足")
            elif report.required_satisfied:
                missing_opt = [r.dependency.name for r in report.missing_optional]
                lines.append(f"  ○ {tool_name}: 必需依赖满足，可选依赖缺失: {', '.join(missing_opt)}")
            else:
                missing_req = [r.dependency.name for r in report.missing_required]
                lines.append(f"  ✗ {tool_name}: 必需依赖缺失: {', '.join(missing_req)}")
        
        return "\n".join(lines)
    
    def add_plugin_dir(self, plugin_dir: Path, is_builtin: bool = False, force_reload: bool = False) -> int:
        """添加插件目录并加载工具
        
        Args:
            plugin_dir: 插件目录路径
            is_builtin: 是否为内置工具目录
            force_reload: 是否强制重新加载模块
            
        Returns:
            加载的工具数量
        """
        if plugin_dir in self._plugin_dirs and not force_reload:
            logger.debug(f"插件目录已添加: {plugin_dir}")
            return 0
        
        if plugin_dir not in self._plugin_dirs:
            self._plugin_dirs.append(plugin_dir)
        return self._scan_directory(plugin_dir, is_builtin=is_builtin, force_reload=force_reload)
    
    def remove_plugin_dir(self, plugin_dir: Path) -> int:
        """移除插件目录并注销其工具
        
        Args:
            plugin_dir: 插件目录路径
            
        Returns:
            注销的工具数量
        """
        if plugin_dir not in self._plugin_dirs:
            return 0
        
        # 找出该目录加载的所有工具
        tools_to_remove = self.get_tools_by_source(plugin_dir)
        
        # 注销工具
        for name in tools_to_remove:
            self.unregister(name)
        
        self._plugin_dirs.remove(plugin_dir)
        logger.info(f"已移除插件目录: {plugin_dir}, 注销 {len(tools_to_remove)} 个工具")
        
        return len(tools_to_remove)
    
    def reload_plugin_dir(self, plugin_dir: Path) -> int:
        """重新加载插件目录
        
        先注销该目录的所有工具，然后重新扫描加载。
        
        Args:
            plugin_dir: 插件目录路径
            
        Returns:
            重新加载的工具数量
        """
        is_builtin = False
        
        # 获取该目录加载的模块名称，用于后续清理
        modules_to_clear = set()
        if plugin_dir in self._plugin_dirs:
            # 检查是否为内置目录
            tools = self.get_tools_by_source(plugin_dir)
            for tool_name in tools:
                info = self._plugin_info.get(tool_name)
                if info:
                    is_builtin = info.is_builtin
                    modules_to_clear.add(info.module_name)
            
            self.remove_plugin_dir(plugin_dir)
        
        # 清理已加载的模块，以便重新加载
        for module_name in modules_to_clear:
            if module_name in self._loaded_modules:
                del self._loaded_modules[module_name]
            if module_name in sys.modules:
                del sys.modules[module_name]
        
        return self.add_plugin_dir(plugin_dir, is_builtin=is_builtin, force_reload=True)
    
    def reload_tool(self, name: str) -> bool:
        """重新加载单个工具
        
        Args:
            name: 工具名称
            
        Returns:
            是否成功重新加载
        """
        info = self._plugin_info.get(name)
        if not info:
            logger.warning(f"工具 {name} 没有插件信息，无法重新加载")
            return False
        
        # 注销旧工具
        self.unregister(name)
        
        # 重新加载模块
        try:
            self._load_tools_from_file(
                info.source_file, 
                info.source_dir, 
                is_builtin=info.is_builtin,
                force_reload=True
            )
            return name in self.tools
        except Exception as e:
            logger.error(f"重新加载工具 {name} 失败: {e}")
            return False
    
    def scan_and_register(self, tools_dir: Path) -> None:
        """扫描目录并注册所有工具
        
        扫描指定目录下的所有 Python 文件，查找 Tool 子类并实例化注册。
        
        Args:
            tools_dir: 工具目录路径
        """
        self.add_plugin_dir(tools_dir, is_builtin=True)
    
    def on_register(self, callback: Callable[[Tool, Optional[PluginInfo]], None]) -> None:
        """注册工具注册事件回调
        
        Args:
            callback: 回调函数，接收 (tool, plugin_info) 参数
        """
        self._on_register_callbacks.append(callback)
    
    def on_unregister(self, callback: Callable[[str, Optional[PluginInfo]], None]) -> None:
        """注册工具注销事件回调
        
        Args:
            callback: 回调函数，接收 (tool_name, plugin_info) 参数
        """
        self._on_unregister_callbacks.append(callback)
    
    def _scan_directory(self, tools_dir: Path, is_builtin: bool = False, force_reload: bool = False) -> int:
        """扫描目录加载工具
        
        Args:
            tools_dir: 工具目录路径
            is_builtin: 是否为内置工具
            force_reload: 是否强制重新加载模块
            
        Returns:
            加载的工具数量
        """
        if not tools_dir.exists():
            logger.warning(f"工具目录不存在: {tools_dir}")
            return 0
        
        if not tools_dir.is_dir():
            logger.warning(f"路径不是目录: {tools_dir}")
            return 0
        
        loaded_count = 0
        for py_file in tools_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            
            try:
                count = self._load_tools_from_file(py_file, tools_dir, is_builtin=is_builtin, force_reload=force_reload)
                loaded_count += count
            except Exception as e:
                logger.error(f"加载工具文件失败 {py_file}: {e}")
        
        logger.info(f"从 {tools_dir} 加载了 {loaded_count} 个工具")
        return loaded_count
    
    def _load_tools_from_file(
        self, 
        py_file: Path, 
        source_dir: Path,
        is_builtin: bool = False,
        force_reload: bool = False
    ) -> int:
        """从 Python 文件加载工具
        
        Args:
            py_file: Python 文件路径
            source_dir: 来源目录
            is_builtin: 是否为内置工具
            force_reload: 是否强制重新加载模块
            
        Returns:
            加载的工具数量
        """
        # 使用文件的绝对路径哈希作为模块名的一部分，确保唯一性和稳定性
        path_hash = hash(str(py_file.resolve()))
        base_module_name = f"tools_plugin_{py_file.stem}_{abs(path_hash)}"
        
        # 如果强制重新加载，使用新的模块名（带时间戳）
        if force_reload:
            import time
            import shutil
            module_name = f"{base_module_name}_{int(time.time() * 1000000)}"
            # 清理旧模块
            for old_name in list(sys.modules.keys()):
                if old_name.startswith(f"tools_plugin_{py_file.stem}_"):
                    del sys.modules[old_name]
            for old_name in list(self._loaded_modules.keys()):
                if old_name.startswith(f"tools_plugin_{py_file.stem}_"):
                    del self._loaded_modules[old_name]
            
            # 删除 __pycache__ 中的 .pyc 文件
            pycache_dir = py_file.parent / "__pycache__"
            if pycache_dir.exists():
                for pyc_file in pycache_dir.glob(f"{py_file.stem}*.pyc"):
                    try:
                        pyc_file.unlink()
                    except Exception as e:
                        logger.debug(f"无法删除缓存文件 {pyc_file}: {e}")
            
            # 使 Python 的导入缓存失效
            importlib.invalidate_caches()
        else:
            module_name = base_module_name
            # 检查是否已加载
            if module_name in self._loaded_modules:
                return 0
        
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        
        if spec is None or spec.loader is None:
            logger.warning(f"无法加载模块: {py_file}")
            return 0
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        self._loaded_modules[module_name] = module
        
        # 查找所有 Tool 子类
        loaded_count = 0
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Tool) and obj is not Tool:
                # 确保类是在当前模块定义的，而不是导入的
                if obj.__module__ != module_name:
                    continue
                    
                try:
                    tool_instance = obj()
                    
                    # 创建插件信息
                    plugin_info = PluginInfo(
                        name=tool_instance.name,
                        source_file=py_file,
                        source_dir=source_dir,
                        module_name=module_name,
                        class_name=name,
                        version=getattr(obj, '__version__', None),
                        is_builtin=is_builtin
                    )
                    
                    self.register(tool_instance, plugin_info)
                    
                    # 如果启用了依赖检查，检查工具依赖
                    if self._check_dependencies:
                        self.check_tool_dependencies(tool_instance.name)
                    
                    loaded_count += 1
                except Exception as e:
                    logger.error(f"实例化工具失败 {name}: {e}")
        
        return loaded_count
