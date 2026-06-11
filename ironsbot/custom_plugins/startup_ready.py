import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

StartupCheck = Callable[[Bot], Awaitable[None]]

_checks: dict[str, StartupCheck] = {}
_ready_events: dict[str, asyncio.Event] = {}
_startup_task_state: dict[str, asyncio.Task[None] | None] = {"task": None}
_startup_ready_runtime_state = {"registered": False}


def register_startup_check(name: str, check: StartupCheck) -> None:
    _checks[name] = check
    _ready_events.setdefault(name, asyncio.Event())


def mark_startup_ready(name: str) -> None:
    _ready_events.setdefault(name, asyncio.Event()).set()


async def _run_checks(bot: Bot) -> None:
    for name, check in list(_checks.items()):
        event = _ready_events.setdefault(name, asyncio.Event())
        if event.is_set():
            continue

        try:
            await check(bot)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"startup check {name} failed: {e}")
        finally:
            event.set()


async def ensure_startup_ready(bot: Bot) -> None:
    if not _checks:
        return

    startup_task = _startup_task_state["task"]
    if startup_task is None or startup_task.done():
        startup_task = asyncio.create_task(_run_checks(bot))
        _startup_task_state["task"] = startup_task

    await startup_task


async def wait_startup_ready() -> None:
    events = list(_ready_events.values())
    if not events:
        return

    await asyncio.gather(*(event.wait() for event in events))


async def run_registered_startup_checks(bot: Bot) -> None:
    await ensure_startup_ready(bot)


def _setup_startup_ready_runtime(driver: Any) -> None:
    if _startup_ready_runtime_state["registered"]:
        return

    driver.on_bot_connect(run_registered_startup_checks)
    _startup_ready_runtime_state["registered"] = True


def setup_startup_ready_runtime() -> None:
    _setup_startup_ready_runtime(get_driver())
