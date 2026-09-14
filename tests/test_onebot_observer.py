from __future__ import annotations

import subprocess
import sys
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import ActionFailed, Adapter, Bot
from nonebot.exception import IgnoredException

from ironsbot.config.models.settings import BotConfig
from ironsbot.integrations.onebot.observer import (
    READ_ONLY_APIS,
    ObserverOneBotAdapter,
    ignore_observer_event,
)
from tests.helpers.onebot_events import group_message_event


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "api",
    [
        "send_msg",
        "send_group_msg",
        "send_private_msg",
        "send_group_forward_msg",
        "send_private_forward_msg",
        "send_group_msg_async",
        "send_poke",
        "set_group_ban",
        "delete_msg",
        "unknown_future_api",
    ],
)
async def test_observer_denies_writes_at_real_bot_api_boundary(
    monkeypatch: pytest.MonkeyPatch,
    api: str,
) -> None:
    wire = AsyncMock()
    monkeypatch.setattr(Adapter, "_call_api", wire)
    monkeypatch.setattr(Bot, "_calling_api_hook", set())
    monkeypatch.setattr(Bot, "_called_api_hook", set())
    bot = Bot(object.__new__(ObserverOneBotAdapter), "123456")

    with pytest.raises(ActionFailed):
        await bot.call_api(api, message="must not send")
    wire.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("api", sorted(READ_ONLY_APIS))
async def test_observer_preserves_read_only_calls(
    monkeypatch: pytest.MonkeyPatch,
    api: str,
) -> None:
    wire = AsyncMock(return_value={"result": "read"})
    monkeypatch.setattr(Adapter, "_call_api", wire)
    monkeypatch.setattr(Bot, "_calling_api_hook", set())
    monkeypatch.setattr(Bot, "_called_api_hook", set())
    bot = Bot(object.__new__(ObserverOneBotAdapter), "123456")

    assert await bot.call_api(api, no_cache=True) == {"result": "read"}
    wire.assert_awaited_once_with(bot, api, no_cache=True)


@pytest.mark.asyncio
async def test_observer_stops_onebot_event_before_business_handlers() -> None:
    with pytest.raises(IgnoredException):
        await ignore_observer_event(group_message_event("米米号123456"))


def test_observer_is_opt_in() -> None:
    assert BotConfig().onebot_observer is False
    assert BotConfig(onebot_observer=True).onebot_observer is True


def test_observer_preprocessor_registers_in_real_nonebot() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import nonebot
import asyncio
import os
from unittest.mock import patch
from nonebot.adapters.onebot.v11 import Bot
from nonebot.message import _apply_event_preprocessors
from ironsbot.app.bootstrap import bootstrap
from ironsbot.config.loader import load_settings
from ironsbot.integrations.onebot.observer import ObserverOneBotAdapter
from tests.helpers.onebot_events import group_message_event
os.environ['APP_CONFIG_PATH'] = 'config.example.toml'
settings = load_settings()
settings.bot.onebot_observer = True
with patch('ironsbot.app.bootstrap.load_settings', return_value=settings):
    application = bootstrap()
adapter = nonebot.get_adapter('OneBot V11')
assert isinstance(adapter, ObserverOneBotAdapter)
event = group_message_event('help')
allowed = asyncio.run(
    _apply_event_preprocessors(Bot(adapter, '123456'), event, {})
)
assert allowed is False
print('OBSERVER_REGISTERED')
""",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OBSERVER_REGISTERED" in result.stdout
