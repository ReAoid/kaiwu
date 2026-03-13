---
name: summarize
description: "文本摘要和内容精简。支持多种摘要格式（TL;DR、要点列表、结构化、段落）和长文档分段摘要。"
metadata:
  openclaw:
    emoji: "📝"
    requires:
      bins: ["python3"]
---

# Summarize Skill

文本摘要和内容精简工具，支持长文档自动分段摘要。

## 触发条件

当用户请求以下内容时使用此 Skill：

- "总结一下这段内容"
- "帮我摘要这篇文章"
- "给我一个 TL;DR"
- "提取要点"
- "精简这段文字"

## 快速开始

```bash
# 生成摘要提示词（短文本）
python3 {baseDir}/scripts/summarize.py --text "要摘要的内容" --output-prompt

# 从文件读取
python3 {baseDir}/scripts/summarize.py --input /path/to/file.txt --output-prompt

# 从 stdin 读取
cat document.txt | python3 {baseDir}/scripts/summarize.py --input - --output-prompt

# 指定格式和长度
python3 {baseDir}/scripts/summarize.py --text "内容" --format bullet --length short --output-prompt
```

## 摘要格式

| 格式 | 说明 | 适用场景 |
|------|------|----------|
| `tldr` | 一两句话的简短摘要 | 快速了解核心要点 |
| `bullet` | 要点列表 | 会议纪要、文档概览 |
| `structured` | 结构化（概述+要点+结论） | 正式报告、文档摘要 |
| `paragraph` | 段落形式（默认） | 通用摘要 |

## 摘要长度

| 长度 | 说明 |
|------|------|
| `short` | 1-2 句话 |
| `medium` | 1 段落（100-200字）|
| `long` | 多段落（300-500字）|

## 命令参数

```bash
python3 {baseDir}/scripts/summarize.py [选项]

选项:
  --input, -i     输入文件路径（使用 '-' 从 stdin 读取）
  --text, -t      直接提供要摘要的文本
  --format, -f    摘要格式: tldr, bullet, structured, paragraph
  --length, -l    摘要长度: short, medium, long
  --context, -c   额外上下文信息
  --chunk-size    分段大小（默认 4000 字符）
  --output-prompt 输出提示词（用于发送给 LLM）
  --json          JSON 格式输出
```

## 使用示例

### 基本摘要

```bash
# 生成段落式摘要提示词
python3 {baseDir}/scripts/summarize.py --text "这是一段很长的文本..." --output-prompt
```

### TL;DR 格式

```bash
python3 {baseDir}/scripts/summarize.py --text "文本内容" --format tldr --output-prompt
```

### 要点列表

```bash
python3 {baseDir}/scripts/summarize.py --text "文本内容" --format bullet --length medium --output-prompt
```

### 带上下文的摘要

```bash
python3 {baseDir}/scripts/summarize.py --text "技术文档内容" --context "这是一篇关于 Python 异步编程的技术文档" --output-prompt
```

### 长文档分段摘要

对于超过 4000 字符的长文档，脚本会自动分段：

```bash
# 查看分段提示词
python3 {baseDir}/scripts/summarize.py --input long_document.txt --output-prompt --json
```

分段摘要流程：
1. 文档被分成多个块（默认 4000 字符，200 字符重叠）
2. 对每个块生成中间摘要提示词
3. 生成合并提示词，将中间摘要整合为最终摘要

### JSON 输出

```bash
python3 {baseDir}/scripts/summarize.py --text "内容" --output-prompt --json
```

## 工作流程

1. 使用脚本生成摘要提示词
2. 将提示词发送给 LLM（通过对话或 API）
3. LLM 返回摘要结果

对于长文档：
1. 脚本生成多个分段提示词
2. 依次将每个分段提示词发送给 LLM，获取中间摘要
3. 将中间摘要填入合并提示词
4. 发送合并提示词获取最终摘要

## 最佳实践

- 对于代码文件，使用 `structured` 格式
- 对于会议记录，使用 `bullet` 格式
- 对于快速预览，使用 `tldr` + `short`
- 长文档建议使用默认分段大小，确保上下文连贯

## 注意事项

- 此脚本生成提示词，实际摘要由 LLM 完成
- 摘要质量取决于源材料的清晰度
- 技术内容请保留重要术语
