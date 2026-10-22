# SPDX-License-Identifier: MIT
"""Package an unchanged, hash-verified ABI without upstream Python dependencies."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from zipfile import ZipFile

from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build import build
from setuptools.command.build_ext import build_ext

if TYPE_CHECKING:
    from collections.abc import Iterable

    from packaging.tags import Tag

ROOT = Path(__file__).parent
MAX_ARCHIVE_BYTES = 40 * 1024 * 1024
MAX_CORE_BYTES = 100 * 1024 * 1024
DOWNLOAD_SECONDS = 60
CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Artifact:
    url: str
    sha256: str
    tag: Tag


def select_artifact(supported: Iterable[Tag]) -> Artifact:
    entries = json.loads((ROOT / "artifacts.json").read_text(encoding="utf-8"))
    by_tag = {}
    for entry in entries:
        name = PurePosixPath(entry["url"]).name
        _name, _version, _build, tags = parse_wheel_filename(name)
        for tag in tags:
            by_tag[tag] = Artifact(entry["url"], entry["sha256"], tag)
    for tag in supported:
        if tag in by_tag:
            return by_tag[tag]
    msg = "no verified litehtml binary supports this Python/platform ABI"
    raise RuntimeError(msg)


def download_artifact(artifact: Artifact) -> bytes:
    source = urlsplit(artifact.url)
    if source.scheme != "https" or source.hostname != "files.pythonhosted.org":
        msg = "native binary source must be the pinned HTTPS artifact host"
        raise ValueError(msg)
    digest = hashlib.sha256()
    result = bytearray()
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    # The HTTPS artifact host is checked above; content also needs its pinned hash.
    with urllib.request.urlopen(artifact.url, timeout=30) as response:  # nosec B310
        while block := response.read(CHUNK_BYTES):
            if (
                time.monotonic() > deadline
                or len(result) + len(block) > MAX_ARCHIVE_BYTES
            ):
                msg = "native binary download exceeded its time/size budget"
                raise RuntimeError(msg)
            result.extend(block)
            digest.update(block)
    if digest.hexdigest() != artifact.sha256:
        msg = "native binary archive SHA256 mismatch"
        raise RuntimeError(msg)
    return bytes(result)


def extract_core(archive: bytes) -> bytes:
    with ZipFile(BytesIO(archive)) as wheel:
        cores = [
            item
            for item in wheel.infolist()
            if item.filename.startswith("nonebot_plugin_htmlkit/core")
            and PurePosixPath(item.filename).suffix in {".pyd", ".so"}
        ]
        if (
            len(cores) != 1
            or not cores[0].file_size
            or cores[0].file_size > MAX_CORE_BYTES
        ):
            msg = "native archive has a missing, ambiguous or oversized core"
            raise RuntimeError(msg)
        return wheel.read(cores[0])


class NativeBuild(build):
    def finalize_options(self) -> None:
        self._directory = tempfile.TemporaryDirectory(prefix="ironsbot-litehtml-build-")
        self.build_base = self._directory.name
        super().finalize_options()


class NativeBuildExt(build_ext):
    def build_extensions(self) -> None:
        artifact = select_artifact(sys_tags())
        core = extract_core(download_artifact(artifact))
        target = Path(self.get_ext_fullpath("ironsbot_litehtml.core"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(core)


class NativeWheel(bdist_wheel):
    def get_tag(self) -> tuple[str, str, str]:
        tag = select_artifact(sys_tags()).tag
        return tag.interpreter, tag.abi, tag.platform
