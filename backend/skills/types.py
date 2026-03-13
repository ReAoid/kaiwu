"""Skill 类型定义"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


class InstallKind(str, Enum):
    """安装类型"""
    BREW = "brew"
    PIP = "pip"
    NPM = "npm"
    APT = "apt"
    DOWNLOAD = "download"


@dataclass
class SkillInstallSpec:
    """Skill 安装规格"""
    kind: InstallKind
    id: Optional[str] = None
    label: Optional[str] = None
    bins: Optional[List[str]] = None  # 安装后提供的二进制文件
    os: Optional[List[str]] = None  # 支持的操作系统
    # brew 特定
    formula: Optional[str] = None
    # pip 特定
    package: Optional[str] = None
    # npm 特定
    npm_package: Optional[str] = None
    # apt 特定
    apt_package: Optional[str] = None
    # download 特定
    url: Optional[str] = None
    extract: bool = False
    target_dir: Optional[str] = None


@dataclass
class SkillMetadata:
    """Skill 元数据"""
    emoji: Optional[str] = None
    requires: Optional[Dict[str, List[str]]] = None  # {"bins": ["gh"]}
    os: Optional[List[str]] = None  # ["darwin", "linux"]
    install: Optional[List[SkillInstallSpec]] = None  # 安装规格列表


@dataclass
class SkillEntry:
    """Skill 条目"""
    name: str
    description: str
    content: str  # SKILL.md 完整内容
    file_path: str
    metadata: Optional[SkillMetadata] = None


@dataclass
class InstallResult:
    """安装结果"""
    ok: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    code: Optional[int] = None
    warnings: Optional[List[str]] = None
