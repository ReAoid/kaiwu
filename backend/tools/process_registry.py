"""后台进程注册表模块

管理后台运行的进程，支持进程状态追踪、输出日志管理等功能。
参考: openclaw/src/agents/bash-process-registry.ts
"""

import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class ProcessStatus(Enum):
    """进程状态"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class ProcessSession:
    """进程会话
    
    Attributes:
        id: 会话 ID
        command: 执行的命令
        cwd: 工作目录
        pid: 进程 ID
        started_at: 启动时间戳
        process: subprocess.Popen 对象
        status: 进程状态
        exit_code: 退出码
        stdout_buffer: 标准输出缓冲
        stderr_buffer: 标准错误缓冲
        aggregated_output: 聚合输出
        truncated: 输出是否被截断
        backgrounded: 是否已后台化
        max_output_chars: 最大输出字符数
    """
    id: str
    command: str
    cwd: Optional[str]
    pid: Optional[int]
    started_at: float
    process: Optional[subprocess.Popen] = None
    status: ProcessStatus = ProcessStatus.RUNNING
    exit_code: Optional[int] = None
    stdout_buffer: List[str] = field(default_factory=list)
    stderr_buffer: List[str] = field(default_factory=list)
    aggregated_output: str = ""
    truncated: bool = False
    backgrounded: bool = False
    max_output_chars: int = 100000
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _output_thread: Optional[threading.Thread] = None
    
    def __post_init__(self):
        # 确保 lock 存在
        if not hasattr(self, '_lock') or self._lock is None:
            object.__setattr__(self, '_lock', threading.Lock())


@dataclass
class FinishedSession:
    """已完成的会话记录
    
    Attributes:
        id: 会话 ID
        command: 执行的命令
        cwd: 工作目录
        started_at: 启动时间戳
        ended_at: 结束时间戳
        status: 进程状态
        exit_code: 退出码
        aggregated_output: 聚合输出
        truncated: 输出是否被截断
    """
    id: str
    command: str
    cwd: Optional[str]
    started_at: float
    ended_at: float
    status: ProcessStatus
    exit_code: Optional[int]
    aggregated_output: str
    truncated: bool


class ProcessRegistry:
    """进程注册表
    
    管理所有后台运行的进程，提供进程状态查询、输出日志读取等功能。
    """
    
    # 默认配置
    DEFAULT_JOB_TTL_MS = 30 * 60 * 1000  # 30 分钟
    MIN_JOB_TTL_MS = 60 * 1000  # 1 分钟
    MAX_JOB_TTL_MS = 3 * 60 * 60 * 1000  # 3 小时
    DEFAULT_MAX_OUTPUT_CHARS = 100000
    
    def __init__(self, job_ttl_ms: Optional[int] = None):
        """初始化进程注册表
        
        Args:
            job_ttl_ms: 已完成任务的保留时间（毫秒）
        """
        self._running_sessions: Dict[str, ProcessSession] = {}
        self._finished_sessions: Dict[str, FinishedSession] = {}
        self._lock = threading.Lock()
        self._job_ttl_ms = self._clamp_ttl(job_ttl_ms)
        self._sweeper_thread: Optional[threading.Thread] = None
        self._sweeper_stop_event = threading.Event()
    
    def _clamp_ttl(self, value: Optional[int]) -> int:
        """限制 TTL 值在有效范围内"""
        if value is None:
            return self.DEFAULT_JOB_TTL_MS
        return max(self.MIN_JOB_TTL_MS, min(value, self.MAX_JOB_TTL_MS))
    
    def _generate_session_id(self) -> str:
        """生成唯一的会话 ID"""
        while True:
            # 生成短 ID (8 字符)
            session_id = uuid.uuid4().hex[:8]
            with self._lock:
                if session_id not in self._running_sessions and session_id not in self._finished_sessions:
                    return session_id
    
    def create_session(
        self,
        command: str,
        cwd: Optional[str] = None,
        max_output_chars: Optional[int] = None
    ) -> ProcessSession:
        """创建新的进程会话
        
        Args:
            command: 要执行的命令
            cwd: 工作目录
            max_output_chars: 最大输出字符数
            
        Returns:
            新创建的 ProcessSession
        """
        session_id = self._generate_session_id()
        session = ProcessSession(
            id=session_id,
            command=command,
            cwd=cwd,
            pid=None,
            started_at=time.time(),
            max_output_chars=max_output_chars or self.DEFAULT_MAX_OUTPUT_CHARS
        )
        
        with self._lock:
            self._running_sessions[session_id] = session
        
        self._start_sweeper()
        return session
    
    def add_session(self, session: ProcessSession) -> None:
        """添加会话到注册表
        
        Args:
            session: 要添加的会话
        """
        with self._lock:
            self._running_sessions[session.id] = session
        self._start_sweeper()
    
    def get_session(self, session_id: str) -> Optional[ProcessSession]:
        """获取运行中的会话
        
        Args:
            session_id: 会话 ID
            
        Returns:
            ProcessSession 或 None
        """
        with self._lock:
            return self._running_sessions.get(session_id)
    
    def get_finished_session(self, session_id: str) -> Optional[FinishedSession]:
        """获取已完成的会话
        
        Args:
            session_id: 会话 ID
            
        Returns:
            FinishedSession 或 None
        """
        with self._lock:
            return self._finished_sessions.get(session_id)
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话
        
        Args:
            session_id: 会话 ID
            
        Returns:
            是否成功删除
        """
        with self._lock:
            deleted = False
            if session_id in self._running_sessions:
                del self._running_sessions[session_id]
                deleted = True
            if session_id in self._finished_sessions:
                del self._finished_sessions[session_id]
                deleted = True
            return deleted
    
    def append_output(
        self,
        session: ProcessSession,
        stream: str,
        chunk: str
    ) -> None:
        """追加输出到会话
        
        Args:
            session: 会话对象
            stream: 输出流类型 ("stdout" 或 "stderr")
            chunk: 输出内容
        """
        with session._lock:
            buffer = session.stdout_buffer if stream == "stdout" else session.stderr_buffer
            buffer.append(chunk)
            
            # 更新聚合输出
            new_aggregated = session.aggregated_output + chunk
            if len(new_aggregated) > session.max_output_chars:
                session.truncated = True
                new_aggregated = new_aggregated[-session.max_output_chars:]
            session.aggregated_output = new_aggregated
    
    def drain_session(self, session: ProcessSession) -> Dict[str, str]:
        """获取并清空会话的待处理输出
        
        Args:
            session: 会话对象
            
        Returns:
            包含 stdout 和 stderr 的字典
        """
        with session._lock:
            stdout = "".join(session.stdout_buffer)
            stderr = "".join(session.stderr_buffer)
            session.stdout_buffer = []
            session.stderr_buffer = []
            return {"stdout": stdout, "stderr": stderr}
    
    def mark_exited(
        self,
        session: ProcessSession,
        exit_code: Optional[int],
        status: ProcessStatus
    ) -> None:
        """标记会话已退出
        
        Args:
            session: 会话对象
            exit_code: 退出码
            status: 进程状态
        """
        with session._lock:
            session.status = status
            session.exit_code = exit_code
        
        self._move_to_finished(session, status)
    
    def mark_backgrounded(self, session: ProcessSession) -> None:
        """标记会话为后台运行
        
        Args:
            session: 会话对象
        """
        with session._lock:
            session.backgrounded = True
    
    def _move_to_finished(self, session: ProcessSession, status: ProcessStatus) -> None:
        """将会话移动到已完成列表
        
        Args:
            session: 会话对象
            status: 进程状态
        """
        with self._lock:
            # 从运行中列表移除
            if session.id in self._running_sessions:
                del self._running_sessions[session.id]
            
            # 清理进程资源
            if session.process:
                try:
                    session.process.stdout.close() if session.process.stdout else None
                    session.process.stderr.close() if session.process.stderr else None
                    session.process.stdin.close() if session.process.stdin else None
                except Exception:
                    pass
                session.process = None
            
            # 只有后台化的会话才保存到已完成列表
            if session.backgrounded:
                finished = FinishedSession(
                    id=session.id,
                    command=session.command,
                    cwd=session.cwd,
                    started_at=session.started_at,
                    ended_at=time.time(),
                    status=status,
                    exit_code=session.exit_code,
                    aggregated_output=session.aggregated_output,
                    truncated=session.truncated
                )
                self._finished_sessions[session.id] = finished
    
    def list_running_sessions(self) -> List[ProcessSession]:
        """列出所有后台运行的会话
        
        Returns:
            后台运行的会话列表
        """
        with self._lock:
            return [s for s in self._running_sessions.values() if s.backgrounded]
    
    def list_finished_sessions(self) -> List[FinishedSession]:
        """列出所有已完成的会话
        
        Returns:
            已完成的会话列表
        """
        with self._lock:
            return list(self._finished_sessions.values())
    
    def kill_session(self, session_id: str) -> bool:
        """终止会话
        
        Args:
            session_id: 会话 ID
            
        Returns:
            是否成功终止
        """
        session = self.get_session(session_id)
        if not session:
            return False
        
        if session.process and session.process.poll() is None:
            try:
                session.process.terminate()
                # 等待一小段时间
                try:
                    session.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    session.process.kill()
                
                self.mark_exited(session, -9, ProcessStatus.KILLED)
                return True
            except Exception:
                return False
        
        return False
    
    def _start_sweeper(self) -> None:
        """启动清理线程"""
        if self._sweeper_thread and self._sweeper_thread.is_alive():
            return
        
        self._sweeper_stop_event.clear()
        self._sweeper_thread = threading.Thread(
            target=self._sweeper_loop,
            daemon=True
        )
        self._sweeper_thread.start()
    
    def _stop_sweeper(self) -> None:
        """停止清理线程"""
        self._sweeper_stop_event.set()
        if self._sweeper_thread:
            self._sweeper_thread.join(timeout=1)
            self._sweeper_thread = None
    
    def _sweeper_loop(self) -> None:
        """清理线程主循环"""
        interval = max(30, self._job_ttl_ms / 6000)  # 转换为秒
        while not self._sweeper_stop_event.wait(interval):
            self._prune_finished_sessions()
    
    def _prune_finished_sessions(self) -> None:
        """清理过期的已完成会话"""
        cutoff = time.time() - (self._job_ttl_ms / 1000)
        with self._lock:
            expired = [
                session_id
                for session_id, session in self._finished_sessions.items()
                if session.ended_at < cutoff
            ]
            for session_id in expired:
                del self._finished_sessions[session_id]
    
    def reset_for_tests(self) -> None:
        """重置注册表（用于测试）"""
        self._stop_sweeper()
        with self._lock:
            self._running_sessions.clear()
            self._finished_sessions.clear()


# 全局进程注册表实例
_global_registry: Optional[ProcessRegistry] = None


def get_process_registry() -> ProcessRegistry:
    """获取全局进程注册表实例
    
    Returns:
        ProcessRegistry 实例
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ProcessRegistry()
    return _global_registry


def reset_process_registry() -> None:
    """重置全局进程注册表（用于测试）"""
    global _global_registry
    if _global_registry:
        _global_registry.reset_for_tests()
    _global_registry = None
