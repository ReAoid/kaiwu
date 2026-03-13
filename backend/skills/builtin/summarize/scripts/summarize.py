#!/usr/bin/env python3
"""
文本摘要命令行工具

支持文本摘要和长文档分段摘要。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional


class SummaryFormat(Enum):
    """摘要输出格式"""
    TLDR = "tldr"
    BULLET = "bullet"
    STRUCTURED = "structured"
    PARAGRAPH = "paragraph"


class SummaryLength(Enum):
    """摘要长度"""
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


@dataclass
class SummaryResult:
    """摘要结果"""
    summary: str
    original_length: int
    summary_length: int
    chunks_count: int = 1
    format: str = "paragraph"


# 默认分段大小
DEFAULT_CHUNK_SIZE = 4000
DEFAULT_OVERLAP_SIZE = 200


def get_format_instruction(fmt: SummaryFormat) -> str:
    """获取格式指令"""
    instructions = {
        SummaryFormat.TLDR: "请用一到两句话总结核心要点，格式为：TL;DR: [摘要内容]",
        SummaryFormat.BULLET: "请用要点列表形式总结，每个要点用 • 开头",
        SummaryFormat.STRUCTURED: """请用以下结构化格式总结：
## 概述
简要描述内容主旨。

## 要点
- 要点1
- 要点2

## 结论
总结性陈述。""",
        SummaryFormat.PARAGRAPH: "请用简洁的段落形式总结主要内容。"
    }
    return instructions.get(fmt, instructions[SummaryFormat.PARAGRAPH])


def get_length_instruction(length: SummaryLength) -> str:
    """获取长度指令"""
    instructions = {
        SummaryLength.SHORT: "摘要应控制在1-2句话内。",
        SummaryLength.MEDIUM: "摘要应控制在一个段落内（约100-200字）。",
        SummaryLength.LONG: "可以使用多个段落进行详细总结（约300-500字）。"
    }
    return instructions.get(length, instructions[SummaryLength.MEDIUM])


def split_into_chunks(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, 
                      overlap_size: int = DEFAULT_OVERLAP_SIZE) -> List[str]:
    """将长文本分割成多个块"""
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        if end < len(text):
            for sep in ['。', '！', '？', '.', '!', '?', '\n\n', '\n']:
                last_sep = text.rfind(sep, start, end)
                if last_sep > start + chunk_size // 2:
                    end = last_sep + 1
                    break
        
        chunks.append(text[start:end].strip())
        start = end - overlap_size if end < len(text) else end
    
    return [c for c in chunks if c]


def build_prompt(text: str, fmt: SummaryFormat, length: SummaryLength, 
                 context: Optional[str] = None) -> str:
    """构建摘要提示词"""
    format_instruction = get_format_instruction(fmt)
    length_instruction = get_length_instruction(length)
    
    prompt = f"""请对以下内容进行摘要。

【格式要求】
{format_instruction}

【长度要求】
{length_instruction}

【摘要原则】
- 保持原文的核心含义和意图
- 确保事实准确性
- 使用清晰简洁的语言
"""
    
    if context:
        prompt += f"\n【额外上下文】\n{context}\n"
    
    prompt += f"\n【待摘要内容】\n{text}"
    
    return prompt


def build_merge_prompt(summaries: List[str], fmt: SummaryFormat, 
                       length: SummaryLength) -> str:
    """构建合并摘要的提示词"""
    format_instruction = get_format_instruction(fmt)
    length_instruction = get_length_instruction(length)
    
    combined = "\n\n".join([
        f"【第{i+1}部分摘要】\n{s}" 
        for i, s in enumerate(summaries)
    ])
    
    return f"""以下是一篇长文档各部分的摘要，请将它们整合成一份完整的摘要。

【格式要求】
{format_instruction}

【长度要求】
{length_instruction}

{combined}"""


def read_input(input_path: Optional[str]) -> str:
    """读取输入文本"""
    if input_path:
        if input_path == "-":
            return sys.stdin.read()
        return Path(input_path).read_text(encoding="utf-8")
    return ""


def eprint(msg: str) -> None:
    """输出到 stderr"""
    print(msg, file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="文本摘要工具 - 支持文本摘要和长文档分段摘要"
    )
    parser.add_argument(
        "--input", "-i",
        help="输入文件路径，使用 '-' 从 stdin 读取"
    )
    parser.add_argument(
        "--text", "-t",
        help="直接提供要摘要的文本"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["tldr", "bullet", "structured", "paragraph"],
        default="paragraph",
        help="摘要格式 (默认: paragraph)"
    )
    parser.add_argument(
        "--length", "-l",
        choices=["short", "medium", "long"],
        default="medium",
        help="摘要长度 (默认: medium)"
    )
    parser.add_argument(
        "--context", "-c",
        help="额外上下文信息"
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"分段大小 (默认: {DEFAULT_CHUNK_SIZE})"
    )
    parser.add_argument(
        "--output-prompt",
        action="store_true",
        help="只输出提示词，不调用 LLM"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 格式输出"
    )
    
    args = parser.parse_args()
    
    # 获取输入文本
    text = args.text or read_input(args.input)
    if not text.strip():
        eprint("错误: 未提供输入文本。使用 --text 或 --input 参数。")
        return 1
    
    fmt = SummaryFormat(args.format)
    length = SummaryLength(args.length)
    
    # 分段处理
    chunks = split_into_chunks(text, args.chunk_size)
    
    if args.output_prompt:
        # 只输出提示词
        if len(chunks) == 1:
            prompt = build_prompt(text, fmt, length, args.context)
        else:
            # 输出分段提示词
            prompts = []
            for i, chunk in enumerate(chunks):
                chunk_context = f"这是长文档的第 {i+1}/{len(chunks)} 部分。"
                if args.context:
                    chunk_context += " " + args.context
                prompts.append({
                    "chunk": i + 1,
                    "prompt": build_prompt(chunk, SummaryFormat.PARAGRAPH, 
                                          SummaryLength.MEDIUM, chunk_context)
                })
            prompts.append({
                "merge": True,
                "prompt": build_merge_prompt(
                    ["[第N部分摘要结果]"] * len(chunks), fmt, length
                )
            })
            
            if args.json:
                print(json.dumps(prompts, ensure_ascii=False, indent=2))
            else:
                for p in prompts:
                    if p.get("merge"):
                        print(f"\n=== 合并提示词 ===\n{p['prompt']}")
                    else:
                        print(f"\n=== 第 {p['chunk']} 段提示词 ===\n{p['prompt']}")
            return 0
        
        if args.json:
            print(json.dumps({"prompt": prompt}, ensure_ascii=False, indent=2))
        else:
            print(prompt)
        return 0
    
    # 输出摘要信息（实际摘要由 LLM 完成）
    result = {
        "original_length": len(text),
        "chunks_count": len(chunks),
        "format": args.format,
        "length": args.length,
        "message": "请将上述提示词发送给 LLM 获取摘要结果。使用 --output-prompt 查看提示词。"
    }
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"原文长度: {result['original_length']} 字符")
        print(f"分段数量: {result['chunks_count']}")
        print(f"摘要格式: {result['format']}")
        print(f"摘要长度: {result['length']}")
        print(f"\n提示: 使用 --output-prompt 参数生成提示词，然后发送给 LLM。")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
