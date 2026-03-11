"""工具调用链处理器模块

处理 LLM 与工具之间的多轮调用循环。
"""

import json
import logging
from typing import AsyncGenerator, List, Optional

from core.message import Message
from providers.openai_llm import OpenaiLlm
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolChainHandler:
    """工具调用链处理器
    
    处理带工具调用的对话，支持多轮工具调用循环。
    
    流程:
    1. 发送消息给 LLM（带工具定义）
    2. 如果 LLM 返回工具调用，执行工具
    3. 将工具结果反馈给 LLM
    4. 重复直到 LLM 返回文本响应或达到最大迭代次数
    """
    
    def __init__(
        self,
        llm: OpenaiLlm,
        tool_registry: ToolRegistry,
        max_iterations: int = 10
    ):
        """初始化工具调用链处理器
        
        Args:
            llm: LLM 实例
            tool_registry: 工具注册表
            max_iterations: 最大迭代次数，防止无限循环
        """
        self.llm = llm
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
    
    async def process_with_tools(
        self,
        messages: List[Message],
        system_message: Optional[Message] = None
    ) -> AsyncGenerator[str, None]:
        """处理带工具调用的对话
        
        异步生成器，流式输出最终响应或工具执行状态。
        
        Args:
            messages: 对话历史消息列表
            system_message: 系统提示词消息（可选）
            
        Yields:
            响应文本片段或工具执行状态
        """
        import asyncio
        
        # 构建完整消息列表
        full_messages: List[Message] = []
        if system_message:
            full_messages.append(system_message)
        full_messages.extend(messages)
        
        # 获取工具定义
        tools = self.tool_registry.get_tools_for_llm()
        
        iteration = 0
        
        while iteration < self.max_iterations:
            iteration += 1
            logger.debug(f"工具调用链迭代 {iteration}/{self.max_iterations}")
            
            try:
                # 调用 LLM（带工具）
                result = await self.llm.agenerate_with_tools(full_messages, tools)
            except asyncio.CancelledError:
                logger.info("工具调用被取消")
                raise
            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                yield f"\n[LLM 调用错误: {e}]"
                return
            
            if not result.is_tool_call:
                # 没有工具调用，流式输出最终响应
                try:
                    async for chunk in self.llm.astream(full_messages):
                        yield chunk
                except asyncio.CancelledError:
                    logger.info("流式输出被取消")
                    raise
                return
            
            # 处理工具调用
            for tool_call in result.tool_calls:
                tool_name = tool_call.function.name
                tool_call_id = tool_call.id
                
                # 解析工具参数
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}
                    logger.error(f"解析工具参数失败: {tool_call.function.arguments}")
                
                # 输出工具执行状态
                yield f"\n[执行工具: {tool_name}]\n"
                logger.info(f"执行工具: {tool_name}, 参数: {tool_args}")
                
                # 执行工具
                tool = self.tool_registry.get_tool(tool_name)
                if tool:
                    try:
                        tool_result = tool.run(tool_args)
                    except Exception as e:
                        tool_result = f"错误: 工具执行失败 - {e}"
                        logger.error(f"工具执行失败 {tool_name}: {e}")
                else:
                    tool_result = f"错误: 未知工具 {tool_name}"
                    logger.warning(f"未知工具: {tool_name}")
                
                # 添加 assistant 消息（带 tool_calls）
                full_messages.append(Message(
                    role="assistant",
                    content="",
                    tool_calls=[{
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": tool_call.function.arguments
                        }
                    }]
                ))
                
                # 添加 tool 消息
                full_messages.append(Message(
                    role="tool",
                    content=tool_result,
                    tool_call_id=tool_call_id
                ))
        
        # 达到最大迭代次数
        yield "\n[警告: 达到最大迭代次数]\n"
        logger.warning(f"工具调用链达到最大迭代次数: {self.max_iterations}")
