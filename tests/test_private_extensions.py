from __future__ import annotations

import asyncio
import io
import tarfile
from pathlib import Path

import nonebot
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
from ironsbot.core.plugin_install import scoped_plugin_install_context
from ironsbot.services.operations.docker_models import (
    DockerImageArchive,
    DockerImageArchiveRequest,
    DockerImageInfo,
)


def _package_archive(
    *,
    module: str = "ironsbot_private_lineup.plugin",
    include_source: bool = True,
    plugin_dirs: tuple[str, ...] = (),
) -> bytes:
    manifest = (
        "[tool.nonebot]\n"
        f"plugin_dirs = {list(plugin_dirs)!r}\n\n"
        "[tool.nonebot.plugins]\n"
        f'"@private" = ["{module}"]\n'
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
                    b"from nonebot.plugin import PluginMetadata\n"
                    b"from ironsbot.core.plugin_install import (\n"
                    b"    PluginContribution, active_plugin_install_context\n"
                    b")\n"
                    b"__plugin_meta__ = PluginMetadata(\n"
                    b"    name='Private test', description='test', usage='test'\n"
                    b")\n"
                    b"context = active_plugin_install_context()\n"
                    b"if context is not None:\n"
                    b"    context.contribute(\n"
                    b"        __plugin_meta__, PluginContribution(id='private_test')\n"
                    b"    )\n"
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


def test_install_private_extension_archive_writes_a_nonebot_manifest(
    tmp_path: Path,
) -> None:
    manifest = install_private_extension_archive(_package_archive(), tmp_path)

    assert manifest.plugin_modules == ("ironsbot_private_lineup.plugin",)
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    assert catalog.plugin_modules == ("ironsbot_private_lineup.plugin",)
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
    assert catalog.plugin_modules == ("ironsbot_private_lineup.plugin",)


def test_valid_new_archive_replaces_the_current_package(tmp_path: Path) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)

    manifest = install_private_extension_archive(
        _package_archive(module="ironsbot_private_replacement.plugin"),
        tmp_path,
    )

    assert manifest.plugin_modules == ("ironsbot_private_replacement.plugin",)
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    assert catalog.plugin_modules == ("ironsbot_private_replacement.plugin",)


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
    assert catalog.plugin_modules == ("ironsbot_private_lineup.plugin",)
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


def test_private_manifest_rejects_plugin_directory_discovery(tmp_path: Path) -> None:
    with pytest.raises(PrivateExtensionError, match="must not declare plugin_dirs"):
        install_private_extension_archive(
            _package_archive(plugin_dirs=("plugins",)),
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
    assert catalog.plugin_modules == ("ironsbot_private_lineup.plugin",)


def test_disabled_private_extensions_do_not_load_a_cached_package(
    tmp_path: Path,
) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)

    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=False, data_path=str(tmp_path))
    )

    assert catalog.plugin_modules == ()
    assert catalog.manifest_path is None


def test_private_manifest_is_loaded_by_nonebot_inside_scoped_context(
    tmp_path: Path,
) -> None:
    install_private_extension_archive(
        _package_archive(module="ironsbot_private_test_plugin.plugin"),
        tmp_path,
    )
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    if not _nonebot_is_initialized():
        nonebot.init()
    manifest_path = catalog.manifest_path
    assert manifest_path is not None

    with (
        scoped_plugin_install_context(
            settings=object(),  # type: ignore[arg-type]
            resources=object(),  # type: ignore[arg-type]
            scheduler=object(),  # type: ignore[arg-type]
        ) as context,
        catalog.plugin_import_path(),
    ):
        nonebot.load_from_toml(str(manifest_path))

    assert tuple(contribution.id for contribution in context.contributions) == (
        "private_test",
    )


def _nonebot_is_initialized() -> bool:
    try:
        nonebot.get_driver()
    except ValueError:
        return False
    return True
