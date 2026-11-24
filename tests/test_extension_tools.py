from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, NamedTuple

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ironsbot.app import extension_tools as tools
from ironsbot.extensions import tool_runtime
from ironsbot.extensions.tool_runtime import (
    ToolRuntimeError,
    resolve_extension_tool,
)

pytestmark = pytest.mark.skipif(
    os.name == "posix" and os.geteuid() != 0,
    reason="Real tool ownership checks require root; CI runs this module separately",
)


def _file_info(name: str, data: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo("ironsbot_tools/somua/" + name)
    info.mode = 0o644
    info.size = len(data)
    return info


def _artifact(
    tmp_path: Path,
    *,
    extras: tuple[tarfile.TarInfo, ...] = (),
    inventory_change: dict[str, object] | None = None,
) -> tuple[Path, tools.ToolSpec]:
    data = b"synthetic tool only"
    entry = {
        "type": "file",
        "mode": 0o644,
        "uid": 0,
        "gid": 0,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    if inventory_change:
        entry.update(inventory_change)
    manifest = json.dumps({"files": {"tool": entry}}).encode()
    spec = tools.ToolSpec(hashlib.sha256(manifest).hexdigest(), len(data))
    path = tmp_path / "tools.tar"
    with tarfile.open(path, "w") as archive:
        archive.addfile(_file_info("manifest.json", manifest), io.BytesIO(manifest))
        archive.addfile(_file_info("tool", data), io.BytesIO(data))
        for extra in extras:
            archive.addfile(extra, io.BytesIO(b"x" * extra.size))
    return path, spec


def test_spec_is_optional_and_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tools, "validate_tool_host", lambda _spec: None)
    assert tools.read_tool_spec(tmp_path) is None
    spec = tools.ToolSpec("a" * 64, 17)
    payload = asdict(spec) | {"capabilities": spec.capabilities}
    path = tmp_path / "private-tools.json"
    path.write_text(json.dumps(payload))
    assert tools.read_tool_spec(tmp_path) == spec
    for key, value in (
        ("contract_version", True),
        ("libc", "musl"),
        ("platform", "linux/arm64"),
        ("size_bytes", -1),
        ("fingerprint", "../../escape"),
        ("probe_module", "untrusted.run"),
        ("capabilities", {"somua_avatar": True}),
    ):
        path.write_text(json.dumps(payload | {key: value}))
        with pytest.raises(ToolRuntimeError):
            tools.read_tool_spec(tmp_path)


def test_read_spec_checks_host_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = tools.ToolSpec("a" * 64, 17)
    (tmp_path / "private-tools.json").write_text(
        json.dumps(asdict(spec) | {"capabilities": spec.capabilities})
    )
    monkeypatch.setattr(tool_runtime.sys, "platform", "win32")
    with pytest.raises(ToolRuntimeError, match="linux/amd64"):
        tools.read_tool_spec(tmp_path)


def test_extract_validates_without_publishing(tmp_path: Path) -> None:
    archive, spec = _artifact(tmp_path)
    staging = tmp_path / ".staging-tools"
    runtime = tools.extract_tool_archive(archive, staging, spec)
    assert runtime == staging / "somua"
    assert (runtime / "tool").read_bytes() == b"synthetic tool only"
    tools.validate_tool_runtime(runtime, spec)
    assert not (tmp_path / "tools").exists()
    with pytest.raises(ToolRuntimeError, match="empty"):
        tools.extract_tool_archive(archive, staging, spec)


@pytest.mark.parametrize(
    "name",
    [
        "ironsbot_tools/somua/../escape",
        "/ironsbot_tools/somua/tool",
        "ironsbot_tools/somua/a/./b",
        "ironsbot_tools/somua//b",
        "ironsbot_tools/somua/C:escape",
        "ironsbot_tools/somua/a\\b",
        "ironsbot_tools/other/tool",
        "other/somua/tool",
    ],
)
def test_rejects_archive_path_aliases(tmp_path: Path, name: str) -> None:
    member = tarfile.TarInfo(name)
    member.mode = 0o644
    archive, spec = _artifact(tmp_path, extras=(member,))
    with pytest.raises(ToolRuntimeError):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)


@pytest.mark.parametrize("kind", [tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE])
def test_rejects_special_entries(tmp_path: Path, kind: bytes) -> None:
    member = _file_info("bad", b"")
    member.type = kind
    member.linkname = "tool"
    archive, spec = _artifact(tmp_path, extras=(member,))
    with pytest.raises(ToolRuntimeError, match="unsupported"):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)


def test_rejects_duplicate_entries(tmp_path: Path) -> None:
    member = _file_info("tool", b"")
    archive, spec = _artifact(tmp_path, extras=(member,))
    with pytest.raises(ToolRuntimeError, match="duplicate"):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)


@pytest.mark.parametrize(
    "change",
    [
        {"sha256": "0" * 64},
        {"size": 1},
        {"mode": 0o777},
        {"uid": 1},
        {"type": "symlink"},
        {"size": True},
    ],
)
def test_rejects_inventory_mismatch(tmp_path: Path, change: dict[str, object]) -> None:
    archive, spec = _artifact(tmp_path, inventory_change=change)
    with pytest.raises(ToolRuntimeError):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)


def test_rejects_undeclared_files_and_wrong_fingerprint(tmp_path: Path) -> None:
    archive, spec = _artifact(tmp_path, extras=(_file_info("extra", b""),))
    with pytest.raises(ToolRuntimeError, match="undeclared"):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)
    with pytest.raises(ToolRuntimeError, match="fingerprint"):
        tools.extract_tool_archive(
            archive, tmp_path / "other", replace(spec, fingerprint="0" * 64)
        )


def test_limits_are_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive, spec = _artifact(tmp_path)
    monkeypatch.setattr(tools, "MAX_TOOL_ARCHIVE_BYTES", 1)
    with pytest.raises(ToolRuntimeError, match="too large"):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)
    monkeypatch.setattr(tools, "MAX_TOOL_ARCHIVE_BYTES", 1024**3)
    monkeypatch.setattr(tools, "MAX_TOOL_UNPACKED_BYTES", 1)
    with pytest.raises(ToolRuntimeError, match="unpacked"):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)
    monkeypatch.setattr(tools, "MAX_TOOL_UNPACKED_BYTES", 1024**3)
    monkeypatch.setattr(tools, "MAX_TOOL_FILES", 1)
    with pytest.raises(ToolRuntimeError, match="too many"):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)


def test_existing_runtime_is_rechecked(tmp_path: Path) -> None:
    archive, spec = _artifact(tmp_path)
    runtime = tools.extract_tool_archive(archive, tmp_path / "staging", spec)
    (runtime / "tool").write_bytes(b"tampered")
    with pytest.raises(ToolRuntimeError):
        tools.validate_tool_runtime(runtime, spec)


def _cached_package(tmp_path: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        tmp_path = type(tmp_path)("\\\\?\\" + str(tmp_path))
    package = tmp_path / "current"
    package.mkdir()
    runtime = tmp_path / "tools" / ("a" * 64) / "somua"
    runtime.mkdir(parents=True)
    marker = package / ".installed-tools.json"
    payload = {
        "schema": 1,
        "tools": {
            "somua": {"fingerprint": "a" * 64, "path": str(runtime.resolve())},
        },
    }
    marker.write_text(json.dumps(payload))
    spec = tools.ToolSpec("a" * 64, 0)
    (package / "private-tools.json").write_text(
        json.dumps(asdict(spec) | {"capabilities": spec.capabilities})
    )
    return package, runtime


def _compatible_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_runtime.sys, "platform", "linux")
    monkeypatch.setattr(tool_runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(tool_runtime.platform, "libc_ver", lambda: ("glibc", "2.36"))
    monkeypatch.setattr(tool_runtime.sys, "version_info", _PythonVersion(3, 11))


class _PythonVersion(NamedTuple):
    major: int
    minor: int
    micro: int = 0
    releaselevel: str = "final"
    serial: int = 0


def test_resolver_only_accepts_activated_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _compatible_host(monkeypatch)
    assert resolve_extension_tool(tmp_path / "current", "somua") is None
    package, runtime = _cached_package(tmp_path)
    assert resolve_extension_tool(package, "somua") == runtime.resolve()
    marker = package / ".installed-tools.json"
    payload = json.loads(marker.read_text())
    payload["tools"]["somua"]["path"] = str(tmp_path.resolve())
    marker.write_text(json.dumps(payload))
    with pytest.raises(ToolRuntimeError, match="immutable"):
        resolve_extension_tool(package, "somua")


def test_resolver_rejects_marker_duplicate_keys(tmp_path: Path) -> None:
    (tmp_path / ".installed-tools.json").write_text('{"schema":1,"schema":1}')
    with pytest.raises(ToolRuntimeError, match="JSON"):
        resolve_extension_tool(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink privilege is optional")
def test_rejects_symlink_destination(tmp_path: Path) -> None:
    archive, spec = _artifact(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    staging = tmp_path / "staging"
    staging.symlink_to(target, target_is_directory=True)
    with pytest.raises(ToolRuntimeError, match="symlink"):
        tools.extract_tool_archive(archive, staging, spec)


def test_host_contract_checks_actual_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _compatible_host(monkeypatch)
    spec = tools.ToolSpec("a" * 64, 0, python="999.0")
    with pytest.raises(ToolRuntimeError, match="Python"):
        tools.validate_tool_host(spec)
    monkeypatch.setattr(tool_runtime.platform, "libc_ver", lambda: ("musl", "1.2"))
    with pytest.raises(ToolRuntimeError, match="glibc"):
        tools.validate_tool_host(spec)


def test_cached_tool_survives_compatible_public_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _compatible_host(monkeypatch)
    package, runtime = _cached_package(tmp_path)
    declaration = package / "private-tools.json"
    payload = json.loads(declaration.read_text())
    assert resolve_extension_tool(package) == runtime.resolve()
    # Build provenance is informational, not an exact-public-SHA requirement.
    for sha in ("a" * 40, "b" * 40):
        payload["public_sha"] = sha
        declaration.write_text(json.dumps(payload))
        assert resolve_extension_tool(package) == runtime.resolve()


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", 2),
        ("contract_version", 2),
        ("capabilities", {"somua_avatar": 2}),
        ("capabilities", {"somua_avatar": True}),
        ("platform", "linux/arm64"),
        ("libc", "musl"),
        ("min_glibc", "2.35"),
        ("python", "3.12"),
        ("fingerprint", "b" * 64),
    ],
)
def test_cached_incompatible_declaration_disables_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, value: object
) -> None:
    _compatible_host(monkeypatch)
    package, _ = _cached_package(tmp_path)
    declaration = package / "private-tools.json"
    payload = json.loads(declaration.read_text())
    declaration.write_text(json.dumps(payload | {key: value}))
    with pytest.raises(ToolRuntimeError):
        resolve_extension_tool(package)


def test_cached_contract_is_checked_against_current_public_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _compatible_host(monkeypatch)
    package, runtime = _cached_package(tmp_path)
    assert resolve_extension_tool(package) == runtime.resolve()
    monkeypatch.setattr(tool_runtime, "TOOL_CONTRACT_VERSION", 2)
    with pytest.raises(ToolRuntimeError, match="contract_version"):
        resolve_extension_tool(package)


@pytest.mark.parametrize("host", ["platform", "arch", "libc", "glibc", "python"])
def test_cached_runtime_rechecks_current_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    _compatible_host(monkeypatch)
    package, _ = _cached_package(tmp_path)
    if host == "platform":
        monkeypatch.setattr(tool_runtime.sys, "platform", "win32")
    elif host == "arch":
        monkeypatch.setattr(tool_runtime.platform, "machine", lambda: "aarch64")
    elif host == "libc":
        monkeypatch.setattr(tool_runtime.platform, "libc_ver", lambda: ("musl", "1.2"))
    elif host == "glibc":
        monkeypatch.setattr(
            tool_runtime.platform, "libc_ver", lambda: ("glibc", "2.35")
        )
    else:
        monkeypatch.setattr(tool_runtime.sys, "version_info", _PythonVersion(3, 12))
    with pytest.raises(ToolRuntimeError):
        resolve_extension_tool(package)


@pytest.mark.parametrize(
    "contents",
    [None, "not-json", "[0]", " " * (1024**2 + 1)],
    ids=["missing", "invalid-json", "not-object", "oversized"],
)
def test_cached_declaration_is_required_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str | None
) -> None:
    _compatible_host(monkeypatch)
    package, _ = _cached_package(tmp_path)
    declaration = package / "private-tools.json"
    if contents is None:
        declaration.unlink()
    else:
        declaration.write_text(contents)
    with pytest.raises(ToolRuntimeError):
        resolve_extension_tool(package)


@pytest.mark.parametrize(
    "name,target",
    [
        ("elsewhere", "/output/tmp"),
        ("rootfs/tmp", "/etc"),
    ],
)
def test_rejects_unapproved_symlinks(tmp_path: Path, name: str, target: str) -> None:
    member = _file_info(name, b"")
    member.type = tarfile.SYMTYPE
    member.mode = 0o777
    member.linkname = target
    archive, spec = _artifact(tmp_path, extras=(member,))
    with pytest.raises(ToolRuntimeError, match="symlink"):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)


def test_rejects_huge_tar_metadata_before_reading_body(tmp_path: Path) -> None:
    header = tarfile.TarInfo("pax-header")
    header.type = tarfile.XHDTYPE
    header.size = tools.MAX_TOOL_TAR_METADATA_BYTES + 1
    archive = tmp_path / "metadata.tar"
    archive.write_bytes(header.tobuf())
    spec = tools.ToolSpec("a" * 64, 0)
    with pytest.raises(ToolRuntimeError, match=r"invalid tool tar archive|metadata"):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)


def _output_artifact(
    tmp_path: Path, *, include_tmp_link: bool = False
) -> tuple[Path, tools.ToolSpec]:
    inventory: dict[str, object] = {
        "rootfs": {"type": "directory", "mode": 0o755, "uid": 0, "gid": 0, "size": 0},
        "rootfs/output": {
            "type": "directory",
            "mode": 0o700,
            "uid": 62000,
            "gid": 62000,
            "size": 0,
        },
        "rootfs/output/tmp": {
            "type": "directory",
            "mode": 0o700,
            "uid": 62000,
            "gid": 62000,
            "size": 0,
        },
    }
    if include_tmp_link:
        inventory["rootfs/tmp"] = {
            "type": "symlink",
            "mode": 0o777,
            "uid": 0,
            "gid": 0,
            "size": 0,
            "target": "/output/tmp",
        }
    manifest = json.dumps({"files": inventory}).encode()
    spec = tools.ToolSpec(hashlib.sha256(manifest).hexdigest(), 0)
    archive = tmp_path / "symlink.tar"
    with tarfile.open(archive, "w") as stream:
        stream.addfile(_file_info("manifest.json", manifest), io.BytesIO(manifest))
        for name, raw in inventory.items():
            assert isinstance(raw, dict)
            info = _file_info(name, b"")
            info.type = tarfile.SYMTYPE if name == "rootfs/tmp" else tarfile.DIRTYPE
            info.mode, info.uid, info.gid = raw["mode"], raw["uid"], raw["gid"]
            info.linkname = str(raw.get("target", ""))
            stream.addfile(info)
    return archive, spec


def test_actual_runtime_output_directories(tmp_path: Path) -> None:
    archive, spec = _output_artifact(tmp_path)
    runtime = tools.extract_tool_archive(archive, tmp_path / "staging", spec)
    assert (runtime / "rootfs/output/tmp").is_dir()
    assert not tuple((runtime / "rootfs/output/tmp").iterdir())
    assert not (runtime / "output").exists()
    tools.validate_tool_runtime(runtime, spec)


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink privilege is optional")
def test_allowed_tmp_link_is_never_followed(tmp_path: Path) -> None:
    archive, spec = _output_artifact(tmp_path, include_tmp_link=True)
    runtime = tools.extract_tool_archive(archive, tmp_path / "staging", spec)
    tools.validate_tool_runtime(runtime, spec)
    assert (runtime / "rootfs/tmp").is_symlink()


@pytest.mark.parametrize(
    "name,kind,mode,uid",
    [
        ("output", tarfile.DIRTYPE, 0o700, 62000),
        ("rootfs/output", tarfile.DIRTYPE, 0o755, 62000),
        ("rootfs/output/tmp", tarfile.DIRTYPE, 0o700, 0),
        ("rootfs/output/file", tarfile.REGTYPE, 0o644, 62000),
        ("rootfs/output/tmp/file", tarfile.REGTYPE, 0o644, 62000),
        ("rootfs/output/tmp/nested", tarfile.DIRTYPE, 0o700, 62000),
        ("rootfs/output", tarfile.REGTYPE, 0o700, 62000),
        ("rootfs/bin/tool", tarfile.REGTYPE, 0o600, 0),
        ("rootfs/bin/tool", tarfile.REGTYPE, 0o700, 0),
    ],
)
def test_rejects_unsafe_output_layout_and_file_modes(
    tmp_path: Path, name: str, kind: bytes, mode: int, uid: int
) -> None:
    info = _file_info(name, b"")
    info.type, info.mode, info.uid, info.gid = kind, mode, uid, uid
    archive, spec = _artifact(tmp_path, extras=(info,))
    with pytest.raises(ToolRuntimeError, match=r"unsafe tool|must be empty"):
        tools.extract_tool_archive(archive, tmp_path / "staging", spec)
