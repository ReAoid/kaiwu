#!/usr/bin/env python3
"""Kaiwu LLM Chat Backend - 主入口

命令行交互式大模型聊天程序，支持工具调用和 Skill 系统。
"""

import asyncio
import logging
import sys
from typing import List

from config.paths import LOGS_DIR, SKILLS_DIR, TOOLS_DIR
from config.prompts import CHARACTER_PERSONA, build_system_prompt
from config.settings import Settings
from core.logger import init_logging
from core.message import Message
from services.llm_service import get_llm
from skills.loader import SkillLoader
from skills.prompt_builder import SkillPromptBuilder
from tools.chain_handler import ToolChainHandler
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


async def main() -> None:
    """主入口函数
    
    初始化所有组件并启动命令行交互循环。
    """
    
    # 加载配置
    try:
        settings = Settings.load_from_file()
    except Exception as e:
        print(f"配置加载失败: {e}")
        sys.exit(1)
    
    # 初始化日志系统
    init_logging(
        log_level=settings.system.log_level,
        log_file=str(LOGS_DIR / "run.log")
    )
    logger.info("Kaiwu 启动中...")
    
    # 初始化 LLM 服务
    try:
        llm = get_llm(settings)
        logger.info(f"LLM 服务初始化成功: {settings.chat_llm.model}")
    except ValueError as e:
        print(f"LLM 初始化失败: {e}")
        sys.exit(1)
    
    # 初始化工具注册表并扫描工具
    tool_registry = ToolRegistry()
    tool_registry.scan_and_register(TOOLS_DIR)
    logger.info(f"已加载 {len(tool_registry.get_all_tools())} 个工具")
    
    # 加载 Skills 并构建系统提示词
    skill_loader = SkillLoader(SKILLS_DIR)
    skills = skill_loader.load_all()
    skills_prompt = SkillPromptBuilder().build_skills_prompt(skills)
    logger.info(f"已加载 {len(skills)} 个 Skills")
    
    # 构建系统提示词
    system_prompt = build_system_prompt(skills_prompt)
    system_message = Message(role="system", content=system_prompt)
    
    # 初始化工具调用链处理器
    chain_handler = ToolChainHandler(llm, tool_registry)
    
    # 对话历史
    history: List[Message] = []
    
    # 显示欢迎信息
    print(f"\n{CHARACTER_PERSONA['first_mes']}")
    print("(输入 exit/quit/q 退出)\n")
    
    # 命令行交互循环
    while True:
        try:
            user_input = input("你: ").strip()
        except EOFError:
            print("\n再见！")
            logger.info("用户退出 (EOF)")
            break
        except KeyboardInterrupt:
            # Ctrl+C 在输入时按下
            print("\n再见！")
            logger.info("用户退出 (Ctrl+C)")
            break
        
        # 检查退出命令
        if user_input.lower() in ['exit', 'quit', 'q']:
            print("再见！")
            logger.info("用户退出 (命令)")
            break
        
        # 跳过空输入
        if not user_input:
            continue
        
        # 添加用户消息到历史
        history.append(Message(role="user", content=user_input))
        logger.debug(f"用户输入: {user_input}")
        
        # 生成响应
        print("\n助手: ", end="", flush=True)
        response_text = ""
        
        try:
            async for chunk in chain_handler.process_with_tools(history, system_message):
                print(chunk, end="", flush=True)
                response_text += chunk
        except KeyboardInterrupt:
            # Ctrl+C 在生成响应时按下，取消当前请求但不退出
            print("\n[已取消当前请求，可继续对话]")
            logger.info("用户取消了当前请求")
            # 移除未完成的用户消息
            if history and history[-1].role == "user":
                history.pop()
            continue
        except asyncio.CancelledError:
            print("\n[操作已取消]")
            logger.info("异步操作被取消")
            break
        except Exception as e:
            error_msg = f"\n[错误: {e}]"
            print(error_msg)
            logger.error(f"生成响应失败: {e}", exc_info=True)
            response_text = error_msg
        
        print("\n")
        
        # 添加助手响应到历史
        if response_text:
            history.append(Message(role="assistant", content=response_text))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 顶层捕获，确保优雅退出
        print("\nKaiwu 已退出，再见！")
    except Exception as e:
        # 记录未捕获的异常
        logging.error(f"程序异常退出: {e}", exc_info=True)
        print(f"\n程序异常退出: {e}")
        sys.exit(1)
