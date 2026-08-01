# SPDX-License-Identifier: MIT
"""Install and load validated private extension packages."""

from __future__ import annotations

import importlib
import json
import logging
import re
import shutil
import sys
import tarfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol, cast
from uuid import uuid4

from ironsbot.services.operations.docker_models import (
    DockerImageArchiveRequest,
    DockerRegistryCredentials,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ironsbot.config.models.operations import (
        DockerUpdateConfig,
        PrivateExtensionsConfig,
    )
    from ironsbot.core.features import FeatureService
    from ironsbot.integrations.scheduler.facade import SchedulerFacade
    from ironsbot.runtime.plugins import PluginDefinition
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.operations.docker_models import DockerImageArchive
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.headless_session import HeadlessSessionFactory
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionRegistry,
    )
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer
    from ironsbot.services.seer.resources import SeerQueryResources

PRIVATE_EXTENSIONS_ROOT = "ironsbot_extensions"
PRIVATE_EXTENSIONS_MANIFEST = "manifest.json"
PRIVATE_EXTENSIONS_CURRENT_DIRECTORY = "current"
PRIVATE_EXTENSIONS_SCHEMA_VERSION = 1
MAX_PRIVATE_EXTENSION_ARCHIVE_BYTES = 16 * 1024 * 1024
_EXTENSION_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
_PYTHON_MODULE_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z"
)
logger = logging.getLogger(__name__)


class PrivateExtensionError(RuntimeError):
    pass


class PrivateExtensionArtifactGateway(Protocol):
    async def fetch_image_archive(
        self,
        request: DockerImageArchiveRequest,
    ) -> DockerImageArchive: ...


@dataclass(frozen=True, slots=True)
class PrivateExtensionRuntime:
    """Public dependencies intentionally exposed to trusted private plugins."""

    features: FeatureService
    seer: SeerQueryResources
    headless: HeadlessService
    headless_sessions: HeadlessSessionFactory
    data: SeerDataAccess
    images: SeerImageSource
    render_html: HtmlTemplateRenderer
    error_message: ErrorMessageLookup
    player_quotas: PlayerQueryQuotaService
    player_requests: PlayerRequestProtectionService
    player_details: PlayerDetailExtensionRegistry
    scheduler: SchedulerFacade
    admin_notices: AdminNoticeService
    settings: Mapping[str, Mapping[str, Any]]

    def settings_for(self, extension_id: str) -> Mapping[str, Any]:
        return self.settings.get(extension_id, {})


@dataclass(frozen=True, slots=True)
class PrivateExtensionEntry:
    id: str
    path: PurePosixPath
    module: str
    factory: str


@dataclass(frozen=True, slots=True)
class PrivateExtensionInstallResult:
    installed: bool
    message: str = ""
    image_id: str = ""
    extension_ids: tuple[str, ...] = ()


class PrivateExtensionCatalog:
    """Validated package metadata plus controlled module loading."""

    def __init__(
        self,
        root: Path | None,
        entries: dict[str, PrivateExtensionEntry] | None = None,
        *,
        reason: str = "",
    ) -> None:
        self._root = root
        self._entries = entries or {}
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
            entries = _load_manifest(root)
        except FileNotFoundError:
            return cls.unavailable("private extension package is not installed")
        except PrivateExtensionError as error:
            logger.warning("private extension package is invalid: %s", error)
            return cls.unavailable("private extension package is invalid")
        return cls(root, entries)

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def extension_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def load_plugin_definitions(
        self,
        runtime: PrivateExtensionRuntime,
    ) -> tuple[PluginDefinition, ...]:
        """Load definitions from the installed, validated extension package."""

        definitions: list[PluginDefinition] = []
        for entry in self._entries.values():
            factory = self._load_factory(entry)
            if factory is None:
                continue
            try:
                definition = factory(runtime)
            except Exception:  # noqa: BLE001 - optional code must not stop boot
                logger.warning(
                    "private extension factory failed: id=%s",
                    entry.id,
                    exc_info=True,
                )
                continue
            from ironsbot.runtime.plugins import PluginDefinition

            if not isinstance(definition, PluginDefinition):
                logger.warning(
                    "private extension factory returned an invalid plugin: id=%s",
                    entry.id,
                )
                continue
            definitions.append(definition)
        return tuple(definitions)

    def _load_factory(
        self,
        entry: PrivateExtensionEntry,
    ) -> Callable[..., Any] | None:
        if self._root is None:
            return None
        source_root = self._root.joinpath(*entry.path.parts)
        if not source_root.is_dir():
            logger.warning(
                "private extension source path is missing: id=%s path=%s",
                entry.id,
                source_root,
            )
            return None
        source_root_text = str(source_root.resolve())
        if source_root_text not in sys.path:
            sys.path.insert(0, source_root_text)
        importlib.invalidate_caches()
        try:
            imported = importlib.import_module(entry.module)
        except Exception:  # noqa: BLE001 - optional extension must not stop boot
            logger.warning(
                "private extension import failed: id=%s module=%s",
                entry.id,
                entry.module,
                exc_info=True,
            )
            return None
        candidate = getattr(imported, entry.factory, None)
        if not callable(candidate):
            logger.warning(
                "private extension factory is missing: id=%s module=%s factory=%s",
                entry.id,
                entry.module,
                entry.factory,
            )
            return None
        return cast("Callable[..., Any]", candidate)


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
            entries = install_private_extension_archive(
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
        extension_ids = tuple(sorted(entries))
        logger.info(
            "private extensions installed: image=%s image_id=%s extensions=%s",
            self._config.image,
            artifact.image.image_id[:19],
            ",".join(extension_ids),
        )
        return PrivateExtensionInstallResult(
            installed=True,
            image_id=artifact.image.image_id,
            extension_ids=extension_ids,
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
) -> dict[str, PrivateExtensionEntry]:
    """Safely install a package archive without replacing a valid old package."""

    if len(content) > MAX_PRIVATE_EXTENSION_ARCHIVE_BYTES:
        msg = "private extension archive is too large"
        raise PrivateExtensionError(msg)
    destination_root.mkdir(parents=True, exist_ok=True)
    staging = destination_root / f".staging-{uuid4().hex}"
    try:
        _extract_private_extension_archive(content, staging)
        entries = _load_manifest(staging)
        _replace_current_extension_package(destination_root, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return entries


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
            msg = (
                "private extension archive contains unsupported entry: "
                f"{member.name}"
            )
            raise PrivateExtensionError(msg)
        if target.exists():
            msg = (
                "private extension archive contains duplicate entry: "
                f"{member.name}"
            )
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


def _load_manifest(root: Path) -> dict[str, PrivateExtensionEntry]:
    manifest_path = root / PRIVATE_EXTENSIONS_MANIFEST
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        msg = "private extension manifest is not valid JSON"
        raise PrivateExtensionError(msg) from error
    if not isinstance(payload, dict):
        msg = "private extension manifest must be an object"
        raise PrivateExtensionError(msg)
    if payload.get("schema_version") != PRIVATE_EXTENSIONS_SCHEMA_VERSION:
        msg = "private extension manifest has an unsupported schema version"
        raise PrivateExtensionError(msg)
    raw_extensions = payload.get("extensions")
    if not isinstance(raw_extensions, list) or not raw_extensions:
        msg = "private extension manifest has no extensions"
        raise PrivateExtensionError(msg)

    entries: dict[str, PrivateExtensionEntry] = {}
    for raw_entry in raw_extensions:
        entry = _parse_manifest_entry(raw_entry, root)
        if entry.id in entries:
            msg = f"private extension manifest repeats id: {entry.id}"
            raise PrivateExtensionError(msg)
        entries[entry.id] = entry
    return entries


def _parse_manifest_entry(  # noqa: C901 - explicit manifest diagnostics
    raw_entry: object,
    root: Path,
) -> PrivateExtensionEntry:
    if not isinstance(raw_entry, dict):
        msg = "private extension manifest entry must be an object"
        raise PrivateExtensionError(msg)
    extension_id = raw_entry.get("id")
    source_path = raw_entry.get("path")
    module = raw_entry.get("module")
    factory = raw_entry.get("factory")
    if not isinstance(extension_id, str):
        msg = "private extension manifest entry id must be a string"
        raise PrivateExtensionError(msg)
    if not isinstance(source_path, str):
        msg = "private extension manifest entry path must be a string"
        raise PrivateExtensionError(msg)
    if not isinstance(module, str):
        msg = "private extension manifest entry module must be a string"
        raise PrivateExtensionError(msg)
    if not isinstance(factory, str):
        msg = "private extension manifest entry factory must be a string"
        raise PrivateExtensionError(msg)
    if not extension_id or not source_path or not module or not factory:
        msg = "private extension manifest entry fields must be strings"
        raise PrivateExtensionError(msg)
    if not _EXTENSION_ID_PATTERN.fullmatch(extension_id):
        msg = f"private extension id is invalid: {extension_id}"
        raise PrivateExtensionError(msg)
    if not (
        _PYTHON_MODULE_PATTERN.fullmatch(module)
        and _PYTHON_MODULE_PATTERN.fullmatch(factory)
    ):
        msg = f"private extension module contract is invalid: {extension_id}"
        raise PrivateExtensionError(msg)
    path = PurePosixPath(source_path)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        msg = f"private extension path is invalid: {extension_id}"
        raise PrivateExtensionError(msg)
    resolved_source = root.joinpath(*path.parts)
    try:
        resolved_source.resolve().relative_to(root.resolve())
    except ValueError as error:
        msg = f"private extension path escapes package: {extension_id}"
        raise PrivateExtensionError(msg) from error
    if not resolved_source.is_dir():
        msg = f"private extension path does not exist: {extension_id}"
        raise PrivateExtensionError(msg)
    return PrivateExtensionEntry(
        id=extension_id,
        path=path,
        module=module,
        factory=factory,
    )


def _replace_current_extension_package(destination_root: Path, staging: Path) -> None:
    current = destination_root / PRIVATE_EXTENSIONS_CURRENT_DIRECTORY
    previous = destination_root / f".previous-{uuid4().hex}"
    moved_current = False
    try:
        if current.exists():
            current.replace(previous)
            moved_current = True
        staging.replace(current)
    except Exception:
        if moved_current and previous.exists() and not current.exists():
            previous.replace(current)
        raise
    finally:
        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
