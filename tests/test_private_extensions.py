from __future__ import annotations

import asyncio
import io
import tarfile
from typing import TYPE_CHECKING

import nonebot
import pytest

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

if TYPE_CHECKING:
    from pathlib import Path


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
