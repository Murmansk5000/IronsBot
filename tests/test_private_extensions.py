from __future__ import annotations

import asyncio
import io
import json
import tarfile
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.app.private_extensions import (
    PRIVATE_EXTENSIONS_ROOT,
    PrivateExtensionCatalog,
    PrivateExtensionError,
    PrivateExtensionInstaller,
    PrivateExtensionRuntime,
    install_private_extension_archive,
)
from ironsbot.config.models.operations import (
    DockerUpdateConfig,
    PrivateExtensionsConfig,
)
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
) -> bytes:
    manifest = json.dumps(
        {
            "schema_version": 1,
            "extensions": [
                {
                    "id": "player_lineup",
                    "path": "player_lineup",
                    "module": module,
                    "factory": "build_plugin_definition",
                }
            ],
        }
    ).encode("utf-8")
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w") as archive:
        _add_tar_file(archive, f"{PRIVATE_EXTENSIONS_ROOT}/manifest.json", manifest)
        if include_source:
            _add_tar_file(
                archive,
                f"{PRIVATE_EXTENSIONS_ROOT}/player_lineup/__init__.py",
                b"",
            )
            _add_tar_file(
                archive,
                f"{PRIVATE_EXTENSIONS_ROOT}/player_lineup/ironsbot_private_lineup/plugin.py",
                (
                    b"from ironsbot.runtime.plugins import PluginDefinition\n"
                    b"def build_plugin_definition(_runtime):\n"
                    b"    return PluginDefinition(id='private_test')\n"
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


def test_install_private_extension_archive_writes_valid_current_package(
    tmp_path: Path,
) -> None:
    entries = install_private_extension_archive(_package_archive(), tmp_path)

    assert set(entries) == {"player_lineup"}
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    assert catalog.extension_ids == ("player_lineup",)
    assert (tmp_path / "current" / "manifest.json").is_file()


def test_invalid_new_archive_preserves_last_valid_package(tmp_path: Path) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)

    with pytest.raises(PrivateExtensionError, match="path does not exist"):
        install_private_extension_archive(
            _package_archive(include_source=False),
            tmp_path,
        )

    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )
    assert catalog.extension_ids == ("player_lineup",)


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
    assert catalog.extension_ids == ("player_lineup",)


def test_disabled_private_extensions_do_not_load_a_cached_package(
    tmp_path: Path,
) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)

    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=False, data_path=str(tmp_path))
    )

    assert catalog.extension_ids == ()


def test_private_catalog_loads_only_plugin_definitions(tmp_path: Path) -> None:
    install_private_extension_archive(_package_archive(), tmp_path)
    catalog = PrivateExtensionCatalog.from_config(
        PrivateExtensionsConfig(enabled=True, data_path=str(tmp_path))
    )

    runtime = cast("PrivateExtensionRuntime", object())
    definitions = catalog.load_plugin_definitions(runtime)

    assert tuple(definition.id for definition in definitions) == ("private_test",)
