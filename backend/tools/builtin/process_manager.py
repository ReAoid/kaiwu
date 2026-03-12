"""进程管理工具

管理后台运行的进程，支持 list, poll, log, kill, write 操作。
参考: openclaw/src/agents/bash-tools.process.ts
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

from core.tool import Tool, ToolParameter
from tools.process_registry import (
    FinishedSession,
    ProcessRegistry,
    ProcessSession,
    ProcessStatus,
    get_process_registry,
)


class ProcessManagerTool(Tool):
    """进程管理工具
    
    管理后台运行的进程，支持以下操作：
    - list: 列出所有后台进程
    - poll: 轮询进程状态和新输出
    - log: 获取进程完整日志
    - kill: 终止进程
    - write: 向进程 stdin 写入数据
    """
    
    # 默认日志尾部行数
    DEFAULT_LOG_TAIL_LINES = 200
    
    def __init__(self, process_registry: Optional[ProcessRegistry] = None):
        """初始化工具
        
        Args:
            process_registry: 进程注册表，默认使用全局实例
        """
        super().__init__(
            name="process",
            description="管理后台进程：list（列出）、poll（轮询）、log（日志）、kill（终止）、write（写入）"
        )
        self._registry = process_registry or get_process_registry()
    
    def get_parameters(self) -> List[ToolParameter]:
        """获取参数定义"""
        return [
            ToolParameter(
                name="action",
                type="string",
                description="操作类型：list（列出所有进程）、poll（轮询状态和新输出）、log（获取完整日志）、kill（终止进程）、write（写入数据）",
                required=True
            ),
            ToolParameter(
                name="session_id",
                type="string",
                description="会话 ID，除 list 外的操作都需要",
                required=False,
                default=None
            ),
            ToolParameter(
                name="data",
                type="string",
                description="要写入的数据（write 操作需要）",
                required=False,
                default=None
            ),
            ToolParameter(
                name="offset",
                type="integer",
                description="日志偏移量（log 操作可选）",
                required=False,
                default=None
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description="日志行数限制（log 操作可选）",
                required=False,
                default=None
            ),
            ToolParameter(
                name="timeout",
                type="integer",
                description="poll 操作的等待超时时间（毫秒），最大 120000",
                required=False,
                default=0
            )
        ]
    
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行进程管理操作
        
        Args:
            parameters: 包含 action, session_id, data, offset, limit, timeout 的参数字典
            
        Returns:
            操作结果字符串
        """
        action = parameters.get("action")
        if not action:
            return "错误: 缺少 action 参数"
        
        action = action.lower()
        
        # 验证操作类型
        valid_actions = {"list", "poll", "log", "kill", "write"}
        if action not in valid_actions:
            return f"错误: 未知操作 {action}，支持的操作：list, poll, log, kill, write"
        
        if action == "list":
            return self._action_list()
        
        # 其他操作需要 session_id
        session_id = parameters.get("session_id")
        if not session_id:
            return "错误: 此操作需要 session_id 参数"
        
        if action == "poll":
            timeout = parameters.get("timeout", 0)
            return self._action_poll(session_id, timeout)
        elif action == "log":
            offset = parameters.get("offset")
            limit = parameters.get("limit")
            return self._action_log(session_id, offset, limit)
        elif action == "kill":
            return self._action_kill(session_id)
        elif action == "write":
            data = parameters.get("data", "")
            return self._action_write(session_id, data)
        
        # This should never be reached due to the validation above
        return f"错误: 未知操作 {action}"
    
    def _action_list(self) -> str:
        """列出所有后台进程
        
        Returns:
            进程列表字符串
        """
        running = self._registry.list_running_sessions()
        finished = self._registry.list_finished_sessions()
        
        if not running and not finished:
            return "没有运行中或最近完成的进程"
        
        lines = []
        
        # 运行中的进程
        for session in running:
            runtime_ms = int((time.time() - session.started_at) * 1000)
            runtime_str = self._format_duration(runtime_ms)
            command_short = self._truncate_command(session.command, 80)
            lines.append({
                "session_id": session.id,
                "status": "running",
                "runtime": runtime_str,
                "command": command_short,
                "pid": session.pid,
                "started_at": session.started_at
            })
        
        # 已完成的进程
        for session in finished:
            runtime_ms = int((session.ended_at - session.started_at) * 1000)
            runtime_str = self._format_duration(runtime_ms)
            command_short = self._truncate_command(session.command, 80)
            status_str = session.status.value
            lines.append({
                "session_id": session.id,
                "status": status_str,
                "runtime": runtime_str,
                "command": command_short,
                "exit_code": session.exit_code,
                "started_at": session.started_at
            })
        
        # 按启动时间排序（最新的在前）
        lines.sort(key=lambda x: x["started_at"], reverse=True)
        
        # 格式化输出
        output_lines = []
        for item in lines:
            status_padded = item["status"].ljust(9)
            output_lines.append(
                f"{item['session_id']} {status_padded} {item['runtime']} :: {item['command']}"
            )
        
        return "\n".join(output_lines)
    
    def _action_poll(self, session_id: str, timeout: int = 0) -> str:
        """轮询进程状态和新输出
        
        Args:
            session_id: 会话 ID
            timeout: 等待超时时间（毫秒）
            
        Returns:
            进程状态和输出
        """
        # 限制超时时间
        max_poll_wait_ms = 120000
        timeout = max(0, min(timeout, max_poll_wait_ms))
        
        session = self._registry.get_session(session_id)
        finished = self._registry.get_finished_session(session_id)
        
        # 检查已完成的会话
        if not session and finished:
            exit_info = self._format_exit_info(finished.exit_code, finished.status)
            output = finished.aggregated_output or "(无输出记录)"
            if finished.truncated:
                output += "\n[输出已截断]"
            return f"{output}\n\n{exit_info}"
        
        # 检查运行中的会话
        if not session:
            return f"错误: 未找到会话 {session_id}"
        
        if not session.backgrounded:
            return f"错误: 会话 {session_id} 不是后台进程"
        
        # 等待超时时间（如果指定）
        if timeout > 0 and session.status == ProcessStatus.RUNNING:
            deadline = time.time() + (timeout / 1000)
            while session.status == ProcessStatus.RUNNING and time.time() < deadline:
                time.sleep(min(0.25, (deadline - time.time())))
                # 重新获取会话状态
                session = self._registry.get_session(session_id)
                if not session:
                    break
        
        # 获取新输出
        if session:
            drained = self._registry.drain_session(session)
            stdout = drained.get("stdout", "").strip()
            stderr = drained.get("stderr", "").strip()
            
            output_parts = []
            if stdout:
                output_parts.append(stdout)
            if stderr:
                output_parts.append(f"[stderr]\n{stderr}")
            
            output = "\n".join(output_parts) if output_parts else "(无新输出)"
            
            # 检查进程是否已退出
            if session.status != ProcessStatus.RUNNING:
                exit_info = self._format_exit_info(session.exit_code, session.status)
                return f"{output}\n\n{exit_info}"
            else:
                return f"{output}\n\n进程仍在运行中"
        else:
            # 会话可能在等待期间结束
            finished = self._registry.get_finished_session(session_id)
            if finished:
                exit_info = self._format_exit_info(finished.exit_code, finished.status)
                return f"(无新输出)\n\n{exit_info}"
            return f"错误: 会话 {session_id} 已不存在"
    
    def _action_log(
        self,
        session_id: str,
        offset: Optional[int] = None,
        limit: Optional[int] = None
    ) -> str:
        """获取进程完整日志
        
        支持偏移量控制，可以分页读取大量日志。
        
        Args:
            session_id: 会话 ID
            offset: 日志偏移量（从第几行开始，0 为第一行）
            limit: 日志行数限制
            
        Returns:
            进程日志，包含分页信息
        """
        session = self._registry.get_session(session_id)
        finished = self._registry.get_finished_session(session_id)
        
        if session:
            if not session.backgrounded:
                return f"错误: 会话 {session_id} 不是后台进程"
            
            aggregated = session.aggregated_output
            truncated = session.truncated
            status = "running" if session.status == ProcessStatus.RUNNING else session.status.value
        elif finished:
            aggregated = finished.aggregated_output
            truncated = finished.truncated
            status = finished.status.value
        else:
            return f"错误: 未找到会话 {session_id}"
        
        # 切片日志
        slice_result = self._slice_log_lines(aggregated, offset, limit)
        log_content = slice_result["slice"] or "(无输出)"
        
        # 构建分页信息
        pagination_info = []
        
        # 添加尾部提示（仅在使用默认尾部显示且有更多内容时）
        using_default_tail = offset is None and limit is None
        if using_default_tail and slice_result["has_more_before"]:
            pagination_info.append(
                f"[显示最后 {self.DEFAULT_LOG_TAIL_LINES} 行，共 {slice_result['total_lines']} 行；"
                f"使用 offset/limit 参数翻页]"
            )
        elif slice_result["has_more_before"] or slice_result["has_more_after"]:
            # 显示当前位置信息
            start = slice_result["start_line"]
            end = slice_result["end_line"]
            total = slice_result["total_lines"]
            pagination_info.append(f"[显示第 {start + 1}-{end} 行，共 {total} 行]")
            
            # 提供翻页提示
            if slice_result["has_more_before"]:
                prev_offset = max(0, start - (limit or self.DEFAULT_LOG_TAIL_LINES))
                pagination_info.append(f"[上一页: offset={prev_offset}]")
            if slice_result["has_more_after"]:
                pagination_info.append(f"[下一页: offset={end}]")
        
        # 添加状态信息
        status_info = f"[状态: {status}]"
        if truncated:
            status_info += " [输出已截断]"
        
        # 组合输出
        result_parts = [log_content]
        if pagination_info:
            result_parts.append("\n" + " ".join(pagination_info))
        result_parts.append("\n" + status_info)
        
        return "\n".join(result_parts)
    
    def _action_kill(self, session_id: str) -> str:
        """终止进程
        
        Args:
            session_id: 会话 ID
            
        Returns:
            操作结果
        """
        session = self._registry.get_session(session_id)
        
        if not session:
            return f"错误: 未找到活动会话 {session_id}"
        
        if not session.backgrounded:
            return f"错误: 会话 {session_id} 不是后台进程"
        
        success = self._registry.kill_session(session_id)
        
        if success:
            return f"已终止会话 {session_id}"
        else:
            return f"错误: 无法终止会话 {session_id}"
    
    def _action_write(self, session_id: str, data: str) -> str:
        """向进程 stdin 写入数据
        
        Args:
            session_id: 会话 ID
            data: 要写入的数据
            
        Returns:
            操作结果
        """
        session = self._registry.get_session(session_id)
        
        if not session:
            return f"错误: 未找到活动会话 {session_id}"
        
        if not session.backgrounded:
            return f"错误: 会话 {session_id} 不是后台进程"
        
        # 检查是否是 PTY 模式
        if hasattr(session, '_pty_master_fd') and session._pty_master_fd is not None:
            return self._write_to_pty(session, data)
        
        # 普通模式：写入 stdin
        if session.process and session.process.stdin:
            try:
                session.process.stdin.write(data)
                session.process.stdin.flush()
                return f"已写入 {len(data)} 字节到会话 {session_id}"
            except Exception as e:
                return f"错误: 写入失败 - {e}"
        else:
            return f"错误: 会话 {session_id} 的 stdin 不可写"
    
    def _write_to_pty(self, session: ProcessSession, data: str) -> str:
        """向 PTY 会话写入数据
        
        Args:
            session: 进程会话
            data: 要写入的数据
            
        Returns:
            操作结果
        """
        master_fd = session._pty_master_fd
        
        try:
            os.write(master_fd, data.encode('utf-8'))
            return f"已写入 {len(data)} 字节到 PTY 会话 {session.id}"
        except OSError as e:
            return f"错误: 写入 PTY 失败 - {e}"
    
    def _format_duration(self, ms: int) -> str:
        """格式化持续时间
        
        Args:
            ms: 毫秒数
            
        Returns:
            格式化的时间字符串
        """
        if ms < 1000:
            return f"{ms}ms"
        
        seconds = ms // 1000
        if seconds < 60:
            return f"{seconds}s"
        
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        if minutes < 60:
            return f"{minutes}m{remaining_seconds}s"
        
        hours = minutes // 60
        remaining_minutes = minutes % 60
        return f"{hours}h{remaining_minutes}m"
    
    def _truncate_command(self, command: str, max_length: int) -> str:
        """截断命令字符串
        
        Args:
            command: 命令字符串
            max_length: 最大长度
            
        Returns:
            截断后的字符串
        """
        if len(command) <= max_length:
            return command
        
        # 从中间截断
        half = (max_length - 3) // 2
        return command[:half] + "..." + command[-half:]
    
    def _format_exit_info(
        self,
        exit_code: Optional[int],
        status: ProcessStatus
    ) -> str:
        """格式化退出信息
        
        Args:
            exit_code: 退出码
            status: 进程状态
            
        Returns:
            退出信息字符串
        """
        if status == ProcessStatus.KILLED:
            return "进程已被终止 (SIGKILL)"
        elif status == ProcessStatus.COMPLETED:
            return f"进程已完成，退出码: {exit_code or 0}"
        elif status == ProcessStatus.FAILED:
            return f"进程执行失败，退出码: {exit_code or -1}"
        else:
            return f"进程状态: {status.value}"
    
    def _slice_log_lines(
        self,
        content: str,
        offset: Optional[int] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """切片日志行
        
        支持偏移量控制，可以从任意位置读取日志。
        
        Args:
            content: 日志内容
            offset: 起始行偏移（从 0 开始）。如果指定，从该行开始读取。
                   如果未指定但指定了 limit，则从末尾倒数 limit 行开始。
            limit: 行数限制。如果未指定 offset 和 limit，默认显示最后 DEFAULT_LOG_TAIL_LINES 行。
            
        Returns:
            包含以下字段的字典:
            - slice: 切片后的日志内容
            - total_lines: 总行数
            - total_chars: 总字符数
            - start_line: 实际起始行号（从 0 开始）
            - end_line: 实际结束行号（不包含）
            - has_more_before: 是否有更早的日志
            - has_more_after: 是否有更多的日志
        """
        if not content:
            return {
                "slice": "",
                "total_lines": 0,
                "total_chars": 0,
                "start_line": 0,
                "end_line": 0,
                "has_more_before": False,
                "has_more_after": False
            }
        
        # 规范化行结束符
        normalized = content.replace('\r\n', '\n')
        lines = normalized.split('\n')
        
        # 移除末尾空行（如果内容以换行符结尾）
        if lines and lines[-1] == '':
            lines.pop()
        
        total_lines = len(lines)
        total_chars = len(content)
        
        # 默认显示最后 N 行
        using_default_tail = offset is None and limit is None
        if using_default_tail:
            limit = self.DEFAULT_LOG_TAIL_LINES
        
        # 计算切片范围
        if offset is not None:
            # 指定了偏移量，从该位置开始
            start = max(0, int(offset))
        elif limit is not None:
            # 只指定了 limit，从末尾倒数
            start = max(0, total_lines - int(limit))
        else:
            start = 0
        
        if limit is not None:
            end = min(total_lines, start + int(limit))
        else:
            end = total_lines
        
        sliced_lines = lines[start:end]
        
        return {
            "slice": '\n'.join(sliced_lines),
            "total_lines": total_lines,
            "total_chars": total_chars,
            "start_line": start,
            "end_line": end,
            "has_more_before": start > 0,
            "has_more_after": end < total_lines
        }
