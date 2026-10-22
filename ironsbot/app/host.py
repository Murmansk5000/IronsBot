# SPDX-License-Identifier: MIT
"""One ASGI lifespan owns startup, failed-start cleanup and shutdown."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

    from ironsbot.app.lifecycle import ApplicationLifecycle


@asynccontextmanager
async def application_lifespan(
    lifecycle: ApplicationLifecycle, _app: FastAPI
) -> AsyncIterator[None]:
    try:
        await lifecycle.startup()
        yield
    finally:
        await lifecycle.shutdown()
