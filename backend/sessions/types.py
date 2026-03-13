"""会话类型定义模块

定义会话相关的数据结构和类型。
参考: openclaw/src/config/sessions/types.ts
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


class SessionKind(str, Enum):
    """会话类型枚举"""
    MAIN = "main"       # 主会话
    GROUP = "group"     # 群组会话
    CRON = "cron"       # 定时任务会话
    HOOK = "hook"       # 钩子会话
    NODE = "node"       # 节点会话
    OTHER = "other"     # 其他会话


@dataclass
class SessionMetadata:
    """会话元数据
    
    存储会话的附加信息，如来源、标签等。
    """
    label: Optional[str] = None
    display_name: Optional[str] = None
    channel: Optional[str] = None
    chat_type: Optional[str] = None  # dm, group, channel
    from_user: Optional[str] = None
    to_user: Optional[str] = None
    account_id: Optional[str] = None
    thread_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionEntry:
    """会话条目
    
    表示一个会话的完整状态。
    参考: openclaw/src/config/sessions/types.ts SessionEntry
    
    Attributes:
        session_id: 会话唯一标识符 (UUID)
        key: 会话键（用于查找）
        kind: 会话类型
        created_at: 创建时间戳 (ms)
        updated_at: 最后更新时间戳 (ms)
        metadata: 会话元数据
        model: 使用的模型名称
        model_provider: 模型提供商
        system_sent: 是否已发送系统提示
        aborted_last_run: 上次运行是否被中止
        spawned_by: 父会话键（用于子会话追踪）
        spawn_depth: 子会话深度 (0=主会话)
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        total_tokens: 总 token 数
        context_tokens: 上下文 token 数
        compaction_count: 压缩次数
        send_policy: 发送策略 (allow/deny)
        transcript_path: 会话记录文件路径
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    key: str = ""
    kind: SessionKind = SessionKind.OTHER
    created_at: int = field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    updated_at: int = field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    metadata: SessionMetadata = field(default_factory=SessionMetadata)
    
    # 模型相关
    model: Optional[str] = None
    model_provider: Optional[str] = None
    
    # 状态标志
    system_sent: bool = False
    aborted_last_run: bool = False
    
    # 子会话追踪
    spawned_by: Optional[str] = None
    spawn_depth: int = 0
    
    # Token 统计
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    context_tokens: int = 0
    compaction_count: int = 0
    
    # 策略
    send_policy: Literal["allow", "deny"] = "allow"
    
    # 文件路径
    transcript_path: Optional[str] = None
    
    def touch(self) -> None:
        """更新最后修改时间"""
        self.updated_at = int(datetime.now().timestamp() * 1000)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于序列化）"""
        return {
            "session_id": self.session_id,
            "key": self.key,
            "kind": self.kind.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": {
                "label": self.metadata.label,
                "display_name": self.metadata.display_name,
                "channel": self.metadata.channel,
                "chat_type": self.metadata.chat_type,
                "from_user": self.metadata.from_user,
                "to_user": self.metadata.to_user,
                "account_id": self.metadata.account_id,
                "thread_id": self.metadata.thread_id,
                "extra": self.metadata.extra,
            },
            "model": self.model,
            "model_provider": self.model_provider,
            "system_sent": self.system_sent,
            "aborted_last_run": self.aborted_last_run,
            "spawned_by": self.spawned_by,
            "spawn_depth": self.spawn_depth,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "context_tokens": self.context_tokens,
            "compaction_count": self.compaction_count,
            "send_policy": self.send_policy,
            "transcript_path": self.transcript_path,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionEntry":
        """从字典创建会话条目"""
        metadata_data = data.get("metadata", {})
        metadata = SessionMetadata(
            label=metadata_data.get("label"),
            display_name=metadata_data.get("display_name"),
            channel=metadata_data.get("channel"),
            chat_type=metadata_data.get("chat_type"),
            from_user=metadata_data.get("from_user"),
            to_user=metadata_data.get("to_user"),
            account_id=metadata_data.get("account_id"),
            thread_id=metadata_data.get("thread_id"),
            extra=metadata_data.get("extra", {}),
        )
        
        kind_str = data.get("kind", "other")
        try:
            kind = SessionKind(kind_str)
        except ValueError:
            kind = SessionKind.OTHER
        
        return cls(
            session_id=data.get("session_id", str(uuid.uuid4())),
            key=data.get("key", ""),
            kind=kind,
            created_at=data.get("created_at", int(datetime.now().timestamp() * 1000)),
            updated_at=data.get("updated_at", int(datetime.now().timestamp() * 1000)),
            metadata=metadata,
            model=data.get("model"),
            model_provider=data.get("model_provider"),
            system_sent=data.get("system_sent", False),
            aborted_last_run=data.get("aborted_last_run", False),
            spawned_by=data.get("spawned_by"),
            spawn_depth=data.get("spawn_depth", 0),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            context_tokens=data.get("context_tokens", 0),
            compaction_count=data.get("compaction_count", 0),
            send_policy=data.get("send_policy", "allow"),
            transcript_path=data.get("transcript_path"),
        )


def classify_session_kind(
    key: str,
    main_key: str = "main",
    alias: str = "main"
) -> SessionKind:
    """根据会话键分类会话类型
    
    参考: openclaw/src/agents/tools/sessions-helpers.ts classifySessionKind
    
    Args:
        key: 会话键
        main_key: 主会话键
        alias: 主会话别名
        
    Returns:
        会话类型
    """
    if key == alias or key == main_key:
        return SessionKind.MAIN
    if key.startswith("cron:"):
        return SessionKind.CRON
    if key.startswith("hook:"):
        return SessionKind.HOOK
    if key.startswith("node-") or key.startswith("node:"):
        return SessionKind.NODE
    if ":group:" in key or ":channel:" in key:
        return SessionKind.GROUP
    return SessionKind.OTHER


def normalize_session_key(key: str) -> str:
    """规范化会话键
    
    Args:
        key: 原始会话键
        
    Returns:
        规范化后的会话键（小写、去除首尾空格）
    """
    return key.strip().lower()
