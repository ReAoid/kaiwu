"""会话管理器模块

提供多会话管理功能，支持会话的创建、检索、更新、删除和持久化。
参考: openclaw/src/agents/tools/sessions-*.ts
"""

import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .types import (
    SessionEntry,
    SessionKind,
    SessionMetadata,
    classify_session_kind,
    normalize_session_key,
)
from .history import SessionHistory, HistoryMessage

logger = logging.getLogger(__name__)


class SessionManager:
    """会话管理器
    
    管理多个会话，支持：
    - 会话创建、检索、更新、删除
    - 会话列表和过滤
    - 会话持久化到磁盘
    - 会话历史管理
    - 线程安全操作
    
    参考: openclaw/src/config/sessions/store.ts
    
    Attributes:
        store_path: 会话存储文件路径
        transcripts_dir: 会话历史记录目录
        main_key: 主会话键
        alias: 主会话别名
    """
    
    def __init__(
        self,
        store_path: Optional[Path] = None,
        transcripts_dir: Optional[Path] = None,
        main_key: str = "main",
        alias: str = "main",
        auto_save: bool = True,
    ):
        """初始化会话管理器
        
        Args:
            store_path: 会话存储文件路径，None 则不持久化
            transcripts_dir: 会话历史记录目录，None 则不保存历史
            main_key: 主会话键
            alias: 主会话别名
            auto_save: 是否在修改后自动保存
        """
        self.store_path = store_path
        self.transcripts_dir = transcripts_dir
        self.main_key = main_key
        self.alias = alias
        self.auto_save = auto_save
        
        self._sessions: Dict[str, SessionEntry] = {}
        self._histories: Dict[str, SessionHistory] = {}  # 会话历史缓存
        self._lock = threading.RLock()
        
        # 从磁盘加载已有会话
        if store_path and store_path.exists():
            self._load_from_disk()
    
    def _load_from_disk(self) -> None:
        """从磁盘加载会话数据"""
        if not self.store_path:
            return
        
        try:
            content = self.store_path.read_text(encoding="utf-8")
            if not content.strip():
                return
            
            data = json.loads(content)
            if not isinstance(data, dict):
                logger.warning(f"会话存储格式无效: {self.store_path}")
                return
            
            for key, entry_data in data.items():
                if isinstance(entry_data, dict):
                    try:
                        entry = SessionEntry.from_dict(entry_data)
                        entry.key = key  # 确保 key 一致
                        self._sessions[normalize_session_key(key)] = entry
                    except Exception as e:
                        logger.warning(f"加载会话失败 {key}: {e}")
            
            logger.info(f"从磁盘加载了 {len(self._sessions)} 个会话")
        except json.JSONDecodeError as e:
            logger.error(f"解析会话存储失败: {e}")
        except Exception as e:
            logger.error(f"加载会话存储失败: {e}")
    
    def _save_to_disk(self) -> None:
        """保存会话数据到磁盘"""
        if not self.store_path:
            return
        
        try:
            # 确保目录存在
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 序列化会话数据
            data = {
                entry.key: entry.to_dict()
                for entry in self._sessions.values()
            }
            
            # 原子写入
            content = json.dumps(data, indent=2, ensure_ascii=False)
            self.store_path.write_text(content, encoding="utf-8")
            
            logger.debug(f"保存了 {len(self._sessions)} 个会话到磁盘")
        except Exception as e:
            logger.error(f"保存会话存储失败: {e}")
    
    def _maybe_save(self) -> None:
        """如果启用自动保存，则保存到磁盘"""
        if self.auto_save:
            self._save_to_disk()
    
    # ========================================================================
    # 会话创建和检索
    # ========================================================================
    
    def create(
        self,
        key: str,
        kind: Optional[SessionKind] = None,
        metadata: Optional[SessionMetadata] = None,
        model: Optional[str] = None,
        spawned_by: Optional[str] = None,
    ) -> SessionEntry:
        """创建新会话
        
        Args:
            key: 会话键
            kind: 会话类型，None 则自动推断
            metadata: 会话元数据
            model: 使用的模型
            spawned_by: 父会话键
            
        Returns:
            创建的会话条目
            
        Raises:
            ValueError: 如果会话键已存在
        """
        normalized_key = normalize_session_key(key)
        
        with self._lock:
            if normalized_key in self._sessions:
                raise ValueError(f"会话已存在: {key}")
            
            # 自动推断会话类型
            if kind is None:
                kind = classify_session_kind(key, self.main_key, self.alias)
            
            # 计算 spawn_depth
            spawn_depth = 0
            if spawned_by:
                parent = self.get(spawned_by)
                if parent:
                    spawn_depth = parent.spawn_depth + 1
            
            entry = SessionEntry(
                key=key,
                kind=kind,
                metadata=metadata or SessionMetadata(),
                model=model,
                spawned_by=spawned_by,
                spawn_depth=spawn_depth,
            )
            
            self._sessions[normalized_key] = entry
            self._maybe_save()
            
            logger.info(f"创建会话: {key} (kind={kind.value})")
            return entry
    
    def get(self, key: str) -> Optional[SessionEntry]:
        """获取会话
        
        Args:
            key: 会话键
            
        Returns:
            会话条目，不存在则返回 None
        """
        normalized_key = normalize_session_key(key)
        with self._lock:
            return self._sessions.get(normalized_key)
    
    def get_or_create(
        self,
        key: str,
        kind: Optional[SessionKind] = None,
        metadata: Optional[SessionMetadata] = None,
        model: Optional[str] = None,
    ) -> SessionEntry:
        """获取或创建会话
        
        Args:
            key: 会话键
            kind: 会话类型
            metadata: 会话元数据
            model: 使用的模型
            
        Returns:
            会话条目
        """
        normalized_key = normalize_session_key(key)
        
        with self._lock:
            existing = self._sessions.get(normalized_key)
            if existing:
                return existing
            
            return self.create(key, kind, metadata, model)
    
    def get_by_session_id(self, session_id: str) -> Optional[SessionEntry]:
        """通过 session_id 获取会话
        
        Args:
            session_id: 会话 UUID
            
        Returns:
            会话条目，不存在则返回 None
        """
        with self._lock:
            for entry in self._sessions.values():
                if entry.session_id == session_id:
                    return entry
            return None
    
    # ========================================================================
    # 会话更新
    # ========================================================================
    
    def update(
        self,
        key: str,
        updater: Callable[[SessionEntry], None],
    ) -> Optional[SessionEntry]:
        """更新会话
        
        Args:
            key: 会话键
            updater: 更新函数，接收会话条目并原地修改
            
        Returns:
            更新后的会话条目，不存在则返回 None
        """
        normalized_key = normalize_session_key(key)
        
        with self._lock:
            entry = self._sessions.get(normalized_key)
            if not entry:
                return None
            
            updater(entry)
            entry.touch()
            self._maybe_save()
            
            return entry
    
    def set_model(self, key: str, model: str, provider: Optional[str] = None) -> bool:
        """设置会话使用的模型
        
        Args:
            key: 会话键
            model: 模型名称
            provider: 模型提供商
            
        Returns:
            是否成功
        """
        def updater(entry: SessionEntry) -> None:
            entry.model = model
            if provider:
                entry.model_provider = provider
        
        return self.update(key, updater) is not None
    
    def update_tokens(
        self,
        key: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        context_tokens: Optional[int] = None,
    ) -> bool:
        """更新会话 token 统计
        
        Args:
            key: 会话键
            input_tokens: 输入 token 增量
            output_tokens: 输出 token 增量
            context_tokens: 上下文 token 数（可选）
            
        Returns:
            是否成功
        """
        def updater(entry: SessionEntry) -> None:
            entry.input_tokens += input_tokens
            entry.output_tokens += output_tokens
            entry.total_tokens = entry.input_tokens + entry.output_tokens
            if context_tokens is not None:
                entry.context_tokens = context_tokens
        
        return self.update(key, updater) is not None
    
    def mark_system_sent(self, key: str) -> bool:
        """标记会话已发送系统提示
        
        Args:
            key: 会话键
            
        Returns:
            是否成功
        """
        def updater(entry: SessionEntry) -> None:
            entry.system_sent = True
        
        return self.update(key, updater) is not None
    
    def mark_aborted(self, key: str, aborted: bool = True) -> bool:
        """标记会话上次运行是否被中止
        
        Args:
            key: 会话键
            aborted: 是否中止
            
        Returns:
            是否成功
        """
        def updater(entry: SessionEntry) -> None:
            entry.aborted_last_run = aborted
        
        return self.update(key, updater) is not None
    
    # ========================================================================
    # 会话删除
    # ========================================================================
    
    def delete(self, key: str) -> bool:
        """删除会话
        
        Args:
            key: 会话键
            
        Returns:
            是否成功删除
        """
        normalized_key = normalize_session_key(key)
        
        with self._lock:
            if normalized_key not in self._sessions:
                return False
            
            del self._sessions[normalized_key]
            self._maybe_save()
            
            logger.info(f"删除会话: {key}")
            return True
    
    def clear(self) -> int:
        """清空所有会话
        
        Returns:
            删除的会话数量
        """
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            self._maybe_save()
            
            logger.info(f"清空了 {count} 个会话")
            return count
    
    # ========================================================================
    # 会话列表和查询
    # ========================================================================
    
    def list(
        self,
        kinds: Optional[List[SessionKind]] = None,
        limit: Optional[int] = None,
        active_minutes: Optional[int] = None,
        spawned_by: Optional[str] = None,
        include_main: bool = True,
    ) -> List[SessionEntry]:
        """列出会话
        
        Args:
            kinds: 过滤会话类型
            limit: 最大返回数量
            active_minutes: 只返回最近 N 分钟活跃的会话
            spawned_by: 只返回指定父会话的子会话
            include_main: 是否包含主会话
            
        Returns:
            会话列表，按更新时间降序排列
        """
        with self._lock:
            sessions = list(self._sessions.values())
        
        # 过滤
        if kinds:
            kind_set = set(kinds)
            sessions = [s for s in sessions if s.kind in kind_set]
        
        if not include_main:
            sessions = [s for s in sessions if s.kind != SessionKind.MAIN]
        
        if spawned_by:
            normalized_parent = normalize_session_key(spawned_by)
            sessions = [
                s for s in sessions
                if s.spawned_by and normalize_session_key(s.spawned_by) == normalized_parent
            ]
        
        if active_minutes:
            cutoff = int(datetime.now().timestamp() * 1000) - (active_minutes * 60 * 1000)
            sessions = [s for s in sessions if s.updated_at >= cutoff]
        
        # 排序（按更新时间降序）
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        
        # 限制数量
        if limit and limit > 0:
            sessions = sessions[:limit]
        
        return sessions
    
    def count(self) -> int:
        """获取会话数量
        
        Returns:
            会话数量
        """
        with self._lock:
            return len(self._sessions)
    
    def exists(self, key: str) -> bool:
        """检查会话是否存在
        
        Args:
            key: 会话键
            
        Returns:
            是否存在
        """
        normalized_key = normalize_session_key(key)
        with self._lock:
            return normalized_key in self._sessions
    
    def get_spawned_keys(self, parent_key: str) -> Set[str]:
        """获取指定会话的所有子会话键
        
        Args:
            parent_key: 父会话键
            
        Returns:
            子会话键集合
        """
        normalized_parent = normalize_session_key(parent_key)
        
        with self._lock:
            return {
                entry.key
                for entry in self._sessions.values()
                if entry.spawned_by and normalize_session_key(entry.spawned_by) == normalized_parent
            }
    
    # ========================================================================
    # 会话历史管理
    # ========================================================================
    
    def _get_transcript_path(self, key: str) -> Optional[Path]:
        """获取会话历史记录文件路径
        
        Args:
            key: 会话键
            
        Returns:
            历史记录文件路径，未配置 transcripts_dir 则返回 None
        """
        if not self.transcripts_dir:
            return None
        
        # 使用会话键的安全文件名
        safe_key = normalize_session_key(key).replace("/", "_").replace(":", "_")
        return self.transcripts_dir / f"{safe_key}.jsonl"
    
    def get_history(self, key: str, create: bool = True) -> Optional[SessionHistory]:
        """获取会话历史
        
        Args:
            key: 会话键
            create: 如果不存在是否创建
            
        Returns:
            会话历史对象，会话不存在且 create=False 则返回 None
        """
        normalized_key = normalize_session_key(key)
        
        with self._lock:
            # 检查缓存
            if normalized_key in self._histories:
                return self._histories[normalized_key]
            
            # 检查会话是否存在
            if normalized_key not in self._sessions:
                if not create:
                    return None
                # 自动创建会话
                self.create(key)
            
            # 创建历史对象
            transcript_path = self._get_transcript_path(key)
            history = SessionHistory(
                session_key=key,
                transcript_path=transcript_path,
                auto_save=self.auto_save,
            )
            
            # 更新会话的 transcript_path
            entry = self._sessions.get(normalized_key)
            if entry and transcript_path:
                entry.transcript_path = str(transcript_path)
                self._maybe_save()
            
            self._histories[normalized_key] = history
            return history
    
    def add_message(
        self,
        key: str,
        role: str,
        content: str,
        tool_call_id: Optional[str] = None,
        tool_calls: Optional[List[Dict]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[HistoryMessage]:
        """向会话添加消息
        
        Args:
            key: 会话键
            role: 消息角色
            content: 消息内容
            tool_call_id: 工具调用 ID
            tool_calls: 工具调用列表
            metadata: 额外元数据
            
        Returns:
            添加的消息对象，会话不存在则返回 None
        """
        history = self.get_history(key, create=True)
        if not history:
            return None
        
        message = history.add(
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
            metadata=metadata,
        )
        
        # 更新会话的更新时间
        self.update(key, lambda e: None)  # touch
        
        return message
    
    def get_messages(
        self,
        key: str,
        limit: Optional[int] = None,
        roles: Optional[List[str]] = None,
    ) -> List[HistoryMessage]:
        """获取会话消息历史
        
        Args:
            key: 会话键
            limit: 最大返回数量
            roles: 过滤角色列表
            
        Returns:
            消息列表
        """
        history = self.get_history(key, create=False)
        if not history:
            return []
        
        return history.get_messages(limit=limit, roles=roles)
    
    def get_openai_messages(self, key: str) -> List[Dict[str, Any]]:
        """获取 OpenAI 格式的会话消息
        
        Args:
            key: 会话键
            
        Returns:
            OpenAI 格式的消息列表
        """
        history = self.get_history(key, create=False)
        if not history:
            return []
        
        return history.to_openai_messages()
    
    def clear_history(self, key: str) -> int:
        """清空会话历史
        
        Args:
            key: 会话键
            
        Returns:
            清空的消息数量
        """
        history = self.get_history(key, create=False)
        if not history:
            return 0
        
        return history.clear()
    
    def truncate_history(self, key: str, keep_last: int) -> int:
        """截断会话历史
        
        Args:
            key: 会话键
            keep_last: 保留的消息数量
            
        Returns:
            删除的消息数量
        """
        history = self.get_history(key, create=False)
        if not history:
            return 0
        
        removed = history.truncate(keep_last)
        
        # 更新压缩计数
        if removed > 0:
            self.update(key, lambda e: setattr(e, 'compaction_count', e.compaction_count + 1))
        
        return removed
    
    def export_history(
        self,
        key: str,
        format: str = "json",
        include_system: bool = False,
    ) -> Optional[str]:
        """导出会话历史
        
        Args:
            key: 会话键
            format: 导出格式 (json, text)
            include_system: 是否包含系统消息（仅 text 格式）
            
        Returns:
            导出的字符串，会话不存在则返回 None
        """
        history = self.get_history(key, create=False)
        if not history:
            return None
        
        if format == "text":
            return history.export_to_text(include_system=include_system)
        else:
            return history.export_to_json()
    
    def delete_with_history(self, key: str) -> bool:
        """删除会话及其历史
        
        Args:
            key: 会话键
            
        Returns:
            是否成功删除
        """
        normalized_key = normalize_session_key(key)
        
        with self._lock:
            # 删除历史
            if normalized_key in self._histories:
                history = self._histories[normalized_key]
                history.clear()
                del self._histories[normalized_key]
            else:
                # 尝试删除历史文件
                transcript_path = self._get_transcript_path(key)
                if transcript_path and transcript_path.exists():
                    try:
                        transcript_path.unlink()
                    except Exception as e:
                        logger.warning(f"删除历史文件失败: {e}")
            
            # 删除会话
            return self.delete(key)
    
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
            self._sessions.clear()
            self._load_from_disk()
    
    # ========================================================================
    # 上下文管理器支持
    # ========================================================================
    
    def __enter__(self) -> "SessionManager":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.auto_save:
            self.save()
