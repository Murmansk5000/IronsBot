from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest
import tomllib
from packaging.tags import Tag

from ironsbot.integrations import litehtml
from packages.litehtml_core import build_native

if TYPE_CHECKING:
    from collections.abc import Sequence


def test_runtime_dependency_closure_never_installs_a_framework() -> None:
    root = Path(__file__).resolve().parents[1]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in lock["package"]}
    pending = ["ironsbot"]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        package = packages[name]
        edges = list(package.get("dependencies", []))
        edges.extend(package.get("optional-dependencies", {}).get("qq-official", []))
        pending.extend(edge["name"] for edge in edges)
    assert "ironsbot-litehtml-core" in seen
    assert not any(name.startswith("nonebot") for name in seen)
    assert not seen.intersection({"pygments", "pymdown-extensions", "markdown"})
    assert packages["ironsbot-litehtml-core"].get("dependencies", []) == []
    native = tomllib.loads((build_native.ROOT / "pyproject.toml").read_text())
    assert native["project"]["version"] == litehtml.NATIVE_VERSION
    assert native["project"]["name"] == litehtml.NATIVE_DISTRIBUTION
    assert native["project"]["dependencies"] == []


@pytest.mark.parametrize(
    "platform",
    ["win_amd64", "manylinux_2_34_x86_64", "manylinux_2_34_aarch64"],
)
def test_native_artifact_selection_preserves_published_abi(platform: str) -> None:
    tag = Tag("cp310", "abi3", platform)
    artifact = build_native.select_artifact([tag])
    assert artifact.tag == tag
    assert artifact.url.endswith(f"-cp310-abi3-{platform}.whl")
    assert len(bytes.fromhex(artifact.sha256)) == hashlib.sha256().digest_size


def test_native_artifact_selection_never_substitutes_an_unsupported_platform() -> None:
    with pytest.raises(RuntimeError, match="no verified litehtml binary"):
        build_native.select_artifact([Tag("cp311", "cp311", "unsupported")])


def _archive(names: Sequence[str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, b"original-native-bytes")
    return buffer.getvalue()


def test_native_extraction_copies_only_the_unchanged_core() -> None:
    wheel = _archive(
        [
            "nonebot_plugin_htmlkit/__init__.py",
            "nonebot_plugin_htmlkit/core.abi3.so",
            "nonebot_plugin_htmlkit/templates/text.html",
        ]
    )
    assert build_native.extract_core(wheel) == b"original-native-bytes"


@pytest.mark.parametrize(
    "names",
    [
        [],
        ["foreign/core.pyd"],
        ["nonebot_plugin_htmlkit/core.pyd", "nonebot_plugin_htmlkit/core.so"],
    ],
)
def test_native_extraction_rejects_missing_or_ambiguous_cores(names: list[str]) -> None:
    with pytest.raises(RuntimeError, match="missing, ambiguous or oversized"):
        build_native.extract_core(_archive(names))


def test_native_extraction_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_native, "MAX_CORE_BYTES", 1)
    with pytest.raises(RuntimeError, match="oversized"):
        build_native.extract_core(_archive(["nonebot_plugin_htmlkit/core.pyd"]))


@pytest.mark.parametrize("failure", ["none", "hash", "size", "timeout", "host"])
def test_native_download_rejects_unverified_or_unbounded_artifacts(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    content = b"verified-wheel-bytes"
    artifact = build_native.Artifact(
        "file:///should-not-read"
        if failure == "host"
        else "https://files.pythonhosted.org/pinned.whl",
        "wrong" if failure == "hash" else hashlib.sha256(content).hexdigest(),
        Tag("cp310", "abi3", "win_amd64"),
    )
    calls: list[str] = []

    def open_wheel(url: str, *, timeout: int) -> BytesIO:
        assert timeout > 0
        calls.append(url)
        return BytesIO(content)

    monkeypatch.setattr(build_native.urllib.request, "urlopen", open_wheel)
    if failure == "size":
        monkeypatch.setattr(build_native, "MAX_ARCHIVE_BYTES", 1)
    if failure == "timeout":
        clocks = iter([0, build_native.DOWNLOAD_SECONDS + 1])
        monkeypatch.setattr(build_native.time, "monotonic", lambda: next(clocks))
    if failure == "none":
        assert build_native.download_artifact(artifact) == content
    elif failure == "host":
        with pytest.raises(ValueError, match="HTTPS artifact host"):
            build_native.download_artifact(artifact)
        assert calls == []
    else:
        with pytest.raises(RuntimeError, match=r"SHA256|time/size budget"):
            build_native.download_artifact(artifact)
