"""Skill 提示词构建器"""

from typing import List

from .types import SkillEntry


class SkillPromptBuilder:
    """Skill 提示词构建器"""

    def build_skills_prompt(self, skills: List[SkillEntry]) -> str:
        """将 Skills 格式化为提示词"""
        if not skills:
            return ""

        lines = ["# Available Skills\n"]
        for skill in skills:
            emoji = skill.metadata.emoji if skill.metadata and skill.metadata.emoji else ""
            lines.append(f"## {emoji} {skill.name}")
            lines.append(f"**Description:** {skill.description}")
            lines.append(f"**Details:** Read `{skill.file_path}` for full instructions.\n")

        return "\n".join(lines)
