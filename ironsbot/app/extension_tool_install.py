# SPDX-License-Identifier: MIT
"""Serialize optional native-tool installation before code activation."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import stat
import sys
from contextlib import asynccontextmanager
from functools import partial
from typing import TYPE_CHECKING, Protocol, TypeVar
from uuid import uuid4

from anyio import Path as AsyncPath

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.tasks import run_owned_blocking
from ironsbot.extensions.tool_runtime import require_no_symlinks
from ironsbot.services.operations.docker_models import DockerImageArchiveRequest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

MAX_TOOL_DOWNLOAD_BYTES = 1024 * 1024 * 1024
PROBE_TIMEOUT_SECONDS = 60
INSTALL_LOCK_TIMEOUT_SECONDS = 120
_T = TypeVar("_T")


async def finish_thread(operation: Callable[[], _T]) -> _T:
    """Finish writes before cancellation permits the caller to remove staging."""
    owner = TaskOwner()
    return await run_owned_blocking(
        operation, spawn=owner.create_draining, name="private-tool-install-worker"
    )


class ToolArchiveGateway(Protocol):
    async def save_image_archive(
        self, request: DockerImageArchiveRequest, destination: Path, *, max_bytes: int
    ) -> None: ...


def _try_lock(file: int) -> bool:
    try:
        if os.name == "posix":
            import fcntl

            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            import msvcrt

            os.lseek(file, 0, os.SEEK_SET)
            msvcrt.locking(file, msvcrt.LK_NBLCK, 1)
    except (BlockingIOError, PermissionError):
        return False
    return True


@asynccontextmanager
async def installation_lock(root: Path) -> AsyncIterator[None]:
    await AsyncPath(root).mkdir(parents=True, exist_ok=True)
    lock = root / ".install.lock"
    require_no_symlinks(lock)
    descriptor = os.open(
        lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or (
            os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077)
        ):
            message = "Unsafe private extension installation lock"
            raise ValueError(message)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        async with asyncio.timeout(INSTALL_LOCK_TIMEOUT_SECONDS):
            while not _try_lock(descriptor):  # noqa: ASYNC110 - cross-process lock
                await asyncio.sleep(0.1)
        yield
    finally:
        os.close(descriptor)


async def probe_tools(code: Path, module: str, runtime: Path) -> None:
    """Run the trusted extension's safety test without inheriting credentials."""
    bootstrap = (
        "import importlib,pathlib,sys;sys.path.insert(0,sys.argv[1]);"
        "importlib.import_module(sys.argv[2]).main(pathlib.Path(sys.argv[3]))"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        bootstrap,
        str(await AsyncPath(code).resolve()),
        module,
        str(await AsyncPath(runtime).resolve()),
        env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=os.name == "posix",
    )
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            return_code = await process.wait()
        if return_code:
            message = "Private tool safety probe failed"
            raise ValueError(message)
    finally:
        if process.returncode is None:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            await process.wait()


async def install_tools(
    code: Path,
    root: Path,
    gateway: ToolArchiveGateway,
    request: DockerImageArchiveRequest,
) -> None:
    import shutil

    from ironsbot.app.extension_tools import (
        extract_tool_archive,
        read_tool_spec,
        validate_tool_runtime,
    )

    spec = read_tool_spec(code)
    if spec is None:
        return
    tools = root / "tools"
    tools.mkdir(mode=0o755, exist_ok=True)
    final = tools / spec.fingerprint
    runtime = final / spec.tool_directory
    if final.exists():
        await finish_thread(partial(validate_tool_runtime, runtime, spec))
        await probe_tools(code, spec.probe_module, runtime)
    else:
        staging = tools / f".staging-{uuid4().hex}"
        archive = tools / f".download-{uuid4().hex}.tar"
        try:
            await gateway.save_image_archive(
                DockerImageArchiveRequest(
                    image=request.image,
                    archive_path=spec.archive_path,
                    socket_path=request.socket_path,
                    timeout_seconds=request.timeout_seconds,
                ),
                archive,
                max_bytes=MAX_TOOL_DOWNLOAD_BYTES,
            )
            candidate = await finish_thread(
                partial(extract_tool_archive, archive, staging, spec)
            )
            await probe_tools(code, spec.probe_module, candidate)
            staging.rename(final)
        finally:
            archive.unlink(missing_ok=True)
            shutil.rmtree(staging, ignore_errors=True)
    (code / ".installed-tools.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "tools": {
                    spec.tool_directory: {
                        "path": str(runtime.resolve()),
                        "fingerprint": spec.fingerprint,
                    }
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
