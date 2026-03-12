"""代码编辑工具

支持精确行号编辑、字符串替换、Diff/Patch 等代码编辑操作。
参考: openclaw/src/agents/pi-tools.read.ts
"""

import ast
import difflib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.tool import Tool, ToolParameter


class SyntaxValidator:
    """语法验证器
    
    支持多种编程语言的语法验证：
    - Python: 使用 ast.parse()
    - JavaScript/TypeScript: 使用 node --check 或 tsc
    - JSON: 使用 json.loads()
    - YAML: 使用 yaml.safe_load()
    - Shell: 使用 bash -n
    - Go: 使用 gofmt
    - Rust: 使用 rustfmt --check
    """
    
    # 文件扩展名到语言的映射
    EXTENSION_TO_LANGUAGE = {
        '.py': 'python',
        '.pyw': 'python',
        '.js': 'javascript',
        '.mjs': 'javascript',
        '.cjs': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.sh': 'shell',
        '.bash': 'shell',
        '.zsh': 'shell',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.hxx': 'cpp',
    }
    
    def __init__(self):
        """初始化语法验证器"""
        self._available_validators: Dict[str, bool] = {}
    
    def detect_language(self, path: Path) -> Optional[str]:
        """根据文件扩展名检测编程语言
        
        Args:
            path: 文件路径
            
        Returns:
            语言名称，未知则返回 None
        """
        suffix = path.suffix.lower()
        return self.EXTENSION_TO_LANGUAGE.get(suffix)
    
    def is_validator_available(self, language: str) -> bool:
        """检查指定语言的验证器是否可用
        
        Args:
            language: 语言名称
            
        Returns:
            验证器是否可用
        """
        if language in self._available_validators:
            return self._available_validators[language]
        
        # 内置验证器始终可用
        if language in ('python', 'json', 'yaml'):
            self._available_validators[language] = True
            return True
        
        # 检查外部工具
        tool_map = {
            'javascript': 'node',
            'typescript': 'tsc',
            'shell': 'bash',
            'go': 'gofmt',
            'rust': 'rustfmt',
            'ruby': 'ruby',
        }
        
        tool = tool_map.get(language)
        if tool:
            available = shutil.which(tool) is not None
            self._available_validators[language] = available
            return available
        
        self._available_validators[language] = False
        return False
    
    def validate(
        self,
        content: str,
        path: Path,
        language: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """验证代码语法
        
        Args:
            content: 代码内容
            path: 文件路径（用于语言检测和错误报告）
            language: 指定语言（可选，默认自动检测）
            
        Returns:
            (是否有效, 错误信息) - 有效时错误信息为 None
        """
        if language is None:
            language = self.detect_language(path)
        
        if language is None:
            # 未知语言，跳过验证
            return True, None
        
        if not self.is_validator_available(language):
            # 验证器不可用，跳过验证
            return True, None
        
        # 根据语言选择验证方法
        validators = {
            'python': self._validate_python,
            'json': self._validate_json,
            'yaml': self._validate_yaml,
            'javascript': self._validate_javascript,
            'typescript': self._validate_typescript,
            'shell': self._validate_shell,
            'go': self._validate_go,
            'rust': self._validate_rust,
            'ruby': self._validate_ruby,
        }
        
        validator = validators.get(language)
        if validator:
            return validator(content, path)
        
        return True, None
    
    def _validate_python(
        self,
        content: str,
        path: Path
    ) -> Tuple[bool, Optional[str]]:
        """验证 Python 语法
        
        Args:
            content: Python 代码
            path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        try:
            ast.parse(content, filename=str(path))
            return True, None
        except SyntaxError as e:
            error_msg = f"Python 语法错误 (行 {e.lineno}): {e.msg}"
            if e.text:
                error_msg += f"\n  {e.text.strip()}"
                if e.offset:
                    error_msg += f"\n  {' ' * (e.offset - 1)}^"
            return False, error_msg
        except Exception as e:
            return False, f"Python 解析错误: {e}"
    
    def _validate_json(
        self,
        content: str,
        path: Path
    ) -> Tuple[bool, Optional[str]]:
        """验证 JSON 语法
        
        Args:
            content: JSON 内容
            path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        try:
            json.loads(content)
            return True, None
        except json.JSONDecodeError as e:
            return False, f"JSON 语法错误 (行 {e.lineno}, 列 {e.colno}): {e.msg}"
        except Exception as e:
            return False, f"JSON 解析错误: {e}"
    
    def _validate_yaml(
        self,
        content: str,
        path: Path
    ) -> Tuple[bool, Optional[str]]:
        """验证 YAML 语法
        
        Args:
            content: YAML 内容
            path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        try:
            import yaml
            yaml.safe_load(content)
            return True, None
        except yaml.YAMLError as e:
            if hasattr(e, 'problem_mark'):
                mark = e.problem_mark
                return False, f"YAML 语法错误 (行 {mark.line + 1}, 列 {mark.column + 1}): {e.problem}"
            return False, f"YAML 语法错误: {e}"
        except ImportError:
            # yaml 模块不可用，跳过验证
            return True, None
        except Exception as e:
            return False, f"YAML 解析错误: {e}"
    
    def _validate_javascript(
        self,
        content: str,
        path: Path
    ) -> Tuple[bool, Optional[str]]:
        """验证 JavaScript 语法
        
        使用 node --check 进行语法检查
        
        Args:
            content: JavaScript 代码
            path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        return self._validate_with_external_tool(
            content, path, ['node', '--check'], 'JavaScript'
        )
    
    def _validate_typescript(
        self,
        content: str,
        path: Path
    ) -> Tuple[bool, Optional[str]]:
        """验证 TypeScript 语法
        
        使用 tsc --noEmit 进行语法检查
        
        Args:
            content: TypeScript 代码
            path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        return self._validate_with_external_tool(
            content, path, ['tsc', '--noEmit', '--allowJs'], 'TypeScript'
        )
    
    def _validate_shell(
        self,
        content: str,
        path: Path
    ) -> Tuple[bool, Optional[str]]:
        """验证 Shell 脚本语法
        
        使用 bash -n 进行语法检查
        
        Args:
            content: Shell 脚本
            path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        return self._validate_with_external_tool(
            content, path, ['bash', '-n'], 'Shell'
        )
    
    def _validate_go(
        self,
        content: str,
        path: Path
    ) -> Tuple[bool, Optional[str]]:
        """验证 Go 语法
        
        使用 gofmt 进行语法检查
        
        Args:
            content: Go 代码
            path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        return self._validate_with_external_tool(
            content, path, ['gofmt', '-e'], 'Go', use_stdin=True
        )
    
    def _validate_rust(
        self,
        content: str,
        path: Path
    ) -> Tuple[bool, Optional[str]]:
        """验证 Rust 语法
        
        使用 rustfmt --check 进行语法检查
        
        Args:
            content: Rust 代码
            path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        return self._validate_with_external_tool(
            content, path, ['rustfmt', '--check'], 'Rust', use_stdin=True
        )
    
    def _validate_ruby(
        self,
        content: str,
        path: Path
    ) -> Tuple[bool, Optional[str]]:
        """验证 Ruby 语法
        
        使用 ruby -c 进行语法检查
        
        Args:
            content: Ruby 代码
            path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        return self._validate_with_external_tool(
            content, path, ['ruby', '-c'], 'Ruby', use_stdin=True
        )
    
    def _validate_with_external_tool(
        self,
        content: str,
        path: Path,
        command: List[str],
        language_name: str,
        use_stdin: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """使用外部工具验证语法
        
        Args:
            content: 代码内容
            path: 文件路径
            command: 验证命令
            language_name: 语言名称（用于错误消息）
            use_stdin: 是否通过 stdin 传递内容
            
        Returns:
            (是否有效, 错误信息)
        """
        import tempfile
        
        try:
            if use_stdin:
                # 通过 stdin 传递内容
                result = subprocess.run(
                    command,
                    input=content,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            else:
                # 写入临时文件
                suffix = path.suffix
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix=suffix,
                    delete=False
                ) as f:
                    f.write(content)
                    temp_path = f.name
                
                try:
                    cmd = command + [temp_path]
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                finally:
                    Path(temp_path).unlink(missing_ok=True)
            
            if result.returncode == 0:
                return True, None
            
            # 提取错误信息
            error_output = result.stderr or result.stdout
            if error_output:
                # 只取前几行错误信息
                lines = error_output.strip().split('\n')[:5]
                error_msg = '\n'.join(lines)
                return False, f"{language_name} 语法错误:\n{error_msg}"
            
            return False, f"{language_name} 语法检查失败"
            
        except subprocess.TimeoutExpired:
            return True, None  # 超时时跳过验证
        except FileNotFoundError:
            return True, None  # 工具不存在时跳过验证
        except Exception as e:
            return True, None  # 其他错误时跳过验证


# 全局语法验证器实例
_syntax_validator: Optional[SyntaxValidator] = None


def get_syntax_validator() -> SyntaxValidator:
    """获取语法验证器单例
    
    Returns:
        SyntaxValidator 实例
    """
    global _syntax_validator
    if _syntax_validator is None:
        _syntax_validator = SyntaxValidator()
    return _syntax_validator


class CodeEditTool(Tool):
    """代码编辑工具
    
    支持多种编辑模式：
    - replace: 替换指定行范围的内容
    - insert: 在指定行后插入内容
    - delete: 删除指定行范围
    - str_replace: 字符串替换（old_str -> new_str）
    - diff: 显示编辑前后对比（不修改文件）
    - apply_patch: 应用 unified diff 格式的补丁
    """
    
    def __init__(self):
        super().__init__(
            name="code_edit",
            description="编辑代码文件，支持行号编辑、字符串替换等操作"
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
                name="mode",
                type="string",
                description="编辑模式: replace(替换行), insert(插入), delete(删除行), str_replace(字符串替换), diff(显示差异), apply_patch(应用补丁)",
                required=True
            ),
            ToolParameter(
                name="start_line",
                type="integer",
                description="起始行号（1-based），用于 replace/delete/diff 模式",
                required=False,
                default=None
            ),
            ToolParameter(
                name="end_line",
                type="integer",
                description="结束行号（1-based，包含），用于 replace/delete/diff 模式",
                required=False,
                default=None
            ),
            ToolParameter(
                name="insert_line",
                type="integer",
                description="插入位置行号（在该行之后插入），用于 insert 模式。0 表示在文件开头插入",
                required=False,
                default=None
            ),
            ToolParameter(
                name="content",
                type="string",
                description="新内容，用于 replace/insert/diff 模式",
                required=False,
                default=None
            ),
            ToolParameter(
                name="old_str",
                type="string",
                description="要替换的原字符串，用于 str_replace 模式",
                required=False,
                default=None
            ),
            ToolParameter(
                name="new_str",
                type="string",
                description="替换后的新字符串，用于 str_replace 模式",
                required=False,
                default=None
            ),
            ToolParameter(
                name="patch",
                type="string",
                description="unified diff 格式的补丁内容，用于 apply_patch 模式",
                required=False,
                default=None
            ),
            ToolParameter(
                name="context_lines",
                type="integer",
                description="diff 输出时显示的上下文行数，默认 3",
                required=False,
                default=3
            ),
            ToolParameter(
                name="encoding",
                type="string",
                description="文件编码，默认 utf-8",
                required=False,
                default="utf-8"
            ),
            ToolParameter(
                name="create_if_missing",
                type="boolean",
                description="文件不存在时是否创建，默认 False",
                required=False,
                default=False
            ),
            ToolParameter(
                name="validate_syntax",
                type="boolean",
                description="编辑后是否验证语法，默认 True。支持 Python, JSON, YAML, JavaScript, TypeScript, Shell, Go, Rust, Ruby 等语言",
                required=False,
                default=True
            )
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行代码编辑
        
        Args:
            parameters: 编辑参数字典
            
        Returns:
            编辑结果或错误信息
        """
        path_str = parameters.get("path")
        if not path_str:
            return "错误: 缺少 path 参数"
        
        mode = parameters.get("mode")
        if not mode:
            return "错误: 缺少 mode 参数"
        
        if mode not in ("replace", "insert", "delete", "str_replace", "diff", "apply_patch"):
            return f"错误: 无效的 mode 参数 '{mode}'，支持: replace, insert, delete, str_replace, diff, apply_patch"
        
        encoding = parameters.get("encoding", "utf-8")
        create_if_missing = parameters.get("create_if_missing", False)
        path = Path(path_str)
        
        # 检查文件是否存在
        if not path.exists():
            if create_if_missing and mode in ("replace", "insert"):
                # 创建新文件
                return self._create_new_file(path, parameters, encoding)
            return f"错误: 文件不存在 - {path}"
        
        if not path.is_file():
            return f"错误: 路径不是文件 - {path}"
        
        # 根据模式执行编辑
        if mode == "replace":
            return self._replace_lines(path, parameters, encoding)
        elif mode == "insert":
            return self._insert_lines(path, parameters, encoding)
        elif mode == "delete":
            return self._delete_lines(path, parameters, encoding)
        elif mode == "str_replace":
            return self._str_replace(path, parameters, encoding)
        elif mode == "diff":
            return self._show_diff(path, parameters, encoding)
        elif mode == "apply_patch":
            return self._apply_patch(path, parameters, encoding)
        
        return f"错误: 未知模式 - {mode}"
    
    def _create_new_file(
        self,
        path: Path,
        parameters: Dict[str, Any],
        encoding: str
    ) -> str:
        """创建新文件
        
        Args:
            path: 文件路径
            parameters: 参数字典
            encoding: 文件编码
            
        Returns:
            操作结果
        """
        content = parameters.get("content")
        validate_syntax = parameters.get("validate_syntax", True)
        
        if content is None:
            return "错误: 创建新文件需要 content 参数"
        
        # 语法验证（在写入前）
        syntax_error = self._validate_syntax_if_enabled(content, path, validate_syntax)
        if syntax_error:
            return syntax_error
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
            return f"文件已创建: {path}"
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 创建文件失败 - {e}"
    
    def _read_file_lines(self, path: Path, encoding: str) -> tuple[Optional[List[str]], Optional[str]]:
        """读取文件内容为行列表
        
        Args:
            path: 文件路径
            encoding: 文件编码
            
        Returns:
            (行列表, 错误信息) - 成功时错误信息为 None
        """
        try:
            content = path.read_text(encoding=encoding)
            # 保留行尾换行符的处理
            lines = content.splitlines(keepends=True)
            # 如果文件不以换行符结尾，最后一行不会有换行符
            return lines, None
        except UnicodeDecodeError as e:
            return None, f"错误: 编码错误 - {e}"
        except PermissionError:
            return None, f"错误: 权限不足 - {path}"
        except Exception as e:
            return None, f"错误: 读取文件失败 - {e}"
    
    def _write_file_lines(
        self,
        path: Path,
        lines: List[str],
        encoding: str
    ) -> Optional[str]:
        """将行列表写入文件
        
        Args:
            path: 文件路径
            lines: 行列表
            encoding: 文件编码
            
        Returns:
            错误信息，成功时返回 None
        """
        try:
            content = "".join(lines)
            path.write_text(content, encoding=encoding)
            return None
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 写入文件失败 - {e}"
    
    def _validate_syntax_if_enabled(
        self,
        content: str,
        path: Path,
        validate_syntax: bool
    ) -> Optional[str]:
        """如果启用了语法验证，则验证内容的语法
        
        Args:
            content: 要验证的内容
            path: 文件路径（用于语言检测）
            validate_syntax: 是否启用语法验证
            
        Returns:
            语法错误信息，验证通过或未启用验证时返回 None
        """
        if not validate_syntax:
            return None
        
        validator = get_syntax_validator()
        is_valid, error_msg = validator.validate(content, path)
        
        if not is_valid:
            return f"语法验证失败:\n{error_msg}"
        
        return None
    
    def _validate_line_range(
        self,
        start_line: Optional[int],
        end_line: Optional[int],
        total_lines: int
    ) -> Optional[str]:
        """验证行号范围
        
        Args:
            start_line: 起始行号（1-based）
            end_line: 结束行号（1-based）
            total_lines: 文件总行数
            
        Returns:
            错误信息，验证通过返回 None
        """
        if start_line is None:
            return "错误: 缺少 start_line 参数"
        if end_line is None:
            return "错误: 缺少 end_line 参数"
        
        try:
            start_line = int(start_line)
            end_line = int(end_line)
        except (ValueError, TypeError):
            return "错误: start_line 和 end_line 必须是整数"
        
        if start_line < 1:
            return f"错误: start_line 必须 >= 1，当前值: {start_line}"
        if end_line < start_line:
            return f"错误: end_line ({end_line}) 必须 >= start_line ({start_line})"
        if start_line > total_lines:
            return f"错误: start_line ({start_line}) 超出文件行数 ({total_lines})"
        
        return None
    
    def _replace_lines(
        self,
        path: Path,
        parameters: Dict[str, Any],
        encoding: str
    ) -> str:
        """替换指定行范围的内容
        
        Args:
            path: 文件路径
            parameters: 参数字典
            encoding: 文件编码
            
        Returns:
            操作结果
        """
        content = parameters.get("content")
        if content is None:
            return "错误: replace 模式需要 content 参数"
        
        lines, error = self._read_file_lines(path, encoding)
        if error:
            return error
        
        start_line = parameters.get("start_line")
        end_line = parameters.get("end_line")
        validate_syntax = parameters.get("validate_syntax", True)
        
        # 验证行号
        error = self._validate_line_range(start_line, end_line, len(lines))
        if error:
            return error
        
        start_line = int(start_line)
        end_line = int(end_line)
        
        # 限制 end_line 不超过文件行数
        end_line = min(end_line, len(lines))
        
        # 检查原文件是否以换行符结尾
        original_content = path.read_text(encoding=encoding)
        ends_with_newline = original_content.endswith('\n')
        
        # 准备新内容
        new_content_lines = content.splitlines(keepends=True)
        if new_content_lines:
            # 如果新内容最后一行没有换行符
            if not new_content_lines[-1].endswith('\n'):
                # 如果不是替换到文件末尾，或者原文件以换行符结尾，添加换行符
                if end_line < len(lines) or ends_with_newline:
                    new_content_lines[-1] += '\n'
        
        # 执行替换（行号是 1-based，索引是 0-based）
        new_lines = lines[:start_line - 1] + new_content_lines + lines[end_line:]
        
        # 语法验证（在写入前）
        new_content_str = "".join(new_lines)
        syntax_error = self._validate_syntax_if_enabled(new_content_str, path, validate_syntax)
        if syntax_error:
            return syntax_error
        
        # 写入文件
        error = self._write_file_lines(path, new_lines, encoding)
        if error:
            return error
        
        replaced_count = end_line - start_line + 1
        return f"已替换第 {start_line}-{end_line} 行（共 {replaced_count} 行）: {path}"
    
    def _insert_lines(
        self,
        path: Path,
        parameters: Dict[str, Any],
        encoding: str
    ) -> str:
        """在指定行后插入内容
        
        Args:
            path: 文件路径
            parameters: 参数字典
            encoding: 文件编码
            
        Returns:
            操作结果
        """
        content = parameters.get("content")
        if content is None:
            return "错误: insert 模式需要 content 参数"
        
        insert_line = parameters.get("insert_line")
        if insert_line is None:
            return "错误: insert 模式需要 insert_line 参数"
        
        validate_syntax = parameters.get("validate_syntax", True)
        
        try:
            insert_line = int(insert_line)
        except (ValueError, TypeError):
            return "错误: insert_line 必须是整数"
        
        lines, error = self._read_file_lines(path, encoding)
        if error:
            return error
        
        if insert_line < 0:
            return f"错误: insert_line 必须 >= 0，当前值: {insert_line}"
        if insert_line > len(lines):
            return f"错误: insert_line ({insert_line}) 超出文件行数 ({len(lines)})"
        
        # 准备新内容
        new_content_lines = content.splitlines(keepends=True)
        if new_content_lines and not new_content_lines[-1].endswith('\n'):
            new_content_lines[-1] += '\n'
        
        # 执行插入
        new_lines = lines[:insert_line] + new_content_lines + lines[insert_line:]
        
        # 语法验证（在写入前）
        new_content_str = "".join(new_lines)
        syntax_error = self._validate_syntax_if_enabled(new_content_str, path, validate_syntax)
        if syntax_error:
            return syntax_error
        
        # 写入文件
        error = self._write_file_lines(path, new_lines, encoding)
        if error:
            return error
        
        inserted_count = len(new_content_lines)
        if insert_line == 0:
            return f"已在文件开头插入 {inserted_count} 行: {path}"
        return f"已在第 {insert_line} 行后插入 {inserted_count} 行: {path}"
    
    def _delete_lines(
        self,
        path: Path,
        parameters: Dict[str, Any],
        encoding: str
    ) -> str:
        """删除指定行范围
        
        Args:
            path: 文件路径
            parameters: 参数字典
            encoding: 文件编码
            
        Returns:
            操作结果
        """
        lines, error = self._read_file_lines(path, encoding)
        if error:
            return error
        
        start_line = parameters.get("start_line")
        end_line = parameters.get("end_line")
        
        # 验证行号
        error = self._validate_line_range(start_line, end_line, len(lines))
        if error:
            return error
        
        start_line = int(start_line)
        end_line = int(end_line)
        
        # 限制 end_line 不超过文件行数
        end_line = min(end_line, len(lines))
        
        # 执行删除
        new_lines = lines[:start_line - 1] + lines[end_line:]
        
        # 写入文件
        error = self._write_file_lines(path, new_lines, encoding)
        if error:
            return error
        
        deleted_count = end_line - start_line + 1
        return f"已删除第 {start_line}-{end_line} 行（共 {deleted_count} 行）: {path}"
    
    def _str_replace(
        self,
        path: Path,
        parameters: Dict[str, Any],
        encoding: str
    ) -> str:
        """字符串替换
        
        Args:
            path: 文件路径
            parameters: 参数字典
            encoding: 文件编码
            
        Returns:
            操作结果
        """
        old_str = parameters.get("old_str")
        new_str = parameters.get("new_str")
        validate_syntax = parameters.get("validate_syntax", True)
        
        if old_str is None:
            return "错误: str_replace 模式需要 old_str 参数"
        if new_str is None:
            return "错误: str_replace 模式需要 new_str 参数"
        
        try:
            content = path.read_text(encoding=encoding)
        except UnicodeDecodeError as e:
            return f"错误: 编码错误 - {e}"
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 读取文件失败 - {e}"
        
        # 检查 old_str 是否存在
        if old_str not in content:
            return f"错误: 未找到要替换的字符串"
        
        # 检查 old_str 出现次数
        count = content.count(old_str)
        if count > 1:
            return f"错误: 找到 {count} 处匹配，old_str 必须唯一标识要替换的内容"
        
        # 执行替换
        new_content = content.replace(old_str, new_str, 1)
        
        # 语法验证（在写入前）
        syntax_error = self._validate_syntax_if_enabled(new_content, path, validate_syntax)
        if syntax_error:
            return syntax_error
        
        try:
            path.write_text(new_content, encoding=encoding)
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 写入文件失败 - {e}"
        
        return f"已完成字符串替换: {path}"

    def _show_diff(
        self,
        path: Path,
        parameters: Dict[str, Any],
        encoding: str
    ) -> str:
        """显示编辑前后的差异（不修改文件）
        
        支持两种模式：
        1. 指定 start_line/end_line + content: 显示替换指定行后的差异
        2. 指定 old_str + new_str: 显示字符串替换后的差异
        
        Args:
            path: 文件路径
            parameters: 参数字典
            encoding: 文件编码
            
        Returns:
            unified diff 格式的差异输出
        """
        context_lines = parameters.get("context_lines", 3)
        try:
            context_lines = int(context_lines)
        except (ValueError, TypeError):
            context_lines = 3
        
        # 读取原始内容
        try:
            original_content = path.read_text(encoding=encoding)
        except UnicodeDecodeError as e:
            return f"错误: 编码错误 - {e}"
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 读取文件失败 - {e}"
        
        original_lines = original_content.splitlines(keepends=True)
        
        # 确定使用哪种差异模式
        start_line = parameters.get("start_line")
        end_line = parameters.get("end_line")
        content = parameters.get("content")
        old_str = parameters.get("old_str")
        new_str = parameters.get("new_str")
        
        if start_line is not None and end_line is not None and content is not None:
            # 行替换模式
            new_lines, error = self._compute_replace_diff(
                original_lines, start_line, end_line, content, original_content.endswith('\n')
            )
            if error:
                return error
        elif old_str is not None and new_str is not None:
            # 字符串替换模式
            new_lines, error = self._compute_str_replace_diff(
                original_content, old_str, new_str
            )
            if error:
                return error
        else:
            return "错误: diff 模式需要 (start_line + end_line + content) 或 (old_str + new_str) 参数"
        
        # 生成 unified diff
        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
            n=context_lines
        )
        
        diff_output = "".join(diff)
        
        if not diff_output:
            return "无差异: 新内容与原内容相同"
        
        return f"差异预览 ({path}):\n{diff_output}"
    
    def _compute_replace_diff(
        self,
        original_lines: List[str],
        start_line: int,
        end_line: int,
        content: str,
        ends_with_newline: bool
    ) -> Tuple[Optional[List[str]], Optional[str]]:
        """计算行替换后的新内容
        
        Args:
            original_lines: 原始行列表
            start_line: 起始行号（1-based）
            end_line: 结束行号（1-based）
            content: 新内容
            ends_with_newline: 原文件是否以换行符结尾
            
        Returns:
            (新行列表, 错误信息)
        """
        try:
            start_line = int(start_line)
            end_line = int(end_line)
        except (ValueError, TypeError):
            return None, "错误: start_line 和 end_line 必须是整数"
        
        total_lines = len(original_lines)
        
        if start_line < 1:
            return None, f"错误: start_line 必须 >= 1，当前值: {start_line}"
        if end_line < start_line:
            return None, f"错误: end_line ({end_line}) 必须 >= start_line ({start_line})"
        if start_line > total_lines:
            return None, f"错误: start_line ({start_line}) 超出文件行数 ({total_lines})"
        
        end_line = min(end_line, total_lines)
        
        # 准备新内容
        new_content_lines = content.splitlines(keepends=True)
        if new_content_lines:
            if not new_content_lines[-1].endswith('\n'):
                if end_line < total_lines or ends_with_newline:
                    new_content_lines[-1] += '\n'
        
        # 构建新行列表
        new_lines = original_lines[:start_line - 1] + new_content_lines + original_lines[end_line:]
        
        return new_lines, None
    
    def _compute_str_replace_diff(
        self,
        original_content: str,
        old_str: str,
        new_str: str
    ) -> Tuple[Optional[List[str]], Optional[str]]:
        """计算字符串替换后的新内容
        
        Args:
            original_content: 原始内容
            old_str: 要替换的字符串
            new_str: 替换后的字符串
            
        Returns:
            (新行列表, 错误信息)
        """
        if old_str not in original_content:
            return None, "错误: 未找到要替换的字符串"
        
        count = original_content.count(old_str)
        if count > 1:
            return None, f"错误: 找到 {count} 处匹配，old_str 必须唯一标识要替换的内容"
        
        new_content = original_content.replace(old_str, new_str, 1)
        new_lines = new_content.splitlines(keepends=True)
        
        return new_lines, None
    
    def _apply_patch(
        self,
        path: Path,
        parameters: Dict[str, Any],
        encoding: str
    ) -> str:
        """应用 unified diff 格式的补丁
        
        Args:
            path: 文件路径
            parameters: 参数字典
            encoding: 文件编码
            
        Returns:
            操作结果
        """
        patch_content = parameters.get("patch")
        validate_syntax = parameters.get("validate_syntax", True)
        
        if not patch_content:
            return "错误: apply_patch 模式需要 patch 参数"
        
        # 读取原始内容
        try:
            original_content = path.read_text(encoding=encoding)
        except UnicodeDecodeError as e:
            return f"错误: 编码错误 - {e}"
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 读取文件失败 - {e}"
        
        original_lines = original_content.splitlines(keepends=True)
        
        # 解析并应用补丁
        try:
            new_lines, stats = self._parse_and_apply_patch(original_lines, patch_content)
        except ValueError as e:
            return f"错误: 补丁解析失败 - {e}"
        except Exception as e:
            return f"错误: 应用补丁失败 - {e}"
        
        # 语法验证（在写入前）
        new_content = "".join(new_lines)
        syntax_error = self._validate_syntax_if_enabled(new_content, path, validate_syntax)
        if syntax_error:
            return syntax_error
        
        # 写入文件
        try:
            path.write_text(new_content, encoding=encoding)
        except PermissionError:
            return f"错误: 权限不足 - {path}"
        except Exception as e:
            return f"错误: 写入文件失败 - {e}"
        
        return f"已应用补丁: {path} (添加 {stats['added']} 行, 删除 {stats['removed']} 行)"
    
    def _parse_and_apply_patch(
        self,
        original_lines: List[str],
        patch_content: str
    ) -> Tuple[List[str], Dict[str, int]]:
        """解析并应用 unified diff 补丁
        
        Args:
            original_lines: 原始行列表
            patch_content: 补丁内容
            
        Returns:
            (新行列表, 统计信息)
            
        Raises:
            ValueError: 补丁格式错误或无法应用
        """
        patch_lines = patch_content.splitlines(keepends=True)
        
        # 确保每行都有换行符（除了最后一行可能没有）
        for i in range(len(patch_lines) - 1):
            if not patch_lines[i].endswith('\n'):
                patch_lines[i] += '\n'
        
        result_lines = list(original_lines)
        stats = {"added": 0, "removed": 0}
        
        # 跟踪行号偏移（因为添加/删除会改变行号）
        offset = 0
        
        i = 0
        while i < len(patch_lines):
            line = patch_lines[i]
            
            # 跳过文件头
            if line.startswith('---') or line.startswith('+++'):
                i += 1
                continue
            
            # 解析 hunk 头
            if line.startswith('@@'):
                hunk_info = self._parse_hunk_header(line)
                if hunk_info is None:
                    raise ValueError(f"无效的 hunk 头: {line.strip()}")
                
                old_start, old_count, new_start, new_count = hunk_info
                
                # 调整起始位置（考虑偏移）
                current_pos = old_start - 1 + offset  # 转换为 0-based 索引
                
                i += 1
                hunk_added = 0
                hunk_removed = 0
                
                # 处理 hunk 内容
                while i < len(patch_lines):
                    if i >= len(patch_lines):
                        break
                    
                    hunk_line = patch_lines[i]
                    
                    # 检查是否到达下一个 hunk 或文件
                    if hunk_line.startswith('@@') or hunk_line.startswith('---'):
                        break
                    
                    if hunk_line.startswith('-'):
                        # 删除行
                        if current_pos < len(result_lines):
                            # 验证要删除的行是否匹配
                            expected = hunk_line[1:]  # 去掉 '-' 前缀
                            actual = result_lines[current_pos]
                            # 比较时忽略行尾换行符差异
                            if expected.rstrip('\n\r') != actual.rstrip('\n\r'):
                                raise ValueError(
                                    f"补丁不匹配: 期望 '{expected.rstrip()}', "
                                    f"实际 '{actual.rstrip()}'"
                                )
                            result_lines.pop(current_pos)
                            hunk_removed += 1
                        else:
                            raise ValueError(f"补丁位置超出文件范围: 行 {current_pos + 1}")
                    elif hunk_line.startswith('+'):
                        # 添加行
                        new_line = hunk_line[1:]  # 去掉 '+' 前缀
                        result_lines.insert(current_pos, new_line)
                        current_pos += 1
                        hunk_added += 1
                    elif hunk_line.startswith(' ') or hunk_line == '\n':
                        # 上下文行
                        current_pos += 1
                    elif hunk_line.startswith('\\'):
                        # "\ No newline at end of file" 标记
                        pass
                    else:
                        # 无前缀的行视为上下文行
                        current_pos += 1
                    
                    i += 1
                
                # 更新偏移
                offset += hunk_added - hunk_removed
                stats["added"] += hunk_added
                stats["removed"] += hunk_removed
            else:
                i += 1
        
        return result_lines, stats
    
    def _parse_hunk_header(self, line: str) -> Optional[Tuple[int, int, int, int]]:
        """解析 hunk 头
        
        格式: @@ -old_start,old_count +new_start,new_count @@
        
        Args:
            line: hunk 头行
            
        Returns:
            (old_start, old_count, new_start, new_count) 或 None
        """
        import re
        
        # 匹配 @@ -start,count +start,count @@ 格式
        # count 可以省略（默认为 1）
        pattern = r'^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@'
        match = re.match(pattern, line)
        
        if not match:
            return None
        
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) else 1
        
        return old_start, old_count, new_start, new_count
    
    def generate_diff(
        self,
        original_content: str,
        new_content: str,
        filename: str = "file",
        context_lines: int = 3
    ) -> str:
        """生成两个内容之间的 unified diff
        
        这是一个辅助方法，可用于在执行编辑前预览差异。
        
        Args:
            original_content: 原始内容
            new_content: 新内容
            filename: 文件名（用于 diff 头）
            context_lines: 上下文行数
            
        Returns:
            unified diff 格式的字符串
        """
        original_lines = original_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=context_lines
        )
        
        return "".join(diff)
