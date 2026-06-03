import asyncio
from collections.abc import Awaitable, Callable

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

StartupCheck = Callable[[Bot], Awaitable[None]]

_checks: dict[str, StartupCheck] = {}
_ready_events: dict[str, asyncio.Event] = {}
_startup_task: asyncio.Task[None] | None = None


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
        except Exception as e:
            logger.warning(f"startup check {name} failed: {e}")
        finally:
            event.set()


async def ensure_startup_ready(bot: Bot) -> None:
    global _startup_task

    if not _checks:
        return

    if _startup_task is None or _startup_task.done():
        _startup_task = asyncio.create_task(_run_checks(bot))

    await _startup_task


async def wait_startup_ready() -> None:
    events = list(_ready_events.values())
    if not events:
        return

    await asyncio.gather(*(event.wait() for event in events))


@get_driver().on_bot_connect
async def run_registered_startup_checks(bot: Bot) -> None:
    await ensure_startup_ready(bot)
