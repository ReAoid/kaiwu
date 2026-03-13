#!/usr/bin/env python3
"""Kaiwu 聊天客户端

最简化的命令行聊天客户端，通过 HTTP API 与 kaiwu/backend 交互。
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import requests

# Session 管理模块
from backend.sessions.manager import SessionManager
from backend.sessions.history import SessionHistory
from backend.sessions.types import SessionKind

# 默认配置
DEFAULT_API_URL = "http://localhost:8080"
ENV_API_URL_KEY = "KAIWU_API_URL"
REQUEST_TIMEOUT = 60  # 秒

# Session 存储路径
DEFAULT_DATA_DIR = Path(__file__).parent / "backend" / "data"
DEFAULT_SESSIONS_FILE = DEFAULT_DATA_DIR / "sessions.json"
DEFAULT_TRANSCRIPTS_DIR = DEFAULT_DATA_DIR / "transcripts"


def get_api_url(cli_url: Optional[str] = None) -> str:
    """获取 API URL，按优先级：命令行参数 > 环境变量 > 默认值
    
    Args:
        cli_url: 命令行参数指定的 URL
        
    Returns:
        API URL 字符串
    """
    # 优先级 1: 命令行参数
    if cli_url:
        return cli_url
    
    # 优先级 2: 环境变量
    env_url = os.environ.get(ENV_API_URL_KEY)
    if env_url:
        return env_url
    
    # 优先级 3: 默认值
    return DEFAULT_API_URL


def send_message(
    message: str,
    api_url: str,
    session_id: Optional[str] = None,
    timeout: int = REQUEST_TIMEOUT
) -> dict:
    """发送消息到 Backend API
    
    Args:
        message: 用户消息
        api_url: API 服务器 URL
        session_id: 会话 ID（可选）
        timeout: 请求超时时间（秒）
        
    Returns:
        包含 response 和 session_id 的字典，或包含 error 的字典
    """
    url = f"{api_url.rstrip('/')}/api/chat"
    
    # 构建请求体
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        # HTTP 错误（4xx/5xx）
        try:
            error_data = e.response.json()
            return {"error": error_data.get("error", f"HTTP {e.response.status_code}")}
        except Exception:
            return {"error": f"HTTP {e.response.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"error": "连接失败: 无法连接到服务器"}
    except requests.exceptions.Timeout:
        return {"error": "请求超时: 服务器响应时间过长"}
    except requests.exceptions.JSONDecodeError:
        return {"error": "响应格式错误: 无法解析 JSON"}
    except Exception as e:
        return {"error": f"请求失败: {e}"}


def format_user_message(message: str) -> str:
    """格式化用户消息，添加角色标识
    
    Args:
        message: 用户输入的消息
        
    Returns:
        格式化后的消息字符串
    """
    return f"你: {message}"


def format_assistant_message(message: str) -> str:
    """格式化助手消息，添加角色标识
    
    Args:
        message: 助手回复的消息
        
    Returns:
        格式化后的消息字符串
    """
    return f"助手: {message}"


def format_error_message(error: str) -> str:
    """格式化错误消息
    
    Args:
        error: 错误信息
        
    Returns:
        格式化后的错误消息字符串
    """
    return f"[错误] {error}"


def format_waiting_message() -> str:
    """返回等待提示消息
    
    Returns:
        等待提示字符串
    """
    return "正在思考..."


def create_session(
    session_manager: SessionManager,
) -> Tuple[str, SessionHistory]:
    """创建新会话
    
    使用 SessionManager 创建新会话，生成唯一的 session_key 和 SessionHistory 对象。
    
    Args:
        session_manager: 会话管理器实例
        
    Returns:
        (session_key, session_history) 元组
    """
    # 生成唯一的会话键：chat_YYYYMMDD_HHMMSS
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_key = f"chat_{timestamp}"
    
    # 创建会话
    session_entry = session_manager.create(
        key=session_key,
        kind=SessionKind.OTHER,
    )
    
    # 获取会话历史对象
    session_history = session_manager.get_history(session_key, create=True)
    
    return session_entry.session_id, session_history


def main() -> None:
    """主入口函数"""
    parser = argparse.ArgumentParser(
        description="Kaiwu 聊天客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python chat_client.py                              # 使用默认 URL
  python chat_client.py --api-url http://localhost:9000  # 指定 URL
  
环境变量:
  KAIWU_API_URL  设置 API 服务器 URL（优先级低于命令行参数）
  
退出命令:
  输入 exit、quit 或 q 退出程序
        """
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=None,
        help=f"API 服务器 URL (默认: {DEFAULT_API_URL})"
    )
    
    args = parser.parse_args()
    
    # 获取 API URL
    api_url = get_api_url(args.api_url)
    
    # 初始化 SessionManager
    session_manager = SessionManager(
        store_path=DEFAULT_SESSIONS_FILE,
        transcripts_dir=DEFAULT_TRANSCRIPTS_DIR,
        auto_save=True,
    )
    
    # 创建新会话
    session_id, session_history = create_session(session_manager)
    
    print(f"Kaiwu 聊天客户端")
    print(f"API 服务器: {api_url}")
    print(f"会话 ID: {session_id}")
    print("输入 exit、quit 或 q 退出\n")
    
    try:
        while True:
            # 获取用户输入
            try:
                user_input = input("> ").strip()
            except EOFError:
                # 处理 EOF（如管道输入结束）
                print()
                break
            
            # 忽略空输入
            if not user_input:
                continue
            
            # 检查退出命令
            if user_input.lower() in ("exit", "quit", "q"):
                print("再见！")
                break
            
            # 显示用户消息
            print(format_user_message(user_input))
            
            # 保存用户消息到历史
            session_history.add(role="user", content=user_input)
            
            # 显示等待提示
            print(format_waiting_message())
            
            # 发送消息
            result = send_message(user_input, api_url, session_id)
            
            # 清除等待提示（向上移动一行并清除）
            print("\033[A\033[K", end="")
            
            # 处理响应
            if "error" in result and "response" not in result:
                print(format_error_message(result["error"]))
            else:
                # 显示助手回复
                response = result.get("response", "")
                if response:
                    print(format_assistant_message(response))
                    # 保存助手回复到历史
                    session_history.add(role="assistant", content=response)
                else:
                    print(format_error_message("收到空响应"))
            
            print()  # 空行分隔
            
    except KeyboardInterrupt:
        print("\n再见！")
        sys.exit(0)


if __name__ == "__main__":
    main()
