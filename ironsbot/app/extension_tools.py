# SPDX-License-Identifier: MIT
"""Bounded, non-executing validation of optional private tool archives.

Extraction only prepares a staging tree. The installer must run its isolated
probe before atomically publishing the version; this module never activates it.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tarfile
from pathlib import Path, PurePosixPath
from typing import NoReturn

from ironsbot.extensions import tool_runtime
from ironsbot.extensions.tool_runtime import (
    MAX_TOOL_UNPACKED_BYTES,
    TOOL_DIRECTORY,
    ToolRuntimeError,
    ToolSpec,
    is_tool_fingerprint,
    read_tool_json,
    require_no_symlinks,
)

TOOL_SPEC_MANIFEST = tool_runtime.TOOL_SPEC_MANIFEST
MAX_TOOL_ARCHIVE_BYTES = 1024**3
MAX_TOOL_FILES = 20_000
MAX_TOOL_INVENTORY_BYTES = 16 * 1024 * 1024
MAX_TOOL_TAR_METADATA_BYTES = 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_OUTPUT_UID = 62000
_OUTPUT_DIRECTORIES = frozenset({"rootfs/output", "rootfs/output/tmp"})
_ALLOWED_SYMLINK = "rootfs/tmp"
_ALLOWED_SYMLINK_TARGET = "/output/tmp"


class _BoundedTarInfo(tarfile.TarInfo):
    """Bound extension headers before tarfile reads their bodies into memory."""

    __slots__ = ()

    @classmethod
    def frombuf(
        cls, buf: bytes | bytearray, encoding: str, errors: str
    ) -> _BoundedTarInfo:
        info = super().frombuf(buf, encoding, errors)
        if (
            info.type
            in {
                tarfile.XHDTYPE,
                tarfile.XGLTYPE,
                tarfile.GNUTYPE_LONGNAME,
                tarfile.GNUTYPE_LONGLINK,
            }
            and not 0 <= info.size <= MAX_TOOL_TAR_METADATA_BYTES
        ):
            _fail("tool tar extension metadata is too large")
        if info.type == tarfile.GNUTYPE_SPARSE:
            _fail("sparse tool archive entries are unsupported")
        return info


def _fail(message: str) -> NoReturn:
    raise ToolRuntimeError(message)


def read_tool_spec(code_root: Path) -> ToolSpec | None:
    spec = tool_runtime.read_tool_declaration(code_root)
    if spec is not None:
        validate_tool_host(spec)
    return spec


def validate_tool_host(spec: ToolSpec) -> None:
    """Installer wrapper retaining the shared read-only host validation."""

    tool_runtime.validate_tool_host(spec)


def _relative_path(name: str) -> PurePosixPath:
    # Reject aliases before PurePosixPath can normalize them (also on Windows).
    parts = name.split("/")
    if not name or any(part in {"", ".", ".."} for part in parts):
        _fail("invalid tool entry path: " + name)
    if "\\" in name or ":" in name or "\x00" in name:
        _fail("invalid tool entry path: " + name)
    return PurePosixPath(name)


def _safe_metadata(name: str, kind: str, mode: int, uid: int, gid: int) -> None:
    output = name in _OUTPUT_DIRECTORIES
    if (output and kind != "directory") or (
        name.startswith("rootfs/output/") and not output
    ):
        _fail("tool output directories must be empty: " + name)
    if kind == "symlink":
        if name != _ALLOWED_SYMLINK or (mode, uid, gid) != (0o777, 0, 0):
            _fail("unsafe tool symlink metadata: " + name)
        return
    owner = _OUTPUT_UID if output else 0
    if uid != owner or gid != owner:
        _fail("unsafe tool ownership: " + name)
    if kind == "directory":
        if mode != (0o700 if output else 0o755):
            _fail("unsafe tool directory mode: " + name)
    elif kind != "file" or mode not in {0o644, 0o755}:
        _fail("unsafe tool file mode: " + name)


def _apply_metadata(path: Path, mode: int, uid: int, gid: int) -> None:
    if os.name == "posix":
        os.chown(path, uid, gid, follow_symlinks=False)
        if not path.is_symlink():
            path.chmod(mode)


def _validate_permissions(path: Path, mode: int, uid: int = 0, gid: int = 0) -> None:
    if os.name != "posix":
        return
    info = path.lstat()
    if stat.S_IMODE(info.st_mode) != mode or info.st_uid != uid or info.st_gid != gid:
        _fail("tool runtime permissions mismatch: " + str(path))


def _member_kind(member: tarfile.TarInfo) -> str:
    if member.sparse is not None:
        _fail("sparse tool archive entries are unsupported")
    if member.isdir():
        return "directory"
    if member.isfile():
        return "file"
    if member.issym():
        return "symlink"
    _fail("unsupported tool archive entry: " + member.name)
    return ""


def _write_member(
    tar: tarfile.TarFile, member: tarfile.TarInfo, target: Path, kind: str
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == "directory":
        target.mkdir(exist_ok=True)
    elif kind == "symlink":
        if member.linkname != _ALLOWED_SYMLINK_TARGET:
            _fail("unsafe tool symlink target")
        target.symlink_to(member.linkname)
    else:
        source = tar.extractfile(member)
        if source is None:
            _fail("cannot read tool archive entry")
        with source, target.open("xb") as output:
            remaining = member.size
            while remaining:
                chunk = source.read(min(remaining, _CHUNK_BYTES))
                if not chunk:
                    _fail("truncated tool archive entry")
                output.write(chunk)
                remaining -= len(chunk)
    _apply_metadata(target, member.mode, member.uid, member.gid)


def _extract_member(
    tar: tarfile.TarFile, member: tarfile.TarInfo, destination: Path
) -> tuple[str, int]:
    member_name = member.name.rstrip("/") if member.isdir() else member.name
    relative = _relative_path(member_name)
    if relative.parts[0] != "ironsbot_tools":
        _fail("tool archive entry is outside ironsbot_tools")
    if len(relative.parts) == 1:
        if not member.isdir() or (member.mode, member.uid, member.gid) != (0o755, 0, 0):
            _fail("invalid tool archive root")
        return str(relative), 0
    if relative.parts[1] != TOOL_DIRECTORY:
        _fail("tool archive entry is outside somua")
    local = PurePosixPath(*relative.parts[1:])
    target = destination.joinpath(*local.parts)
    require_no_symlinks(target.parent)
    kind = _member_kind(member)
    name = str(PurePosixPath(*local.parts[1:])) if len(local.parts) > 1 else "."
    _safe_metadata(name, kind, member.mode, member.uid, member.gid)
    if member.size < 0 or (kind != "file" and member.size != 0):
        _fail("invalid tool archive entry size")
    _write_member(tar, member, target, kind)
    return str(relative), member.size


def extract_tool_archive(archive: Path, destination: Path, spec: ToolSpec) -> Path:
    """Extract into an absent or empty caller-owned staging directory only.

    Nothing is overwritten or published. Failed staging cleanup belongs to the
    caller, which must also probe the result before activation.
    """

    require_no_symlinks(archive)
    require_no_symlinks(destination)
    if archive.stat().st_size > MAX_TOOL_ARCHIVE_BYTES:
        _fail("tool archive is too large")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        _fail("tool staging directory must be empty")
    seen: set[str] = set()
    total = 0
    try:
        # The uncompressed Docker stream is read sequentially, never materialized.
        with (
            archive.open("rb") as stream,
            tarfile.open(fileobj=stream, mode="r|", tarinfo=_BoundedTarInfo) as tar,
        ):
            for member in tar:
                if len(seen) >= MAX_TOOL_FILES:
                    _fail("tool archive has too many entries")
                canonical = str(_relative_path(member.name.rstrip("/")))
                if canonical in seen:
                    _fail("duplicate tool archive entry: " + canonical)
                seen.add(canonical)
                if member.size < 0 or total + member.size > MAX_TOOL_UNPACKED_BYTES:
                    _fail("tool archive unpacked size is too large")
                _, size = _extract_member(tar, member, destination)
                total += size
    except tarfile.TarError as error:
        msg = "invalid tool tar archive"
        raise ToolRuntimeError(msg) from error
    runtime = destination / TOOL_DIRECTORY
    validate_tool_runtime(runtime, spec)
    return runtime


def _hash_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _inventory(runtime: Path, spec: ToolSpec) -> dict[str, object]:
    manifest = runtime / "manifest.json"
    require_no_symlinks(manifest)
    info = manifest.stat()
    if info.st_size > MAX_TOOL_INVENTORY_BYTES:
        _fail("tool inventory is too large")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail("tool inventory must be a regular file without hardlinks")
    _validate_permissions(manifest, 0o644)
    if _hash_file(manifest) != spec.fingerprint:
        _fail("tool inventory fingerprint mismatch")
    payload = read_tool_json(manifest, max_bytes=MAX_TOOL_INVENTORY_BYTES)
    files = payload.get("files")
    if not isinstance(files, dict) or len(files) > MAX_TOOL_FILES:
        _fail("invalid tool inventory files")
    return files


def _validate_entry_content(
    target: Path, name: str, raw: dict[str, object], kind: str, size: int
) -> int:
    if kind == "symlink":
        if target.readlink().as_posix() != _ALLOWED_SYMLINK_TARGET:
            _fail("tool inventory symlink mismatch")
        if raw.get("target") != _ALLOWED_SYMLINK_TARGET or size != 0:
            _fail("invalid tool inventory symlink")
        return 0
    if kind == "directory":
        if size != 0:
            _fail("invalid tool inventory directory size")
        return 0
    info = target.stat()
    if info.st_nlink != 1:
        _fail("tool runtime contains a hardlink")
    if info.st_size != size or info.st_size > MAX_TOOL_UNPACKED_BYTES:
        _fail("tool inventory size mismatch: " + name)
    if (
        not is_tool_fingerprint(raw.get("sha256"))
        or _hash_file(target) != raw["sha256"]
    ):
        _fail("tool inventory hash mismatch: " + name)
    return info.st_size


def _validate_inventory_entry(runtime: Path, name: str, raw: object) -> int:
    relative = _relative_path(name)
    if name == "manifest.json" or not isinstance(raw, dict):
        _fail("invalid tool inventory entry")
    kind = raw.get("type")
    mode, uid, gid, size = (raw.get(key) for key in ("mode", "uid", "gid", "size"))
    if not isinstance(kind, str):
        _fail("invalid tool inventory metadata")
    if (
        type(mode) is not int
        or type(uid) is not int
        or type(gid) is not int
        or type(size) is not int
    ):
        _fail("invalid tool inventory metadata")
    _safe_metadata(name, kind, int(mode), int(uid), int(gid))
    target = runtime.joinpath(*relative.parts)
    require_no_symlinks(target.parent)
    info = target.lstat()
    actual_kind = (
        "symlink"
        if stat.S_ISLNK(info.st_mode)
        else "directory"
        if stat.S_ISDIR(info.st_mode)
        else "file"
        if stat.S_ISREG(info.st_mode)
        else "unsupported"
    )
    if actual_kind != kind:
        _fail("tool inventory type mismatch: " + name)
    _validate_permissions(target, mode, uid, gid)
    return _validate_entry_content(target, name, raw, kind, int(size))


def validate_tool_runtime(runtime: Path, spec: ToolSpec) -> None:
    """Recheck a complete tree, including cached immutable versions, without exec."""

    require_no_symlinks(runtime)
    _validate_permissions(runtime, 0o755)
    files = _inventory(runtime, spec)
    actual: set[str] = set()
    pending = [runtime]
    while pending:
        for path in pending.pop().iterdir():
            actual.add(path.relative_to(runtime).as_posix())
            if len(actual) > MAX_TOOL_FILES:
                _fail("tool runtime has too many entries")
            if not path.is_symlink() and path.is_dir():
                pending.append(path)
    if actual != set(files) | {"manifest.json"}:
        _fail("tool runtime has missing or undeclared entries")
    total = 0
    for name, entry in files.items():
        total += _validate_inventory_entry(runtime, name, entry)
        if total > MAX_TOOL_UNPACKED_BYTES:
            _fail("tool runtime is too large")
    if total != spec.size_bytes:
        _fail("tool inventory total size mismatch")
