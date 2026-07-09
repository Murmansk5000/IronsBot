import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import nonebot
from pytest import MonkeyPatch

from ironsbot.config.loader import clear_app_config_cache
from ironsbot.config.models.seer import MintmarkQueryConfig

if TYPE_CHECKING:
    from seerapi_models import MintmarkORM

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")
clear_app_config_cache()

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.seer.query.upstream_commands import mintmark


class FakeMintmark:
    def __init__(self, id_: int, *, connected: bool = False) -> None:
        self.id = id_
        self.connected_universal_parts = [object()] if connected else []


def test_mintmark_query_config_merges_connected_by_default() -> None:
    assert MintmarkQueryConfig().merge_connected is True


def test_deduplicate_and_filter_hides_connected_when_merge_enabled(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mintmark,
        "get_mintmark_query_config",
        lambda: MintmarkQueryConfig(merge_connected=True),
    )
    items = [
        cast("MintmarkORM", FakeMintmark(1)),
        cast("MintmarkORM", FakeMintmark(2, connected=True)),
        cast("MintmarkORM", FakeMintmark(1)),
    ]

    result = mintmark._deduplicate_and_filter(items)

    assert [item.id for item in result] == [1]


def test_deduplicate_and_filter_keeps_connected_when_merge_disabled(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mintmark,
        "get_mintmark_query_config",
        lambda: MintmarkQueryConfig(merge_connected=False),
    )
    items = [
        cast("MintmarkORM", FakeMintmark(1)),
        cast("MintmarkORM", FakeMintmark(2, connected=True)),
        cast("MintmarkORM", FakeMintmark(1)),
    ]

    result = mintmark._deduplicate_and_filter(items)

    assert [item.id for item in result] == [1, 2]
