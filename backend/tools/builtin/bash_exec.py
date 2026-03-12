"""Bash/Shell 命令执行工具

支持执行 shell 命令，包括工作目录、超时控制、后台运行等功能。
参考: openclaw/src/agents/bash-tools.exec.ts
"""

import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.tool import Tool, ToolParameter
from tools.process_registry import (
    ProcessRegistry,
    ProcessSession,
    ProcessStatus,
    get_process_registry,
)


class BashExecTool(Tool):
    """Bash/Shell 命令执行工具
    
    支持执行 shell 命令，可配置工作目录、超时时间、后台运行等参数。
    """
    
    def __init__(self, process_registry: Optional[ProcessRegistry] = None):
        """初始化工具
        
        Args:
            process_registry: 进程注册表，默认使用全局实例
        """
        super().__init__(
            name="bash_exec",
            description="执行 shell 命令，支持工作目录、超时控制和后台运行"
        )
        self._registry = process_registry or get_process_registry()
    
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义"""
        return [
            ToolParameter(
                name="command",
                type="string",
                description="要执行的 shell 命令",
                required=True
            ),
            ToolParameter(
                name="cwd",
                type="string",
                description="工作目录，默认为当前目录",
                required=False,
                default=None
            ),
            ToolParameter(
                name="timeout",
                type="integer",
                description="命令执行超时时间（秒），默认 30 秒。后台模式下忽略此参数",
                required=False,
                default=30
            ),
            ToolParameter(
                name="shell",
                type="boolean",
                description="是否通过 shell 执行，默认 True",
                required=False,
                default=True
            ),
            ToolParameter(
                name="background",
                type="boolean",
                description="是否后台运行，默认 False。后台运行时返回进程 ID",
                required=False,
                default=False
            )
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行 shell 命令
        
        Args:
            parameters: 包含 command, cwd, timeout, shell, background 的参数字典
            
        Returns:
            命令执行结果或错误信息。后台模式返回会话 ID 和进程 ID
        """
        command = parameters.get("command")
        if not command:
            return "错误: 缺少 command 参数"
        
        cwd = parameters.get("cwd")
        timeout = parameters.get("timeout", 30)
        shell = parameters.get("shell", True)
        background = parameters.get("background", False)
        
        # 验证工作目录
        if cwd:
            cwd_path = Path(cwd)
            if not cwd_path.exists():
                return f"错误: 工作目录不存在 - {cwd}"
            if not cwd_path.is_dir():
                return f"错误: 工作目录不是目录 - {cwd}"
        
        # 后台模式
        if background:
            return self._run_background(command, cwd, shell)
        
        # 前台模式（同步执行）
        return self._run_foreground(command, cwd, timeout, shell)
    
    def _run_foreground(
        self,
        command: str,
        cwd: Optional[str],
        timeout: int,
        shell: bool
    ) -> str:
        """前台执行命令（同步）
        
        Args:
            command: 要执行的命令
            cwd: 工作目录
            timeout: 超时时间（秒）
            shell: 是否通过 shell 执行
            
        Returns:
            命令执行结果
        """
        # 验证超时时间
        try:
            timeout = int(timeout)
            if timeout <= 0:
                return "错误: timeout 必须大于 0"
        except (ValueError, TypeError):
            return "错误: timeout 必须是整数"
        
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                timeout=timeout,
                shell=shell,
                capture_output=True,
                text=True
            )
            
            # 构建输出
            output_parts = []
            
            if result.stdout:
                output_parts.append(result.stdout)
            
            if result.stderr:
                output_parts.append(f"[stderr]\n{result.stderr}")
            
            if result.returncode != 0:
                output_parts.append(f"[exit code: {result.returncode}]")
            
            return "\n".join(output_parts) if output_parts else "[命令执行成功，无输出]"
        
        except subprocess.TimeoutExpired:
            return f"错误: 命令执行超时（{timeout} 秒）"
        except FileNotFoundError:
            return "错误: 命令不存在或无法执行"
        except PermissionError:
            return "错误: 权限不足，无法执行命令"
        except Exception as e:
            return f"错误: 命令执行失败 - {e}"
    
    def _run_background(
        self,
        command: str,
        cwd: Optional[str],
        shell: bool
    ) -> str:
        """后台执行命令（异步）
        
        Args:
            command: 要执行的命令
            cwd: 工作目录
            shell: 是否通过 shell 执行
            
        Returns:
            包含会话 ID 和进程 ID 的结果字符串
        """
        try:
            # 创建会话
            session = self._registry.create_session(command, cwd)
            
            # 启动进程
            process = subprocess.Popen(
                command,
                cwd=cwd,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # 更新会话信息
            session.process = process
            session.pid = process.pid
            
            # 标记为后台运行
            self._registry.mark_backgrounded(session)
            
            # 启动输出收集线程
            self._start_output_collector(session)
            
            return (
                f"命令已在后台启动\n"
                f"会话 ID: {session.id}\n"
                f"进程 ID: {session.pid}\n"
                f"使用 process 工具 (list/poll/log/kill) 管理后台进程"
            )
        
        except FileNotFoundError:
            return "错误: 命令不存在或无法执行"
        except PermissionError:
            return "错误: 权限不足，无法执行命令"
        except Exception as e:
            return f"错误: 后台启动失败 - {e}"
    
    def _start_output_collector(self, session: ProcessSession) -> None:
        """启动输出收集线程
        
        Args:
            session: 进程会话
        """
        def collect_output():
            process = session.process
            if not process:
                return
            
            # 收集 stdout
            def read_stdout():
                try:
                    if process.stdout:
                        for line in iter(process.stdout.readline, ''):
                            if not line:
                                break
                            self._registry.append_output(session, "stdout", line)
                except Exception:
                    pass
            
            # 收集 stderr
            def read_stderr():
                try:
                    if process.stderr:
                        for line in iter(process.stderr.readline, ''):
                            if not line:
                                break
                            self._registry.append_output(session, "stderr", line)
                except Exception:
                    pass
            
            # 启动读取线程
            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            
            # 等待进程结束
            exit_code = process.wait()
            
            # 等待输出线程完成
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            
            # 标记会话结束
            status = ProcessStatus.COMPLETED if exit_code == 0 else ProcessStatus.FAILED
            self._registry.mark_exited(session, exit_code, status)
        
        # 启动收集线程
        collector_thread = threading.Thread(target=collect_output, daemon=True)
        collector_thread.start()
        session._output_thread = collector_thread
