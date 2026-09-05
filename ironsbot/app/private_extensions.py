# SPDX-License-Identifier: MIT
"""Install and validate private extension packages."""

from __future__ import annotations

import logging
import re
import shutil
import sys
import tarfile
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from ironsbot.services.operations.docker_models import (
    DockerImageArchiveRequest,
    DockerRegistryCredentials,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.config.models.operations import (
        DockerUpdateConfig,
        PrivateExtensionsConfig,
    )
    from ironsbot.services.operations.docker_models import DockerImageArchive

PRIVATE_EXTENSIONS_ROOT = "ironsbot_extensions"
PRIVATE_EXTENSIONS_MANIFEST = "pyproject.toml"
PRIVATE_EXTENSIONS_CURRENT_DIRECTORY = "current"
MAX_PRIVATE_EXTENSION_ARCHIVE_BYTES = 16 * 1024 * 1024
_PYTHON_MODULE_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z"
)
_PRIVATE_MODULE_PREFIX = "ironsbot_private_"
logger = logging.getLogger(__name__)

try:
    import tomllib  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib  # pyright: ignore[reportMissingImports]


class PrivateExtensionError(RuntimeError):
    pass


class PrivateExtensionArtifactGateway(Protocol):
    async def fetch_image_archive(
        self,
        request: DockerImageArchiveRequest,
    ) -> DockerImageArchive: ...


@dataclass(frozen=True, slots=True)
class PrivateExtensionManifest:
    """Validated standard NoneBot plugin declaration from a private package."""

    plugin_modules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PrivateExtensionInstallResult:
    installed: bool
    message: str = ""
    image_id: str = ""
    plugin_modules: tuple[str, ...] = ()


class PrivateExtensionCatalog:
    """Validated private manifest plus its temporary import root."""

    def __init__(
        self,
        root: Path | None,
        manifest: PrivateExtensionManifest | None = None,
        *,
        reason: str = "",
    ) -> None:
        self._root = root
        self._manifest = manifest
        self._reason = reason

    @classmethod
    def unavailable(cls, reason: str) -> PrivateExtensionCatalog:
        return cls(None, reason=reason)

    @classmethod
    def from_config(cls, config: PrivateExtensionsConfig) -> PrivateExtensionCatalog:
        if not config.enabled:
            return cls.unavailable("private extensions are disabled")
        root = Path(config.data_path) / PRIVATE_EXTENSIONS_CURRENT_DIRECTORY
        try:
            manifest = _load_manifest(root)
        except FileNotFoundError:
            return cls.unavailable("private extension package is not installed")
        except PrivateExtensionError as error:
            logger.warning("private extension package is invalid: %s", error)
            return cls.unavailable("private extension package is invalid")
        return cls(root, manifest)

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def manifest_path(self) -> Path | None:
        if self._root is None or self._manifest is None:
            return None
        return self._root / PRIVATE_EXTENSIONS_MANIFEST

    @property
    def plugin_modules(self) -> tuple[str, ...]:
        if self._manifest is None:
            return ()
        return self._manifest.plugin_modules

    @contextmanager
    def plugin_import_path(self) -> Iterator[None]:
        """Expose the package root only while NoneBot loads its manifest."""

        if self._root is None:
            yield
            return
        root_text = str(self._root.resolve())
        inserted = root_text not in sys.path
        if inserted:
            sys.path.insert(0, root_text)
        try:
            yield
        finally:
            if inserted:
                sys.path.remove(root_text)


def load_private_extension_catalog(
    config: PrivateExtensionsConfig,
) -> PrivateExtensionCatalog:
    """Load the last successfully installed package for application composition."""

    return PrivateExtensionCatalog.from_config(config)


class PrivateExtensionInstaller:
    """Refresh a private package before the public NoneBot process starts."""

    def __init__(
        self,
        config: PrivateExtensionsConfig,
        docker_update: DockerUpdateConfig,
        docker: PrivateExtensionArtifactGateway,
    ) -> None:
        self._config = config
        self._docker_update = docker_update
        self._docker = docker

    async def install(self) -> PrivateExtensionInstallResult:
        if not self._config.enabled:
            return PrivateExtensionInstallResult(
                installed=False,
                message="private extensions are disabled",
            )
        request = DockerImageArchiveRequest(
            image=str(self._config.image),
            archive_path=str(self._config.archive_path),
            socket_path=str(self._docker_update.docker_socket_path),
            timeout_seconds=float(self._config.timeout_seconds),
            registry_credentials=_registry_credentials(self._docker_update),
        )
        try:
            artifact = await self._docker.fetch_image_archive(request)
            manifest = install_private_extension_archive(
                artifact.content,
                Path(self._config.data_path),
            )
        except Exception as error:  # noqa: BLE001 - optional package cannot block boot
            logger.warning(
                "private extension refresh failed: image=%s error_type=%s error=%s",
                self._config.image,
                type(error).__name__,
                error,
            )
            return PrivateExtensionInstallResult(
                installed=False,
                message="private extension refresh failed",
            )
        plugin_modules = manifest.plugin_modules
        logger.info(
            "private extensions installed: image=%s image_id=%s plugins=%s",
            self._config.image,
            artifact.image.image_id[:19],
            ",".join(plugin_modules),
        )
        return PrivateExtensionInstallResult(
            installed=True,
            image_id=artifact.image.image_id,
            plugin_modules=plugin_modules,
        )


def _registry_credentials(
    config: DockerUpdateConfig,
) -> DockerRegistryCredentials | None:
    username = str(config.registry_username).strip()
    token = str(config.registry_token).strip()
    if not username and not token:
        return None
    return DockerRegistryCredentials(username=username, token=token)


def install_private_extension_archive(
    content: bytes,
    destination_root: Path,
) -> PrivateExtensionManifest:
    """Safely install a package archive without replacing a valid old package."""

    if len(content) > MAX_PRIVATE_EXTENSION_ARCHIVE_BYTES:
        msg = "private extension archive is too large"
        raise PrivateExtensionError(msg)
    destination_root.mkdir(parents=True, exist_ok=True)
    staging = destination_root / f".staging-{uuid4().hex}"
    try:
        _extract_private_extension_archive(content, staging)
        manifest = _load_manifest(staging)
        _replace_current_extension_package(destination_root, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def _extract_private_extension_archive(content: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    destination_resolved = destination.resolve()
    try:
        with tarfile.open(fileobj=BytesIO(content), mode="r:*") as archive:
            _extract_private_extension_members(
                archive,
                destination,
                destination_resolved,
            )
    except tarfile.TarError as error:
        msg = "private extension archive is not a tar archive"
        raise PrivateExtensionError(msg) from error


def _extract_private_extension_members(
    archive: tarfile.TarFile,
    destination: Path,
    destination_resolved: Path,
) -> None:
    for member in archive.getmembers():
        relative = _archive_member_relative_path(member.name)
        if relative is None:
            continue
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            msg = f"private extension archive contains unsafe entry: {member.name}"
            raise PrivateExtensionError(msg)
        target = destination.joinpath(*relative.parts)
        try:
            target.resolve().relative_to(destination_resolved)
        except ValueError as error:
            msg = f"private extension archive escapes destination: {member.name}"
            raise PrivateExtensionError(msg) from error
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not member.isfile():
            msg = f"private extension archive contains unsupported entry: {member.name}"
            raise PrivateExtensionError(msg)
        if target.exists():
            msg = f"private extension archive contains duplicate entry: {member.name}"
            raise PrivateExtensionError(msg)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            msg = f"private extension archive cannot read entry: {member.name}"
            raise PrivateExtensionError(msg)
        with source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def _archive_member_relative_path(member_name: str) -> PurePosixPath | None:
    path = PurePosixPath(member_name)
    parts = path.parts
    if not parts or parts[0] != PRIVATE_EXTENSIONS_ROOT:
        msg = (
            "private extension archive entry is outside "
            f"{PRIVATE_EXTENSIONS_ROOT}: {member_name}"
        )
        raise PrivateExtensionError(msg)
    relative_parts = parts[1:]
    if not relative_parts:
        return None
    if any(part in {"", ".", ".."} for part in relative_parts):
        msg = f"private extension archive has an invalid path: {member_name}"
        raise PrivateExtensionError(msg)
    return PurePosixPath(*relative_parts)


def _load_manifest(root: Path) -> PrivateExtensionManifest:
    manifest_path = root / PRIVATE_EXTENSIONS_MANIFEST
    try:
        payload = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        msg = "private extension manifest is not valid TOML"
        raise PrivateExtensionError(msg) from error
    return PrivateExtensionManifest(
        plugin_modules=_private_plugin_modules(_nonebot_manifest_table(payload), root)
    )


def _nonebot_manifest_table(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        msg = "private extension manifest must be an object"
        raise PrivateExtensionError(msg)
    tool = payload.get("tool")
    if not isinstance(tool, dict):
        msg = "private extension manifest has no tool table"
        raise PrivateExtensionError(msg)
    nonebot = tool.get("nonebot")
    if not isinstance(nonebot, dict):
        msg = "private extension manifest has no [tool.nonebot] table"
        raise PrivateExtensionError(msg)
    return nonebot


def _private_plugin_modules(
    nonebot: dict[str, object],
    root: Path,
) -> tuple[str, ...]:
    if nonebot.get("plugin_dirs", []) != []:
        msg = "private extension manifest must not declare plugin_dirs"
        raise PrivateExtensionError(msg)
    raw_plugins = nonebot.get("plugins")
    if not isinstance(raw_plugins, dict) or not raw_plugins:
        msg = "private extension manifest has no [tool.nonebot.plugins] table"
        raise PrivateExtensionError(msg)

    modules: list[str] = []
    for source, raw_modules in raw_plugins.items():
        if not isinstance(source, str) or not isinstance(raw_modules, list):
            msg = "private extension plugins must map string sources to module lists"
            raise PrivateExtensionError(msg)
        for module in raw_modules:
            _validate_private_plugin_module(module, root)
            modules.append(module)
    if not modules:
        msg = "private extension manifest has no plugin modules"
        raise PrivateExtensionError(msg)
    if len(set(modules)) != len(modules):
        msg = "private extension manifest repeats a plugin module"
        raise PrivateExtensionError(msg)
    return tuple(modules)


def _validate_private_plugin_module(module: object, root: Path) -> None:
    if not isinstance(module, str) or not _PYTHON_MODULE_PATTERN.fullmatch(module):
        msg = "private extension plugin module is invalid"
        raise PrivateExtensionError(msg)
    parts = module.split(".")
    if not parts[0].startswith(_PRIVATE_MODULE_PREFIX):
        msg = f"private extension plugin module is outside its package: {module}"
        raise PrivateExtensionError(msg)
    module_file = root.joinpath(*parts).with_suffix(".py")
    package_file = root.joinpath(*parts, "__init__.py")
    if not module_file.is_file() and not package_file.is_file():
        msg = f"private extension plugin module does not exist: {module}"
        raise PrivateExtensionError(msg)


def _replace_current_extension_package(destination_root: Path, staging: Path) -> None:
    current = destination_root / PRIVATE_EXTENSIONS_CURRENT_DIRECTORY
    previous = destination_root / f".previous-{uuid4().hex}"
    moved_current = False
    try:
        if current.exists():
            _move_extension_directory(current, previous)
            moved_current = True
        _move_extension_directory(staging, current)
    except Exception:
        if moved_current and previous.exists() and not current.exists():
            _move_extension_directory(previous, current)
        raise
    finally:
        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)


def _move_extension_directory(source: Path, destination: Path) -> None:
    """Move an extension directory, with a Windows-compatible fallback."""

    try:
        source.rename(destination)
    except OSError:
        shutil.move(str(source), str(destination))
