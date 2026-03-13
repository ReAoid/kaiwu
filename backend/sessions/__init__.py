"""会话管理模块

提供多会话管理功能，支持会话创建、检索、列表、删除和历史持久化。
"""

from .types import SessionEntry, SessionKind, SessionMetadata
from .manager import SessionManager
from .history import SessionHistory, HistoryMessage

__all__ = [
    "SessionEntry",
    "SessionKind", 
    "SessionMetadata",
    "SessionManager",
    "SessionHistory",
    "HistoryMessage",
]
