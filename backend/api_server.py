#!/usr/bin/env python3
"""Kaiwu HTTP API 服务器

提供简单的 HTTP API 接口，用于与 LLM 服务交互。
使用 Python 标准库 http.server 实现，无需额外依赖。
"""

import argparse
import asyncio
import json
import logging
import sys
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加 backend 目录到 Python 路径
BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

from config.paths import CONFIG_DIR, LOGS_DIR, SKILLS_DIR, TOOLS_DIR, DATA_DIR
from config.prompts import build_system_prompt
from config.settings import Settings
from core.logger import init_logging
from core.message import Message
from services.llm_service import get_llm
from sessions.manager import SessionManager
from sessions.types import SessionKind
from skills.loader import SkillLoader
from skills.prompt_builder import SkillPromptBuilder
from tools.chain_handler import ToolChainHandler
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# 全局组件（在服务器启动时初始化）
_llm = None
_tool_registry = None
_chain_handler = None
_session_manager = None
_system_message = None


def init_components() -> None:
    """初始化所有服务组件"""
    global _llm, _tool_registry, _chain_handler, _session_manager, _system_message
    
    # 加载配置
    settings = Settings.load_from_file()
    
    # 初始化日志系统
    init_logging(
        log_level=settings.system.log_level,
        log_file=str(LOGS_DIR / "api_server.log")
    )
    logger.info("API 服务器初始化中...")
    
    # 初始化 LLM 服务
    _llm = get_llm(settings)
    logger.info(f"LLM 服务初始化成功: {settings.chat_llm.model}")
    
    # 初始化工具注册表
    _tool_registry = ToolRegistry()
    _tool_registry.scan_and_register(TOOLS_DIR)
    logger.info(f"已加载 {len(_tool_registry.get_all_tools())} 个工具")
    
    # 加载 Skills 并构建系统提示词
    skill_loader = SkillLoader(SKILLS_DIR)
    skills = skill_loader.load_all()
    skills_prompt = SkillPromptBuilder().build_skills_prompt(skills)
    logger.info(f"已加载 {len(skills)} 个 Skills")
    
    # 构建系统提示词
    system_prompt = build_system_prompt(skills_prompt)
    _system_message = Message(role="system", content=system_prompt)
    
    # 初始化工具调用链处理器
    _chain_handler = ToolChainHandler(_llm, _tool_registry)
    
    # 初始化会话管理器
    sessions_file = DATA_DIR / "sessions.json"
    transcripts_dir = DATA_DIR / "transcripts"
    _session_manager = SessionManager(
        store_path=sessions_file,
        transcripts_dir=transcripts_dir,
        auto_save=True
    )
    logger.info("会话管理器初始化成功")


async def process_chat_message(message: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """处理聊天消息
    
    Args:
        message: 用户消息
        session_id: 会话 ID（可选）
        
    Returns:
        包含 response 和 session_id 的字典，或包含 error 的字典
    """
    global _chain_handler, _session_manager, _system_message
    
    # 如果没有提供 session_id，创建新会话
    if not session_id:
        session_key = f"chat_{uuid.uuid4().hex[:12]}"
        session = _session_manager.create(session_key, kind=SessionKind.OTHER)
        session_id = session.session_id
        logger.info(f"创建新会话: {session_id}")
    else:
        # 尝试通过 session_id 获取会话
        session = _session_manager.get_by_session_id(session_id)
        if not session:
            # 如果会话不存在，创建新会话
            session_key = f"chat_{uuid.uuid4().hex[:12]}"
            session = _session_manager.create(session_key, kind=SessionKind.OTHER)
            session_id = session.session_id
            logger.info(f"会话不存在，创建新会话: {session_id}")
    
    # 获取会话历史
    history = _session_manager.get_history(session.key)
    
    # 添加用户消息到历史
    _session_manager.add_message(session.key, "user", message)
    
    # 构建消息列表
    messages: List[Message] = []
    for msg in history.get_messages():
        messages.append(Message(role=msg.role, content=msg.content))
    
    # 生成响应
    response_text = ""
    try:
        async for chunk in _chain_handler.process_with_tools(messages, _system_message):
            response_text += chunk
    except Exception as e:
        logger.error(f"生成响应失败: {e}", exc_info=True)
        return {"error": str(e), "session_id": session_id}
    
    # 添加助手响应到历史
    if response_text:
        _session_manager.add_message(session.key, "assistant", response_text)
    
    return {
        "response": response_text,
        "session_id": session_id
    }


class ChatHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器
    
    处理 /api/chat 端点的 POST 请求。
    """
    
    def log_message(self, format: str, *args) -> None:
        """重写日志方法，使用 logging 模块"""
        logger.info("%s - %s", self.address_string(), format % args)
    
    def send_json_response(self, data: Dict[str, Any], status: int = 200) -> None:
        """发送 JSON 响应
        
        Args:
            data: 响应数据
            status: HTTP 状态码
        """
        response_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response_body)
    
    def send_error_response(self, error: str, status: int = 400) -> None:
        """发送错误响应
        
        Args:
            error: 错误信息
            status: HTTP 状态码
        """
        self.send_json_response({"error": error}, status)
    
    def do_OPTIONS(self) -> None:
        """处理 OPTIONS 请求（CORS 预检）"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def do_POST(self) -> None:
        """处理 POST 请求"""
        if self.path != "/api/chat":
            self.send_error_response(f"未知端点: {self.path}", 404)
            return
        
        # 读取请求体
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error_response("请求体为空")
            return
        
        try:
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as e:
            self.send_error_response(f"JSON 解析失败: {e}")
            return
        except Exception as e:
            self.send_error_response(f"读取请求失败: {e}")
            return
        
        # 验证请求参数
        message = data.get("message")
        if not message:
            self.send_error_response("缺少 message 参数")
            return
        
        if not isinstance(message, str):
            self.send_error_response("message 必须是字符串")
            return
        
        session_id = data.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            self.send_error_response("session_id 必须是字符串")
            return
        
        # 处理聊天请求
        logger.info(f"收到聊天请求: message={message[:50]}..., session_id={session_id}")
        
        try:
            # 在新的事件循环中运行异步函数
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(process_chat_message(message, session_id))
            finally:
                loop.close()
            
            if "error" in result and "response" not in result:
                self.send_error_response(result["error"], 500)
            else:
                self.send_json_response(result)
                
        except Exception as e:
            logger.error(f"处理请求失败: {e}", exc_info=True)
            self.send_error_response(f"服务器内部错误: {e}", 500)


def run_server(port: int = 8080) -> None:
    """启动 HTTP 服务器
    
    Args:
        port: 监听端口
    """
    # 初始化组件
    init_components()
    
    # 创建并启动服务器
    server_address = ("", port)
    httpd = HTTPServer(server_address, ChatHandler)
    
    print(f"\nKaiwu API 服务器已启动")
    print(f"监听地址: http://localhost:{port}")
    print(f"API 端点: POST /api/chat")
    print("按 Ctrl+C 停止服务器\n")
    
    logger.info(f"API 服务器启动，监听端口 {port}")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
        logger.info("API 服务器停止")
    finally:
        httpd.server_close()


def main() -> None:
    """主入口函数"""
    parser = argparse.ArgumentParser(
        description="Kaiwu HTTP API 服务器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python api_server.py                  # 使用默认端口 8080
  python api_server.py --port 9000      # 使用端口 9000

API 使用:
  POST /api/chat
  请求体: {"message": "你好", "session_id": "可选"}
  响应: {"response": "...", "session_id": "..."}
        """
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8080,
        help="监听端口 (默认: 8080)"
    )
    
    args = parser.parse_args()
    
    try:
        run_server(args.port)
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"服务器启动失败: {e}")
        logger.error(f"服务器启动失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
