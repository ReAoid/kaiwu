"""Skill 加载器"""

import logging
import platform
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .types import InstallKind, SkillEntry, SkillInstallSpec, SkillMetadata

logger = logging.getLogger(__name__)


class SkillLoader:
    """Skill 加载器"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir

    def load_all(self) -> List[SkillEntry]:
        """加载所有满足条件的 Skills"""
        entries = []
        if not self.skills_dir.exists():
            return entries

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                entry = self._load_skill(skill_md)
                if entry and self._check_requirements(entry):
                    entries.append(entry)
        return entries

    def _load_skill(self, skill_md: Path) -> Optional[SkillEntry]:
        """加载单个 Skill"""
        try:
            content = skill_md.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f"Failed to read skill file {skill_md}: {e}")
            return None

        frontmatter, body = self._parse_frontmatter(content)

        if not frontmatter:
            return None

        metadata_dict = frontmatter.get("metadata", {}).get("openclaw", {})
        
        # 解析安装规格
        install_specs = self._parse_install_specs(metadata_dict.get("install", []))
        
        metadata = SkillMetadata(
            emoji=metadata_dict.get("emoji"),
            requires=metadata_dict.get("requires"),
            os=metadata_dict.get("os"),
            install=install_specs if install_specs else None,
        )

        return SkillEntry(
            name=frontmatter.get("name", skill_md.parent.name),
            description=frontmatter.get("description", ""),
            content=content,
            file_path=str(skill_md),
            metadata=metadata
        )

    def _parse_install_specs(self, install_list: List[Dict]) -> List[SkillInstallSpec]:
        """解析安装规格列表"""
        specs = []
        for item in install_list:
            if not isinstance(item, dict):
                continue
            
            kind_str = item.get("kind", "").lower()
            try:
                kind = InstallKind(kind_str)
            except ValueError:
                logger.warning(f"Unknown install kind: {kind_str}")
                continue
            
            spec = SkillInstallSpec(
                kind=kind,
                id=item.get("id"),
                label=item.get("label"),
                bins=item.get("bins"),
                os=item.get("os"),
                formula=item.get("formula"),
                package=item.get("package"),
                npm_package=item.get("npm_package"),
                apt_package=item.get("apt_package"),
                url=item.get("url"),
                extract=item.get("extract", False),
                target_dir=item.get("target_dir"),
            )
            specs.append(spec)
        
        return specs

    def _parse_frontmatter(self, content: str) -> Tuple[Dict, str]:
        """解析 YAML frontmatter"""
        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        try:
            frontmatter = yaml.safe_load(parts[1])
            body = parts[2].strip()
            return frontmatter or {}, body
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse YAML frontmatter: {e}")
            return {}, content

    def _check_requirements(self, entry: SkillEntry) -> bool:
        """检查 Skill 依赖是否满足"""
        if not entry.metadata:
            return True

        # 检查 OS
        if entry.metadata.os:
            current_os = platform.system().lower()
            if current_os not in [os.lower() for os in entry.metadata.os]:
                logger.debug(f"Skill {entry.name} skipped: OS {current_os} not in {entry.metadata.os}")
                return False

        # 检查 bins
        if entry.metadata.requires:
            bins = entry.metadata.requires.get("bins", [])
            for bin_name in bins:
                if not shutil.which(bin_name):
                    logger.debug(f"Skill {entry.name} skipped: binary {bin_name} not found")
                    return False

        return True
