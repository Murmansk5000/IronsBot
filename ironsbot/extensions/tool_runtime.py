# SPDX-License-Identifier: MIT
"""Read-only discovery of explicitly activated private tool runtimes."""

from __future__ import annotations

import json
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path

TOOL_SCHEMA_VERSION = 1
TOOL_CONTRACT_VERSION = 1
TOOL_PLATFORM = "linux/amd64"
TOOL_LIBC = "glibc"
TOOL_MIN_GLIBC = "2.36"
TOOL_PYTHON = "3.11"
TOOL_CAPABILITIES = {"somua_avatar": 1}
TOOL_ARCHIVE_PATH = "/ironsbot_tools"
TOOL_DIRECTORY = "somua"
TOOL_PROBE_MODULE = "ironsbot_private_somua.install_probe"
INSTALLED_TOOLS_MANIFEST = ".installed-tools.json"
TOOL_SPEC_MANIFEST = "private-tools.json"
MAX_TOOL_METADATA_BYTES = 1024 * 1024
MAX_TOOL_UNPACKED_BYTES = 1024**3
_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")


class ToolRuntimeError(ValueError):
    """An untrusted tool declaration or runtime failed validation."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    fingerprint: str
    size_bytes: int
    schema_version: int = TOOL_SCHEMA_VERSION
    contract_version: int = TOOL_CONTRACT_VERSION
    platform: str = TOOL_PLATFORM
    libc: str = TOOL_LIBC
    min_glibc: str = TOOL_MIN_GLIBC
    python: str = TOOL_PYTHON
    archive_path: str = TOOL_ARCHIVE_PATH
    tool_directory: str = TOOL_DIRECTORY
    probe_module: str = TOOL_PROBE_MODULE

    @property
    def capabilities(self) -> dict[str, int]:
        return dict(TOOL_CAPABILITIES)


def read_tool_declaration(code_root: Path) -> ToolSpec | None:
    """Read the shared compatibility contract without invoking tools or host checks."""

    path = code_root / TOOL_SPEC_MANIFEST
    require_no_symlinks(path)
    if not path.exists():
        return None
    payload = read_tool_json(path)
    expected = {
        "schema_version": TOOL_SCHEMA_VERSION,
        "contract_version": TOOL_CONTRACT_VERSION,
        "platform": TOOL_PLATFORM,
        "libc": TOOL_LIBC,
        "min_glibc": TOOL_MIN_GLIBC,
        "python": TOOL_PYTHON,
        "capabilities": TOOL_CAPABILITIES,
        "archive_path": TOOL_ARCHIVE_PATH,
        "tool_directory": TOOL_DIRECTORY,
        "probe_module": TOOL_PROBE_MODULE,
    }
    for key, value in expected.items():
        if payload.get(key) != value or type(payload.get(key)) is not type(value):
            msg = f"unsupported tool specification field: {key}"
            raise ToolRuntimeError(msg)
    capabilities = payload["capabilities"]
    if not isinstance(capabilities, dict) or any(
        type(value) is not int for value in capabilities.values()
    ):
        msg = "invalid tool capabilities"
        raise ToolRuntimeError(msg)
    fingerprint = payload.get("fingerprint")
    size = payload.get("size_bytes")
    if not is_tool_fingerprint(fingerprint):
        msg = "invalid tool fingerprint"
        raise ToolRuntimeError(msg)
    if type(size) is not int or not 0 <= size <= MAX_TOOL_UNPACKED_BYTES:
        msg = "invalid tool inventory size"
        raise ToolRuntimeError(msg)
    return ToolSpec(fingerprint=str(fingerprint), size_bytes=size)


def validate_tool_host(spec: ToolSpec) -> None:
    """Check the actual process host for both fresh and cached installations."""

    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        msg = "tool runtime requires linux/amd64"
        raise ToolRuntimeError(msg)
    libc, version = platform.libc_ver()
    try:
        actual = tuple(int(part) for part in version.split("."))
        minimum = tuple(int(part) for part in spec.min_glibc.split("."))
    except ValueError as error:
        msg = "cannot determine host glibc version"
        raise ToolRuntimeError(msg) from error
    if libc != "glibc" or actual < minimum:
        msg = "tool runtime requires glibc >= " + spec.min_glibc
        raise ToolRuntimeError(msg)
    if f"{sys.version_info.major}.{sys.version_info.minor}" != spec.python:
        msg = "tool runtime requires Python " + spec.python
        raise ToolRuntimeError(msg)


def is_tool_fingerprint(value: object) -> bool:
    return isinstance(value, str) and _FINGERPRINT.fullmatch(value) is not None


def require_no_symlinks(path: Path) -> None:
    """Reject symlinks in every existing component, including broken links."""

    for component in (path, *path.parents):
        if component.is_symlink():
            msg = f"tool path contains a symlink: {component}"
            raise ToolRuntimeError(msg)


def read_tool_json(
    path: Path, *, max_bytes: int = MAX_TOOL_METADATA_BYTES
) -> dict[str, object]:
    require_no_symlinks(path)
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        msg = "tool metadata is too large"
        raise ToolRuntimeError(msg)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as error:
        msg = "tool metadata is not valid JSON"
        raise ToolRuntimeError(msg) from error
    if not isinstance(value, dict):
        msg = "tool metadata must be an object"
        raise ToolRuntimeError(msg)
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            msg = "tool metadata repeats a key"
            raise ToolRuntimeError(msg)
        result[key] = value
    return result


def _validate_cached_spec(package_root: Path, fingerprint: str) -> None:
    try:
        spec = read_tool_declaration(package_root)
    except OSError as error:
        msg = "cached tool declaration is unreadable"
        raise ToolRuntimeError(msg) from error
    if spec is None:
        msg = "cached tool declaration is missing"
        raise ToolRuntimeError(msg)
    if spec.fingerprint != fingerprint:
        msg = "cached tool declaration fingerprint mismatch"
        raise ToolRuntimeError(msg)
    validate_tool_host(spec)


def resolve_extension_tool(
    package_root: Path,
    name: str = TOOL_DIRECTORY,
) -> Path | None:
    """Resolve an activated immutable runtime without importing private code."""

    require_no_symlinks(package_root)
    marker = package_root / INSTALLED_TOOLS_MANIFEST
    if not marker.exists() and not marker.is_symlink():
        return None
    payload = read_tool_json(marker)
    if (
        type(payload.get("schema")) is not int
        or payload["schema"] != TOOL_SCHEMA_VERSION
    ):
        msg = "unsupported installed tools schema"
        raise ToolRuntimeError(msg)
    tools = payload.get("tools")
    if not isinstance(tools, dict) or name != TOOL_DIRECTORY:
        msg = "invalid installed tools declaration"
        raise ToolRuntimeError(msg)
    entry = tools.get(name)
    if entry is None:
        return None
    if not isinstance(entry, dict) or not is_tool_fingerprint(entry.get("fingerprint")):
        msg = "invalid installed tool fingerprint"
        raise ToolRuntimeError(msg)
    _validate_cached_spec(package_root, str(entry["fingerprint"]))
    raw_path = entry.get("path")
    if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
        msg = "installed tool path must be absolute"
        raise ToolRuntimeError(msg)
    runtime = Path(raw_path)
    require_no_symlinks(runtime)
    data_root = package_root.parent.resolve()
    expected = data_root / "tools" / str(entry["fingerprint"]) / name
    if runtime.resolve() != expected or not runtime.is_dir():
        msg = "installed tool path is outside its immutable version"
        raise ToolRuntimeError(msg)
    return runtime.resolve()
