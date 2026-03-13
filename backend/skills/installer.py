"""Skill 依赖安装器

支持多种包管理器自动安装 Skill 依赖：
- brew (macOS/Linux)
- pip (Python)
- npm (Node.js)
- apt (Debian/Ubuntu)
- download (直接下载)
"""

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen
from urllib.error import URLError

from .types import InstallKind, InstallResult, SkillEntry, SkillInstallSpec, SkillMetadata
from .package_manager import (
    PackageManager,
    PackageManagerType,
    PackageManagerInfo,
    BinaryInfo,
    get_package_manager,
)

logger = logging.getLogger(__name__)


class SkillInstaller:
    """Skill 依赖安装器"""

    def __init__(
        self,
        timeout: int = 300,
        prefer_brew: bool = True,
        pip_user: bool = True,
        package_manager: Optional[PackageManager] = None,
    ):
        """
        初始化安装器

        Args:
            timeout: 命令执行超时时间（秒）
            prefer_brew: 是否优先使用 brew
            pip_user: pip 是否使用 --user 安装
            package_manager: 包管理器实例（可选）
        """
        self.timeout = timeout
        self.prefer_brew = prefer_brew
        self.pip_user = pip_user
        self._current_os = platform.system().lower()
        self._pm = package_manager or get_package_manager(timeout=min(timeout, 30))

    @property
    def package_manager(self) -> PackageManager:
        """获取包管理器实例"""
        return self._pm

    def has_binary(self, name: str) -> bool:
        """检查二进制文件是否存在"""
        return self._pm.check_binary(name).exists

    def get_binary_info(self, name: str) -> BinaryInfo:
        """
        获取二进制文件详细信息

        Args:
            name: 二进制文件名

        Returns:
            BinaryInfo 对象
        """
        return self._pm.check_binary(name)

    def get_available_package_managers(self) -> List[PackageManagerInfo]:
        """
        获取所有可用的包管理器

        Returns:
            可用的 PackageManagerInfo 列表
        """
        return self._pm.get_available_package_managers()

    def detect_package_manager(
        self,
        pm_type: PackageManagerType,
    ) -> PackageManagerInfo:
        """
        检测指定包管理器是否可用

        Args:
            pm_type: 包管理器类型

        Returns:
            PackageManagerInfo 对象
        """
        return self._pm.detect_package_manager(pm_type)

    def check_dependencies(self, entry: SkillEntry) -> Tuple[bool, List[str]]:
        """
        检查 Skill 依赖是否满足

        Args:
            entry: Skill 条目

        Returns:
            (是否满足, 缺失的依赖列表)
        """
        if not entry.metadata or not entry.metadata.requires:
            return True, []

        missing = []
        bins = entry.metadata.requires.get("bins", [])
        for bin_name in bins:
            if not self.has_binary(bin_name):
                missing.append(bin_name)

        return len(missing) == 0, missing

    def find_install_spec(
        self,
        entry: SkillEntry,
        install_id: Optional[str] = None,
    ) -> Optional[SkillInstallSpec]:
        """
        查找安装规格

        Args:
            entry: Skill 条目
            install_id: 安装规格 ID（可选）

        Returns:
            匹配的安装规格，或 None
        """
        if not entry.metadata or not entry.metadata.install:
            return None

        specs = entry.metadata.install
        if not specs:
            return None

        # 如果指定了 ID，查找匹配的
        if install_id:
            for i, spec in enumerate(specs):
                spec_id = spec.id or f"{spec.kind.value}-{i}"
                if spec_id == install_id:
                    return spec
            return None

        # 否则返回第一个适用于当前 OS 的
        for spec in specs:
            if self._is_spec_applicable(spec):
                return spec

        return None

    def _is_spec_applicable(self, spec: SkillInstallSpec) -> bool:
        """检查安装规格是否适用于当前系统"""
        if spec.os:
            if self._current_os not in [os.lower() for os in spec.os]:
                return False

        # 检查包管理器是否可用
        if spec.kind == InstallKind.BREW:
            return self.has_binary("brew")
        elif spec.kind == InstallKind.APT:
            return self.has_binary("apt-get")
        elif spec.kind == InstallKind.PIP:
            return self.has_binary("pip") or self.has_binary("pip3")
        elif spec.kind == InstallKind.NPM:
            return self.has_binary("npm")
        elif spec.kind == InstallKind.DOWNLOAD:
            return True

        return False

    def install(
        self,
        entry: SkillEntry,
        install_id: Optional[str] = None,
    ) -> InstallResult:
        """
        安装 Skill 依赖

        Args:
            entry: Skill 条目
            install_id: 安装规格 ID（可选）

        Returns:
            安装结果
        """
        # 检查是否已满足依赖
        satisfied, missing = self.check_dependencies(entry)
        if satisfied:
            return InstallResult(
                ok=True,
                message="Dependencies already satisfied",
            )

        # 查找安装规格
        spec = self.find_install_spec(entry, install_id)
        if not spec:
            return InstallResult(
                ok=False,
                message=f"No applicable install spec found for skill '{entry.name}'. "
                        f"Missing binaries: {', '.join(missing)}",
            )

        # 执行安装
        return self._execute_install(spec)

    def _execute_install(self, spec: SkillInstallSpec) -> InstallResult:
        """执行安装"""
        try:
            if spec.kind == InstallKind.BREW:
                return self._install_brew(spec)
            elif spec.kind == InstallKind.PIP:
                return self._install_pip(spec)
            elif spec.kind == InstallKind.NPM:
                return self._install_npm(spec)
            elif spec.kind == InstallKind.APT:
                return self._install_apt(spec)
            elif spec.kind == InstallKind.DOWNLOAD:
                return self._install_download(spec)
            else:
                return InstallResult(
                    ok=False,
                    message=f"Unsupported install kind: {spec.kind}",
                )
        except Exception as e:
            logger.exception(f"Install failed: {e}")
            return InstallResult(
                ok=False,
                message=f"Install failed: {str(e)}",
            )

    def _run_command(
        self,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """
        运行命令

        Args:
            args: 命令参数列表
            env: 环境变量

        Returns:
            (返回码, stdout, stderr)
        """
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=full_env,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {self.timeout}s"
        except Exception as e:
            return -1, "", str(e)

    def _install_brew(self, spec: SkillInstallSpec) -> InstallResult:
        """使用 brew 安装"""
        if not spec.formula:
            return InstallResult(
                ok=False,
                message="Missing brew formula in install spec",
            )

        if not self.has_binary("brew"):
            return InstallResult(
                ok=False,
                message="Homebrew is not installed. Install from https://brew.sh",
            )

        args = ["brew", "install", spec.formula]
        code, stdout, stderr = self._run_command(args)

        if code == 0:
            return InstallResult(
                ok=True,
                message=f"Successfully installed {spec.formula} via brew",
                stdout=stdout,
                stderr=stderr,
                code=code,
            )
        else:
            return InstallResult(
                ok=False,
                message=f"Failed to install {spec.formula} via brew",
                stdout=stdout,
                stderr=stderr,
                code=code,
            )

    def _install_pip(self, spec: SkillInstallSpec) -> InstallResult:
        """使用 pip 安装"""
        if not spec.package:
            return InstallResult(
                ok=False,
                message="Missing pip package in install spec",
            )

        # 优先使用 pip3
        pip_cmd = "pip3" if self.has_binary("pip3") else "pip"
        if not self.has_binary(pip_cmd):
            return InstallResult(
                ok=False,
                message="pip is not installed",
            )

        args = [pip_cmd, "install"]
        if self.pip_user:
            args.append("--user")
        args.append(spec.package)

        code, stdout, stderr = self._run_command(args)

        if code == 0:
            return InstallResult(
                ok=True,
                message=f"Successfully installed {spec.package} via pip",
                stdout=stdout,
                stderr=stderr,
                code=code,
            )
        else:
            return InstallResult(
                ok=False,
                message=f"Failed to install {spec.package} via pip",
                stdout=stdout,
                stderr=stderr,
                code=code,
            )

    def _install_npm(self, spec: SkillInstallSpec) -> InstallResult:
        """使用 npm 安装"""
        package = spec.npm_package or spec.package
        if not package:
            return InstallResult(
                ok=False,
                message="Missing npm package in install spec",
            )

        if not self.has_binary("npm"):
            return InstallResult(
                ok=False,
                message="npm is not installed",
            )

        args = ["npm", "install", "-g", package]
        code, stdout, stderr = self._run_command(args)

        if code == 0:
            return InstallResult(
                ok=True,
                message=f"Successfully installed {package} via npm",
                stdout=stdout,
                stderr=stderr,
                code=code,
            )
        else:
            return InstallResult(
                ok=False,
                message=f"Failed to install {package} via npm",
                stdout=stdout,
                stderr=stderr,
                code=code,
            )

    def _install_apt(self, spec: SkillInstallSpec) -> InstallResult:
        """使用 apt 安装"""
        package = spec.apt_package or spec.package
        if not package:
            return InstallResult(
                ok=False,
                message="Missing apt package in install spec",
            )

        if not self.has_binary("apt-get"):
            return InstallResult(
                ok=False,
                message="apt-get is not available (not a Debian/Ubuntu system?)",
            )

        # 检查是否需要 sudo
        is_root = os.getuid() == 0 if hasattr(os, 'getuid') else False
        
        if is_root:
            args = ["apt-get", "install", "-y", package]
        elif self.has_binary("sudo"):
            # 检查 sudo 是否可用（无密码）
            check_code, _, _ = self._run_command(["sudo", "-n", "true"])
            if check_code != 0:
                return InstallResult(
                    ok=False,
                    message=f"apt-get requires sudo, but sudo is not available without password. "
                            f"Please install {package} manually: sudo apt-get install {package}",
                )
            args = ["sudo", "apt-get", "install", "-y", package]
        else:
            return InstallResult(
                ok=False,
                message=f"apt-get requires root privileges. "
                        f"Please install {package} manually: sudo apt-get install {package}",
            )

        code, stdout, stderr = self._run_command(args)

        if code == 0:
            return InstallResult(
                ok=True,
                message=f"Successfully installed {package} via apt",
                stdout=stdout,
                stderr=stderr,
                code=code,
            )
        else:
            return InstallResult(
                ok=False,
                message=f"Failed to install {package} via apt",
                stdout=stdout,
                stderr=stderr,
                code=code,
            )

    def _install_download(self, spec: SkillInstallSpec) -> InstallResult:
        """直接下载安装"""
        if not spec.url:
            return InstallResult(
                ok=False,
                message="Missing download URL in install spec",
            )

        target_dir = spec.target_dir or str(Path.home() / ".local" / "bin")
        target_path = Path(target_dir)
        target_path.mkdir(parents=True, exist_ok=True)

        try:
            with urlopen(spec.url, timeout=self.timeout) as response:
                content = response.read()

            if spec.extract:
                # 解压到目标目录
                return self._extract_archive(content, spec.url, target_path)
            else:
                # 直接保存为可执行文件
                filename = Path(spec.url).name
                file_path = target_path / filename
                file_path.write_bytes(content)
                file_path.chmod(0o755)
                return InstallResult(
                    ok=True,
                    message=f"Downloaded {filename} to {target_path}",
                )

        except URLError as e:
            return InstallResult(
                ok=False,
                message=f"Failed to download from {spec.url}: {e}",
            )
        except Exception as e:
            return InstallResult(
                ok=False,
                message=f"Download install failed: {e}",
            )

    def _extract_archive(
        self,
        content: bytes,
        url: str,
        target_path: Path,
    ) -> InstallResult:
        """解压归档文件"""
        import tarfile
        import zipfile
        from io import BytesIO

        try:
            if url.endswith(".tar.gz") or url.endswith(".tgz"):
                with tarfile.open(fileobj=BytesIO(content), mode="r:gz") as tar:
                    tar.extractall(path=target_path)
            elif url.endswith(".tar.bz2"):
                with tarfile.open(fileobj=BytesIO(content), mode="r:bz2") as tar:
                    tar.extractall(path=target_path)
            elif url.endswith(".zip"):
                with zipfile.ZipFile(BytesIO(content)) as zf:
                    zf.extractall(path=target_path)
            else:
                return InstallResult(
                    ok=False,
                    message=f"Unsupported archive format: {url}",
                )

            return InstallResult(
                ok=True,
                message=f"Extracted archive to {target_path}",
            )

        except Exception as e:
            return InstallResult(
                ok=False,
                message=f"Failed to extract archive: {e}",
            )

    def install_missing_dependencies(
        self,
        entry: SkillEntry,
    ) -> List[InstallResult]:
        """
        安装所有缺失的依赖

        Args:
            entry: Skill 条目

        Returns:
            每个安装规格的结果列表
        """
        results = []

        if not entry.metadata or not entry.metadata.install:
            satisfied, missing = self.check_dependencies(entry)
            if not satisfied:
                results.append(InstallResult(
                    ok=False,
                    message=f"No install specs available. Missing: {', '.join(missing)}",
                ))
            return results

        # 尝试每个安装规格
        for i, spec in enumerate(entry.metadata.install):
            if not self._is_spec_applicable(spec):
                continue

            # 检查此规格提供的二进制是否已存在
            if spec.bins:
                all_present = all(self.has_binary(b) for b in spec.bins)
                if all_present:
                    continue

            result = self._execute_install(spec)
            results.append(result)

            # 如果安装成功，检查依赖是否满足
            if result.ok:
                satisfied, _ = self.check_dependencies(entry)
                if satisfied:
                    break

        return results


def get_installer(**kwargs) -> SkillInstaller:
    """获取 SkillInstaller 实例"""
    return SkillInstaller(**kwargs)
