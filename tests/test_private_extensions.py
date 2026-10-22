from __future__ import annotations

import asyncio
import io
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.app import private_extensions
from ironsbot.app.private_extensions import (
    PRIVATE_EXTENSIONS_ROOT,
    PrivateExtensionCatalog,
    PrivateExtensionError,
    PrivateExtensionInstaller,
    install_private_extension_archive,
)
from ironsbot.config.models.operations import (
    DockerUpdateConfig,
    PrivateExtensionsConfig,
)
from ironsbot.core.schedule_rendering import ScheduleRendererRegistry
from ironsbot.extensions.registration import ExtensionServices
from ironsbot.services.operations.docker_models import (
    DockerImageArchive,
    DockerImageArchiveRequest,
    DockerImageInfo,
)

if TYPE_CHECKING:
    from ironsbot.extensions.contracts import PlayerLineupExtensionContext


def _package_archive(
    *,
    module: str = "ironsbot_private_lineup.plugin",
    include_source: bool = True,
    factory: str = "plugin_contribution",
) -> bytes:
    manifest = (
        '[project.entry-points."ironsbot.extensions"]\n'
        f'lineup = "{module}:{factory}"\n'
    ).encode()
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w") as archive:
        _add_tar_file(archive, f"{PRIVATE_EXTENSIONS_ROOT}/pyproject.toml", manifest)
        if include_source:
            package, _, leaf = module.rpartition(".")
            package_path = package.replace(".", "/")
            _add_tar_file(
                archive,
                f"{PRIVATE_EXTENSIONS_ROOT}/{package_path}/__init__.py",
                b"",
            )
            _add_tar_file(
                archive,
                f"{PRIVATE_EXTENSIONS_ROOT}/{package_path}/{leaf}.py",
                (
                    b"from ironsbot.core.plugin_install import PluginContribution\n"
                    b"received = None\n"
                    b"def plugin_contribution(services):\n"
                    b"    global received\n"
                    b"    received = services\n"
                    b"    return PluginContribution(id='private_test')\n"
                ),
            )
    return result.getvalue()


def _add_tar_file(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))


class _Docker:
    def __init__(self, content: bytes | Exception) -> None:
        self._content = content
        self.requests: list[DockerImageArchiveRequest] = []

    async def fetch_image_archive(
        self,
        request: DockerImageArchiveRequest,
    ) -> DockerImageArchive:
        self.requests.append(request)
        if isinstance(self._content, Exception):
            raise self._content
        return DockerImageArchive(
            image=DockerImageInfo(image_id="sha256:private-package"),
            content=self._content,
        )


def test_install_private_extension_archive_writes_factory_entry_points(
    tmp_path: Path,
) -> None:
    manifest = install_private_extension_archive(_package_archive(), tmp_path)

    assert tuple(entry.value for entry in manifest.entry_points) == (
        "ironsbot_private_lineup.plugin:plugin_contribution",
    )
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    assert tuple(entry.value for entry in catalog.entry_points) == (
        "ironsbot_private_lineup.plugin:plugin_contribution",
    )
    assert (tmp_path / "current" / "pyproject.toml").is_file()


def test_invalid_new_archive_preserves_last_valid_package(tmp_path: Path) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)

    with pytest.raises(PrivateExtensionError, match="does not exist"):
        install_private_extension_archive(
            _package_archive(include_source=False),
            tmp_path,
        )

    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    assert tuple(entry.value for entry in catalog.entry_points) == (
        "ironsbot_private_lineup.plugin:plugin_contribution",
    )


def test_valid_new_archive_replaces_the_current_package(tmp_path: Path) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)

    manifest = install_private_extension_archive(
        _package_archive(module="ironsbot_private_replacement.plugin"),
        tmp_path,
    )

    assert tuple(entry.value for entry in manifest.entry_points) == (
        "ironsbot_private_replacement.plugin:plugin_contribution",
    )
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    assert tuple(entry.value for entry in catalog.entry_points) == (
        "ironsbot_private_replacement.plugin:plugin_contribution",
    )


@pytest.mark.parametrize("fail_backup", [False, True])
def test_directory_switch_failure_preserves_current_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, fail_backup: bool
) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)
    original_move = private_extensions._move_extension_directory

    def fail_switch(source: Path, destination: Path) -> None:
        failing_step = (
            source.name == "current"
            if fail_backup
            else source.name.startswith(".staging-")
        )
        if failing_step:
            msg = "injected switch failure"
            raise PermissionError(msg)
        original_move(source, destination)

    monkeypatch.setattr(private_extensions, "_move_extension_directory", fail_switch)
    with pytest.raises(PermissionError, match="injected switch failure"):
        install_private_extension_archive(
            _package_archive(module="ironsbot_private_replacement.plugin"), tmp_path
        )

    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    assert tuple(entry.value for entry in catalog.entry_points) == (
        "ironsbot_private_lineup.plugin:plugin_contribution",
    )
    assert not list(tmp_path.glob(".previous-*"))


def test_failed_rollback_retains_valid_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)
    original_move = private_extensions._move_extension_directory

    def fail_install_and_restore(source: Path, destination: Path) -> None:
        if destination.name == "current":
            msg = "injected destination lock"
            raise PermissionError(msg)
        original_move(source, destination)

    monkeypatch.setattr(
        private_extensions, "_move_extension_directory", fail_install_and_restore
    )
    with pytest.raises(PrivateExtensionError, match="rollback failed") as failure:
        install_private_extension_archive(
            _package_archive(module="ironsbot_private_replacement.plugin"), tmp_path
        )

    backups = list(tmp_path.glob(".previous-*"))
    assert len(backups) == 1
    assert str(backups[0]) in str(failure.value)
    assert (backups[0] / "ironsbot_private_lineup" / "plugin.py").is_file()
    assert not (tmp_path / "current").exists()


def test_failed_first_install_never_exposes_partial_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_move(_source: Path, _destination: Path) -> None:
        msg = "injected first install failure"
        raise PermissionError(msg)

    monkeypatch.setattr(private_extensions, "_move_extension_directory", deny_move)
    with pytest.raises(PermissionError, match="first install failure"):
        install_private_extension_archive(_package_archive(), tmp_path)

    assert not (tmp_path / "current").exists()
    assert not list(tmp_path.glob(".staging-*"))


@pytest.mark.parametrize("persistent", [False, True])
def test_directory_move_has_bounded_permission_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, persistent: bool
) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    (source / "content").write_bytes(b"complete package")
    original_rename = Path.rename
    attempts: list[Path] = []
    waits: list[float] = []

    def locked_rename(path: Path, target: Path) -> Path:
        attempts.append(path)
        if persistent or len(attempts) == 1:
            msg = "injected lock"
            raise PermissionError(msg)
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", locked_rename)
    monkeypatch.setattr(private_extensions.time, "sleep", waits.append)
    if persistent:
        with pytest.raises(PermissionError, match="injected lock"):
            private_extensions._move_extension_directory(source, destination)
        assert len(attempts) == private_extensions._DIRECTORY_MOVE_ATTEMPTS
        assert source.is_dir()
        assert not destination.exists()
    else:
        private_extensions._move_extension_directory(source, destination)
        assert (destination / "content").read_bytes() == b"complete package"
        assert not source.exists()
    assert len(waits) == len(attempts) - 1


def test_private_manifest_rejects_invalid_factory_reference(tmp_path: Path) -> None:
    with pytest.raises(PrivateExtensionError, match="module:function"):
        install_private_extension_archive(
            _package_archive(factory="plugin.invalid"),
            tmp_path,
        )


def test_archive_rejects_entries_outside_package_root(tmp_path: Path) -> None:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as output:
        _add_tar_file(output, "outside.py", b"unsafe")

    with pytest.raises(PrivateExtensionError, match="outside"):
        install_private_extension_archive(archive.getvalue(), tmp_path)


def test_installer_reuses_registry_credentials_and_preserves_old_package(
    tmp_path: Path,
) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)
    docker = _Docker(RuntimeError("registry unavailable"))
    result = asyncio.run(
        PrivateExtensionInstaller(
            PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path)),
            DockerUpdateConfig(
                registry_username="murmansk5000",
                registry_token="pull-token",
            ),
            docker,
        ).install()
    )

    assert not result.installed
    assert docker.requests[0].registry_credentials is not None
    assert docker.requests[0].registry_credentials.username == "murmansk5000"
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    assert tuple(entry.value for entry in catalog.entry_points) == (
        "ironsbot_private_lineup.plugin:plugin_contribution",
    )


def test_disabled_private_extensions_do_not_load_a_cached_package(
    tmp_path: Path,
) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)

    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=False, data_path=str(tmp_path))
    )

    assert catalog.entry_points == ()
    assert catalog.contributions(_services()) == ()


def test_private_factories_receive_explicit_services_without_native_loading(
    tmp_path: Path,
) -> None:
    install_private_extension_archive(
        _package_archive(module="ironsbot_private_test_plugin.plugin"),
        tmp_path,
    )
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    from importlib import import_module

    services = _services()
    with catalog.plugin_import_path():
        module = import_module("ironsbot_private_test_plugin.plugin")
    assert module.received is None
    contributions = catalog.contributions(services)
    assert module.received is services
    assert tuple(contribution.id for contribution in contributions) == (
        "private_test",
    )


def _services() -> ExtensionServices:
    return ExtensionServices(
        cast("PlayerLineupExtensionContext", object()), ScheduleRendererRegistry()
    )


def test_old_native_manifest_is_not_accepted(tmp_path: Path) -> None:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as output:
        _add_tar_file(
            output,
            f"{PRIVATE_EXTENSIONS_ROOT}/pyproject.toml",
            b'[tool.nonebot.plugins]\n"@private" = ["ironsbot_private_test.plugin"]',
        )
    with pytest.raises(PrivateExtensionError, match="no project table"):
        install_private_extension_archive(archive.getvalue(), tmp_path)
    assert not (tmp_path / "current").exists()


@pytest.mark.parametrize("factory", [42, lambda _: None])
def test_invalid_factories_fail_before_application_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, factory: object
) -> None:
    module_name = "ironsbot_private_invalid.plugin"
    install_private_extension_archive(_package_archive(module=module_name), tmp_path)
    root = tmp_path / "current"
    module = ModuleType(module_name)
    module.__file__ = str(root / "ironsbot_private_invalid" / "plugin.py")
    monkeypatch.setattr(module, "plugin_contribution", factory, raising=False)
    monkeypatch.setitem(sys.modules, module_name, module)
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    before = sys.path[:]
    with pytest.raises(PrivateExtensionError, match=r"not callable|invalid data"):
        catalog.contributions(_services())
    assert sys.path == before


def test_cached_module_from_another_package_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_name = "ironsbot_private_foreign.plugin"
    install_private_extension_archive(_package_archive(module=module_name), tmp_path)
    module = ModuleType(module_name)
    module.__file__ = str(tmp_path / "another-package" / "plugin.py")
    monkeypatch.setitem(sys.modules, module_name, module)
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    with pytest.raises(PrivateExtensionError, match="outside package"):
        catalog.contributions(_services())


@pytest.mark.parametrize(
    "target", ["external.plugin:factory", "ironsbot_private_test.plugin", "bad:path:x"]
)
def test_manifest_rejects_nonlocal_or_malformed_entry_points(
    tmp_path: Path, target: str
) -> None:
    root = tmp_path / "current"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project.entry-points."ironsbot.extensions"]\n' + f'test = "{target}"\n',
        encoding="utf-8",
    )
    assert PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    ).reason == "private extension package is invalid"
