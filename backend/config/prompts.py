"""提示词系统 - 模板和角色人设配置"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplate:
    """提示词模板
    
    支持使用 {variable} 格式的变量替换。
    """
    template: str

    def render(self, **kwargs) -> str:
        """渲染模板，替换所有变量
        
        Args:
            **kwargs: 变量名和值的映射
            
        Returns:
            替换变量后的字符串
        """
        return self.template.format(**kwargs)


# 角色人设配置
CHARACTER_PERSONA = {
    "name": "Kaiwu Assistant",
    "description": "一个智能助手，能够执行文件操作和使用各种技能。",
    "first_mes": "你好！我是 Kaiwu 助手，有什么可以帮助你的？"
}


def build_system_prompt(skills_prompt: str = "") -> str:
    """构建系统提示词
    
    将角色人设和技能提示词组合成完整的系统提示词。
    
    Args:
        skills_prompt: 技能提示词，由 SkillPromptBuilder 生成
        
    Returns:
        完整的系统提示词
    """
    base = f"""You are {CHARACTER_PERSONA['name']}.
{CHARACTER_PERSONA['description']}

You have access to tools for file operations. Use them when needed.
"""
    if skills_prompt:
        base += f"\n{skills_prompt}"

    return base
