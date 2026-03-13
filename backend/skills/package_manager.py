"""包管理器集成模块

提供统一的包管理器检测、版本查询和包安装接口。
支持的包管理器：
- brew (macOS/Linux Homebrew)
- apt (Debian/Ubuntu)
- pip (Python)
- npm (Node.js)
"""

import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PackageManagerType(str, Enum):
    """包管理器类型"""
    BREW = "brew"
    APT = "apt"
    PIP = "pip"
    NPM = "npm"


@dataclass
class PackageManagerInfo:
    """包管理器信息"""
    type: PackageManagerType
    available: bool
    version: Optional[str] = None
    path: Optional[str] = None
    requires_sudo: bool = False
    error: Optional[str] = None


@dataclass
class PackageInfo:
    """包信息"""
    name: str
    version: Optional[str] = None
    installed: bool = False
    description: Optional[str] = None


@dataclass
class BinaryInfo:
    """二进制文件信息"""
    name: str
    path: Optional[str] = None
    version: Optional[str] = None
    exists: bool = False


class PackageManager:
    """包管理器统一接口"""

    def __init__(self, timeout: int = 30):
        """
        初始化包管理器

        Args:
            timeout: 命令执行超时时间（秒）
        """
        self.timeout = timeout
        self._current_os = platform.system().lower()
        self._cache: Dict[str, PackageManagerInfo] = {}

    def _run_command(
        self,
        args: List[str],
        timeout: Optional[int] = None,
    ) -> Tuple[int, str, str]:
        """
        运行命令

        Args:
            args: 命令参数列表
            timeout: 超时时间（秒）

        Returns:
            (返回码, stdout, stderr)
        """
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout or self.timeout}s"
        except FileNotFoundError:
            return -1, "", f"Command not found: {args[0]}"
        except Exception as e:
            return -1, "", str(e)

    # ==================== 二进制文件检查 ====================

    def check_binary(self, name: str) -> BinaryInfo:
        """
        检查二进制文件是否存在

        Args:
            name: 二进制文件名

        Returns:
            BinaryInfo 对象
        """
        path = shutil.which(name)
        if not path:
            return BinaryInfo(name=name, exists=False)

        # 尝试获取版本
        version = self._get_binary_version(name, path)

        return BinaryInfo(
            name=name,
            path=path,
            version=version,
            exists=True,
        )

    def check_binaries(self, names: List[str]) -> Dict[str, BinaryInfo]:
        """
        批量检查二进制文件

        Args:
            names: 二进制文件名列表

        Returns:
            {name: BinaryInfo} 字典
        """
        return {name: self.check_binary(name) for name in names}

    def _get_binary_version(self, name: str, path: str) -> Optional[str]:
        """尝试获取二进制文件版本"""
        # 常见的版本参数
        version_args = ["--version", "-v", "-V", "version"]

        for arg in version_args:
            code, stdout, stderr = self._run_command([path, arg], timeout=5)
            if code == 0 and stdout:
                # 尝试从输出中提取版本号
                version = self._extract_version(stdout)
                if version:
                    return version
            # 有些程序把版本输出到 stderr
            if stderr:
                version = self._extract_version(stderr)
                if version:
                    return version

        return None

    def _extract_version(self, text: str) -> Optional[str]:
        """从文本中提取版本号"""
        # 匹配常见的版本号格式
        patterns = [
            r"(\d+\.\d+\.\d+(?:-[\w.]+)?)",  # 1.2.3 或 1.2.3-beta
            r"(\d+\.\d+(?:\.\d+)?)",  # 1.2 或 1.2.3
            r"v(\d+\.\d+\.\d+)",  # v1.2.3
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)

        return None

    # ==================== 包管理器检测 ====================

    def detect_package_manager(
        self,
        pm_type: PackageManagerType,
    ) -> PackageManagerInfo:
        """
        检测包管理器是否可用

        Args:
            pm_type: 包管理器类型

        Returns:
            PackageManagerInfo 对象
        """
        # 检查缓存
        cache_key = pm_type.value
        if cache_key in self._cache:
            return self._cache[cache_key]

        if pm_type == PackageManagerType.BREW:
            info = self._detect_brew()
        elif pm_type == PackageManagerType.APT:
            info = self._detect_apt()
        elif pm_type == PackageManagerType.PIP:
            info = self._detect_pip()
        elif pm_type == PackageManagerType.NPM:
            info = self._detect_npm()
        else:
            info = PackageManagerInfo(
                type=pm_type,
                available=False,
                error=f"Unknown package manager type: {pm_type}",
            )

        self._cache[cache_key] = info
        return info

    def detect_all_package_managers(self) -> Dict[PackageManagerType, PackageManagerInfo]:
        """
        检测所有支持的包管理器

        Returns:
            {PackageManagerType: PackageManagerInfo} 字典
        """
        return {
            pm_type: self.detect_package_manager(pm_type)
            for pm_type in PackageManagerType
        }

    def get_available_package_managers(self) -> List[PackageManagerInfo]:
        """
        获取所有可用的包管理器

        Returns:
            可用的 PackageManagerInfo 列表
        """
        all_pms = self.detect_all_package_managers()
        return [info for info in all_pms.values() if info.available]

    def _detect_brew(self) -> PackageManagerInfo:
        """检测 Homebrew"""
        path = shutil.which("brew")
        if not path:
            return PackageManagerInfo(
                type=PackageManagerType.BREW,
                available=False,
                error="Homebrew not found. Install from https://brew.sh",
            )

        code, stdout, stderr = self._run_command(["brew", "--version"])
        version = None
        if code == 0:
            # Homebrew 4.2.0
            match = re.search(r"Homebrew\s+(\d+\.\d+\.\d+)", stdout)
            if match:
                version = match.group(1)

        return PackageManagerInfo(
            type=PackageManagerType.BREW,
            available=True,
            version=version,
            path=path,
            requires_sudo=False,
        )

    def _detect_apt(self) -> PackageManagerInfo:
        """检测 apt"""
        path = shutil.which("apt-get")
        if not path:
            return PackageManagerInfo(
                type=PackageManagerType.APT,
                available=False,
                error="apt-get not found (not a Debian/Ubuntu system?)",
            )

        # 检查是否需要 sudo
        is_root = os.getuid() == 0 if hasattr(os, 'getuid') else False
        requires_sudo = not is_root

        # 获取版本
        code, stdout, stderr = self._run_command(["apt-get", "--version"])
        version = None
        if code == 0:
            # apt 2.4.11 (amd64)
            match = re.search(r"apt\s+(\d+\.\d+\.\d+)", stdout)
            if match:
                version = match.group(1)

        return PackageManagerInfo(
            type=PackageManagerType.APT,
            available=True,
            version=version,
            path=path,
            requires_sudo=requires_sudo,
        )

    def _detect_pip(self) -> PackageManagerInfo:
        """检测 pip"""
        # 优先使用 pip3
        pip_cmd = "pip3" if shutil.which("pip3") else "pip"
        path = shutil.which(pip_cmd)

        if not path:
            return PackageManagerInfo(
                type=PackageManagerType.PIP,
                available=False,
                error="pip not found",
            )

        code, stdout, stderr = self._run_command([pip_cmd, "--version"])
        version = None
        if code == 0:
            # pip 23.3.1 from /usr/lib/python3/dist-packages/pip (python 3.11)
            match = re.search(r"pip\s+(\d+\.\d+(?:\.\d+)?)", stdout)
            if match:
                version = match.group(1)

        return PackageManagerInfo(
            type=PackageManagerType.PIP,
            available=True,
            version=version,
            path=path,
            requires_sudo=False,
        )

    def _detect_npm(self) -> PackageManagerInfo:
        """检测 npm"""
        path = shutil.which("npm")
        if not path:
            return PackageManagerInfo(
                type=PackageManagerType.NPM,
                available=False,
                error="npm not found",
            )

        code, stdout, stderr = self._run_command(["npm", "--version"])
        version = stdout.strip() if code == 0 else None

        return PackageManagerInfo(
            type=PackageManagerType.NPM,
            available=True,
            version=version,
            path=path,
            requires_sudo=False,
        )

    # ==================== 包查询 ====================

    def is_package_installed(
        self,
        pm_type: PackageManagerType,
        package: str,
    ) -> bool:
        """
        检查包是否已安装

        Args:
            pm_type: 包管理器类型
            package: 包名

        Returns:
            是否已安装
        """
        info = self.get_package_info(pm_type, package)
        return info.installed if info else False

    def get_package_info(
        self,
        pm_type: PackageManagerType,
        package: str,
    ) -> Optional[PackageInfo]:
        """
        获取包信息

        Args:
            pm_type: 包管理器类型
            package: 包名

        Returns:
            PackageInfo 对象，或 None
        """
        pm_info = self.detect_package_manager(pm_type)
        if not pm_info.available:
            return None

        if pm_type == PackageManagerType.BREW:
            return self._get_brew_package_info(package)
        elif pm_type == PackageManagerType.APT:
            return self._get_apt_package_info(package)
        elif pm_type == PackageManagerType.PIP:
            return self._get_pip_package_info(package)
        elif pm_type == PackageManagerType.NPM:
            return self._get_npm_package_info(package)

        return None

    def _get_brew_package_info(self, package: str) -> PackageInfo:
        """获取 brew 包信息"""
        code, stdout, stderr = self._run_command(["brew", "list", package])
        installed = code == 0

        version = None
        if installed:
            # 尝试获取版本
            code, stdout, stderr = self._run_command(
                ["brew", "info", "--json=v2", package]
            )
            if code == 0:
                try:
                    import json
                    data = json.loads(stdout)
                    formulae = data.get("formulae", [])
                    if formulae:
                        versions = formulae[0].get("installed", [])
                        if versions:
                            version = versions[0].get("version")
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

        return PackageInfo(
            name=package,
            version=version,
            installed=installed,
        )

    def _get_apt_package_info(self, package: str) -> PackageInfo:
        """获取 apt 包信息"""
        code, stdout, stderr = self._run_command(
            ["dpkg-query", "-W", "-f=${Status} ${Version}", package]
        )

        installed = False
        version = None

        if code == 0 and "install ok installed" in stdout:
            installed = True
            # 提取版本
            parts = stdout.split()
            if len(parts) >= 4:
                version = parts[-1]

        return PackageInfo(
            name=package,
            version=version,
            installed=installed,
        )

    def _get_pip_package_info(self, package: str) -> PackageInfo:
        """获取 pip 包信息"""
        pip_cmd = "pip3" if shutil.which("pip3") else "pip"
        code, stdout, stderr = self._run_command([pip_cmd, "show", package])

        installed = code == 0
        version = None
        description = None

        if installed:
            for line in stdout.split("\n"):
                if line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
                elif line.startswith("Summary:"):
                    description = line.split(":", 1)[1].strip()

        return PackageInfo(
            name=package,
            version=version,
            installed=installed,
            description=description,
        )

    def _get_npm_package_info(self, package: str) -> PackageInfo:
        """获取 npm 全局包信息"""
        code, stdout, stderr = self._run_command(
            ["npm", "list", "-g", package, "--depth=0"]
        )

        installed = code == 0 and package in stdout
        version = None

        if installed:
            # package@1.2.3
            match = re.search(rf"{re.escape(package)}@(\d+\.\d+\.\d+)", stdout)
            if match:
                version = match.group(1)

        return PackageInfo(
            name=package,
            version=version,
            installed=installed,
        )

    # ==================== 推荐安装方式 ====================

    def recommend_install_method(
        self,
        binary_name: str,
        package_mappings: Optional[Dict[PackageManagerType, str]] = None,
    ) -> Optional[Tuple[PackageManagerType, str]]:
        """
        推荐安装方式

        Args:
            binary_name: 需要安装的二进制文件名
            package_mappings: {包管理器类型: 包名} 映射

        Returns:
            (推荐的包管理器类型, 包名) 或 None
        """
        available_pms = self.get_available_package_managers()
        if not available_pms:
            return None

        # 优先级：brew > apt > pip > npm
        priority = [
            PackageManagerType.BREW,
            PackageManagerType.APT,
            PackageManagerType.PIP,
            PackageManagerType.NPM,
        ]

        for pm_type in priority:
            pm_info = next(
                (pm for pm in available_pms if pm.type == pm_type),
                None,
            )
            if pm_info:
                if package_mappings and pm_type in package_mappings:
                    return pm_type, package_mappings[pm_type]
                # 默认使用二进制名作为包名
                return pm_type, binary_name

        return None

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()


def get_package_manager(timeout: int = 30) -> PackageManager:
    """获取 PackageManager 实例"""
    return PackageManager(timeout=timeout)
