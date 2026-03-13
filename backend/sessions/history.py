"""会话历史模块

提供会话消息历史的存储和管理功能。
支持 JSONL 格式的增量持久化，便于追加写入和流式读取。
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class HistoryMessage:
    """历史消息条目
    
    Attributes:
        role: 消息角色 (user, assistant, system, tool)
        content: 消息内容
        timestamp: 消息时间戳 (ISO 格式)
        tool_call_id: 工具调用 ID (tool 消息)
        tool_calls: 工具调用列表 (assistant 消息)
        metadata: 额外元数据
    """
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        data = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            data["tool_calls"] = self.tool_calls
        if self.metadata:
            data["metadata"] = self.metadata
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoryMessage":
        """从字典创建消息"""
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            tool_call_id=data.get("tool_call_id"),
            tool_calls=data.get("tool_calls"),
            metadata=data.get("metadata"),
        )
    
    def to_json_line(self) -> str:
        """转换为 JSON 行（用于 JSONL 格式）"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class SessionHistory:
    """会话历史管理器
    
    管理单个会话的消息历史，支持：
    - 内存中的消息列表
    - JSONL 格式的磁盘持久化
    - 增量追加写入
    - 流式读取历史
    - 历史压缩和截断
    
    Attributes:
        session_key: 会话键
        transcript_path: 历史记录文件路径
        max_messages: 内存中保留的最大消息数（0=不限制）
    """
    
    def __init__(
        self,
        session_key: str,
        transcript_path: Optional[Path] = None,
        max_messages: int = 0,
        auto_save: bool = True,
    ):
        """初始化会话历史
        
        Args:
            session_key: 会话键
            transcript_path: 历史记录文件路径，None 则不持久化
            max_messages: 内存中保留的最大消息数（0=不限制）
            auto_save: 是否在添加消息后自动保存
        """
        self.session_key = session_key
        self.transcript_path = transcript_path
        self.max_messages = max_messages
        self.auto_save = auto_save
        
        self._messages: List[HistoryMessage] = []
        self._lock = threading.RLock()
        self._dirty = False  # 是否有未保存的更改
        
        # 从磁盘加载已有历史
        if transcript_path and transcript_path.exists():
            self._load_from_disk()
    
    def _load_from_disk(self) -> None:
        """从磁盘加载历史记录"""
        if not self.transcript_path:
            return
        
        try:
            with open(self.transcript_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        msg = HistoryMessage.from_dict(data)
                        self._messages.append(msg)
                    except json.JSONDecodeError as e:
                        logger.warning(f"解析历史记录行 {line_num} 失败: {e}")
            
            logger.info(f"从磁盘加载了 {len(self._messages)} 条历史消息: {self.transcript_path}")
        except Exception as e:
            logger.error(f"加载历史记录失败: {e}")
    
    def _save_to_disk(self, messages: Optional[List[HistoryMessage]] = None) -> None:
        """保存历史记录到磁盘
        
        Args:
            messages: 要保存的消息列表，None 则保存所有消息
        """
        if not self.transcript_path:
            return
        
        try:
            # 确保目录存在
            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            
            msgs = messages if messages is not None else self._messages
            
            with open(self.transcript_path, "w", encoding="utf-8") as f:
                for msg in msgs:
                    f.write(msg.to_json_line() + "\n")
            
            self._dirty = False
            logger.debug(f"保存了 {len(msgs)} 条历史消息到磁盘")
        except Exception as e:
            logger.error(f"保存历史记录失败: {e}")
    
    def _append_to_disk(self, message: HistoryMessage) -> None:
        """追加单条消息到磁盘（增量写入）"""
        if not self.transcript_path:
            return
        
        try:
            # 确保目录存在
            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.transcript_path, "a", encoding="utf-8") as f:
                f.write(message.to_json_line() + "\n")
            
            logger.debug(f"追加消息到历史记录: {message.role}")
        except Exception as e:
            logger.error(f"追加历史记录失败: {e}")
            self._dirty = True  # 标记需要完整保存
    
    # ========================================================================
    # 消息操作
    # ========================================================================
    
    def add(
        self,
        role: str,
        content: str,
        tool_call_id: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> HistoryMessage:
        """添加消息到历史
        
        Args:
            role: 消息角色
            content: 消息内容
            tool_call_id: 工具调用 ID
            tool_calls: 工具调用列表
            metadata: 额外元数据
            
        Returns:
            添加的消息对象
        """
        message = HistoryMessage(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
            metadata=metadata,
        )
        
        with self._lock:
            self._messages.append(message)
            
            # 如果超过最大消息数，截断旧消息
            if self.max_messages > 0 and len(self._messages) > self.max_messages:
                self._messages = self._messages[-self.max_messages:]
                self._dirty = True  # 需要完整重写
            
            # 自动保存
            if self.auto_save:
                if self._dirty:
                    self._save_to_disk()
                else:
                    self._append_to_disk(message)
        
        return message
    
    def add_message(self, message: HistoryMessage) -> None:
        """添加已有消息对象到历史
        
        Args:
            message: 消息对象
        """
        with self._lock:
            self._messages.append(message)
            
            if self.max_messages > 0 and len(self._messages) > self.max_messages:
                self._messages = self._messages[-self.max_messages:]
                self._dirty = True
            
            if self.auto_save:
                if self._dirty:
                    self._save_to_disk()
                else:
                    self._append_to_disk(message)
    
    def get_messages(
        self,
        limit: Optional[int] = None,
        roles: Optional[List[str]] = None,
    ) -> List[HistoryMessage]:
        """获取历史消息
        
        Args:
            limit: 最大返回数量（从最新开始）
            roles: 过滤角色列表
            
        Returns:
            消息列表
        """
        with self._lock:
            messages = list(self._messages)
        
        if roles:
            role_set = set(roles)
            messages = [m for m in messages if m.role in role_set]
        
        if limit and limit > 0:
            messages = messages[-limit:]
        
        return messages
    
    def get_last_message(self, role: Optional[str] = None) -> Optional[HistoryMessage]:
        """获取最后一条消息
        
        Args:
            role: 过滤角色，None 则返回任意角色的最后消息
            
        Returns:
            最后一条消息，不存在则返回 None
        """
        with self._lock:
            if not self._messages:
                return None
            
            if role is None:
                return self._messages[-1]
            
            for msg in reversed(self._messages):
                if msg.role == role:
                    return msg
            
            return None
    
    def count(self) -> int:
        """获取消息数量"""
        with self._lock:
            return len(self._messages)
    
    def clear(self) -> int:
        """清空历史
        
        Returns:
            清空的消息数量
        """
        with self._lock:
            count = len(self._messages)
            self._messages.clear()
            
            # 清空磁盘文件
            if self.transcript_path and self.transcript_path.exists():
                try:
                    self.transcript_path.unlink()
                except Exception as e:
                    logger.error(f"删除历史文件失败: {e}")
            
            self._dirty = False
            return count
    
    def truncate(self, keep_last: int) -> int:
        """截断历史，只保留最后 N 条消息
        
        Args:
            keep_last: 保留的消息数量
            
        Returns:
            删除的消息数量
        """
        with self._lock:
            if keep_last >= len(self._messages):
                return 0
            
            removed = len(self._messages) - keep_last
            self._messages = self._messages[-keep_last:]
            self._save_to_disk()
            
            return removed
    
    # ========================================================================
    # 流式读取
    # ========================================================================
    
    def iter_messages(self) -> Iterator[HistoryMessage]:
        """迭代所有消息（流式读取）
        
        Yields:
            历史消息
        """
        with self._lock:
            for msg in self._messages:
                yield msg
    
    @classmethod
    def iter_from_file(cls, transcript_path: Path) -> Iterator[HistoryMessage]:
        """从文件流式读取消息（不加载到内存）
        
        Args:
            transcript_path: 历史记录文件路径
            
        Yields:
            历史消息
        """
        if not transcript_path.exists():
            return
        
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    yield HistoryMessage.from_dict(data)
                except json.JSONDecodeError:
                    continue
    
    # ========================================================================
    # 导出和转换
    # ========================================================================
    
    def to_openai_messages(self) -> List[Dict[str, Any]]:
        """转换为 OpenAI API 格式的消息列表
        
        Returns:
            OpenAI 格式的消息列表
        """
        result = []
        for msg in self.get_messages():
            openai_msg: Dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                openai_msg["tool_calls"] = msg.tool_calls
            result.append(openai_msg)
        return result
    
    def export_to_json(self) -> str:
        """导出为 JSON 格式
        
        Returns:
            JSON 字符串
        """
        messages = [msg.to_dict() for msg in self.get_messages()]
        return json.dumps(messages, indent=2, ensure_ascii=False)
    
    def export_to_text(self, include_system: bool = False) -> str:
        """导出为纯文本格式
        
        Args:
            include_system: 是否包含系统消息
            
        Returns:
            纯文本字符串
        """
        lines = []
        for msg in self.get_messages():
            if msg.role == "system" and not include_system:
                continue
            
            role_label = {
                "user": "用户",
                "assistant": "助手",
                "system": "系统",
                "tool": "工具",
            }.get(msg.role, msg.role)
            
            lines.append(f"[{role_label}] {msg.content}")
        
        return "\n\n".join(lines)
    
    # ========================================================================
    # 持久化控制
    # ========================================================================
    
    def save(self) -> None:
        """手动保存到磁盘"""
        with self._lock:
            self._save_to_disk()
    
    def reload(self) -> None:
        """从磁盘重新加载"""
        with self._lock:
            self._messages.clear()
            self._load_from_disk()
            self._dirty = False
    
    # ========================================================================
    # 上下文管理器支持
    # ========================================================================
    
    def __enter__(self) -> "SessionHistory":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._dirty:
            self.save()
    
    def __bool__(self) -> bool:
        """SessionHistory 对象始终为真（即使为空）"""
        return True
    
    def __len__(self) -> int:
        return self.count()
    
    def __iter__(self) -> Iterator[HistoryMessage]:
        return self.iter_messages()
