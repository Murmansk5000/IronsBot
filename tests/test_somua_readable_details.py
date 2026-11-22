from __future__ import annotations

import struct
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from ironsbot.core import time as clock
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.seer_data.somua_text_repository import (
    PublishedSomuaTextResolver,
)
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.observation_cache import ObservationCache
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.player_shortcut_contracts import PlayerShortcutDependencies
from ironsbot.services.seer.somua_codec import parse_somua_detail
from ironsbot.services.seer.somua_detail import (
    cached_detail_reply,
    fetch_somua_detail_reply,
)
from ironsbot.services.seer.somua_models import SomuaCommonSlot, SomuaOverviewReply
from ironsbot.services.seer.somua_presentation import (
    SomuaEntryText,
    SomuaTextSnapshot,
    format_somua_detail,
    format_somua_time,
    visible_somua_text,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

    from ironsbot.services.seer.data import DataQuery
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.query_result import QueryReply
    from ironsbot.services.seer.somua_models import SomuaDetail

PLAYER = 700001
SEQUENCE = 111
TTL = 300
STAMP = int(datetime(2026, 11, 21, 16, tzinfo=timezone.utc).timestamp())


def _wire() -> bytes:
    parts = (9001, 9002, 9001, 9002, 0, 9001, 0, 0, 0)
    head = struct.pack(
        "!I32s6I6I3I4I9I",
        SEQUENCE,
        b"Example",
        4,
        0,
        3,
        STAMP,
        0,
        0,
        1,
        0,
        2,
        1,
        0,
        2,
        0,
        1001,
        2001,
        3001,
        3001,
        3002,
        3999,
        *parts,
    )
    parent = struct.pack("!32sI9I16sI", b"Parent", 3, *parts, b"Owner", STAMP)
    return head + parent + parent + struct.pack("!IBI", 0, 0, PLAYER)


@pytest.fixture
def detail() -> SomuaDetail:
    return parse_somua_detail(_wire(), player_id=PLAYER, sequence=SEQUENCE)


class _Publication:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.calls = 0

    @contextmanager
    def query(self, operation: DataQuery[Any]) -> Iterator[Any]:
        self.calls += 1
        with Session(self.engine) as session:
            yield operation(session)


@pytest.fixture
def publication() -> Iterator[_Publication]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE somua_entry (id INTEGER PRIMARY KEY, "
                "name TEXT, desc TEXT, type INTEGER)"
            )
        )
        connection.execute(
            text("INSERT INTO somua_entry VALUES (:id, :name, :description, :kind)"),
            [
                {
                    "id": 1001,
                    "name": "示例魂印",
                    "description": "[color=#52a5f2]魂印效果[/color]<sprite name=ATK>",
                    "kind": 1,
                },
                {"id": 2001, "name": "示例性格", "description": "性格说明", "kind": 4},
                {
                    "id": 3001,
                    "name": "示例词条甲",
                    "description": "<color=#ffffff>效果甲</color><br>第二行",
                    "kind": 3,
                },
                {"id": 3002, "name": "示例词条乙", "description": "效果乙", "kind": 3},
            ],
        )
        connection.execute(
            text("CREATE TABLE somua_gene (id INTEGER PRIMARY KEY, gene TEXT)")
        )
        connection.execute(
            text("INSERT INTO somua_gene VALUES (1, '示例基因甲'), (2, '示例基因乙')")
        )
        connection.execute(
            text(
                "CREATE TABLE somua_model (id INTEGER PRIMARY KEY, "
                "pet_id INTEGER, name TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO somua_model VALUES "
                "(1, 9001, '部件来源甲'), (2, 9002, '部件来源乙')"
            )
        )
    yield _Publication(engine)
    engine.dispose()


def test_resolver_uses_one_snapshot_and_part_pet_ids(
    detail: SomuaDetail,
    publication: _Publication,
) -> None:
    facts = PublishedSomuaTextResolver(publication).resolve(detail)
    assert publication.calls == 1
    message = format_somua_detail(detail, facts)
    assert "性格：示例性格：性格说明" in message
    assert "魂印：示例魂印：魂印效果" in message
    assert "身体：部件来源甲、表情：部件来源乙" in message
    assert message.count("身体：部件来源甲") == 1
    assert "父系" not in message and "母系" not in message
    assert "Parent" not in message and "Owner" not in message
    assert detail.father.name == "Parent" and detail.mother.name == "Parent"
    assert "1. 示例词条甲：效果甲\n第二行\n2. 示例词条甲" in message
    assert "4. 未识别（编号3999）" in message
    assert "基因：示例基因甲、未识别（编号0）、示例基因乙、示例基因甲" in message
    assert "尾：无" in message
    assert "创建时间：2026-11-22 00:00:00（北京时间）" in message
    assert "上次互动：暂无记录（北京时间）" in message
    assert (
        "[color" not in message and "<sprite" not in message and "<color" not in message
    )
    assert "攻击模式" not in message and "能力参数" not in message


def test_missing_tables_and_columns_preserve_other_facts(
    detail: SomuaDetail,
    publication: _Publication,
) -> None:
    with publication.engine.begin() as connection:
        connection.execute(text("DROP TABLE somua_gene"))
        connection.execute(
            text("ALTER TABLE somua_model RENAME COLUMN pet_id TO obsolete_id")
        )
    facts = PublishedSomuaTextResolver(publication).resolve(detail)
    message = format_somua_detail(detail, facts)
    assert "性格：示例性格" in message
    assert "身体：未识别（编号9001）" in message
    assert "部分中文配置暂不可用：基因、外观部件" in message
    assert f"米米号：{PLAYER}" in message


def test_conflicting_part_names_and_wrong_entry_kind_are_not_guessed(
    detail: SomuaDetail,
    publication: _Publication,
) -> None:
    with publication.engine.begin() as connection:
        connection.execute(text("INSERT INTO somua_model VALUES (3, 9001, '另一名称')"))
        connection.execute(text("UPDATE somua_entry SET type = 1 WHERE id = 2001"))
    message = format_somua_detail(
        detail, PublishedSomuaTextResolver(publication).resolve(detail)
    )
    assert "身体：未识别（编号9001）" in message
    assert "性格：未识别（编号2001）" in message
    assert "表情：部件来源乙" in message


def test_unavailable_publication_and_no_resolver_are_readable(
    detail: SomuaDetail,
) -> None:
    class Missing:
        @contextmanager
        def query(self, operation: DataQuery[Any]) -> Iterator[Any]:
            del operation
            raise DataUnavailableError
            yield  # pragma: no cover

    facts = PublishedSomuaTextResolver(Missing()).resolve(detail)
    message = format_somua_detail(detail, facts)
    assert "未识别（编号2001）" in message
    assert "资料配置" in message
    assert "创建时间：2026-11-22 00:00:00" in message


def test_incomplete_entry_fields_do_not_break_other_details(
    detail: SomuaDetail,
    publication: _Publication,
) -> None:
    with publication.engine.begin() as connection:
        connection.execute(text("UPDATE somua_entry SET type = NULL WHERE id = 2001"))
        connection.execute(text("UPDATE somua_entry SET desc = NULL WHERE id = 3001"))
    message = format_somua_detail(
        detail, PublishedSomuaTextResolver(publication).resolve(detail)
    )
    assert "性格：未识别（编号2001）" in message
    assert "1. 未识别（编号3001）" in message
    assert "魂印：示例魂印" in message


@pytest.mark.parametrize("value", [-1, 10**40])
def test_invalid_times_are_not_guessed(value: int) -> None:
    assert format_somua_time(value) == "时间不可用"


def test_zero_time_and_sanitizing_preserve_visible_text() -> None:
    assert format_somua_time(0) == "暂无记录"
    assert (
        visible_somua_text("[color=#fff]<b>50%</b>[/color]|<sprite name=ATK>文字<3")
        == "50%\n文字<3"
    )


@pytest.mark.asyncio
async def test_live_and_cached_reply_reparse_publication_without_renewal(
    monkeypatch: pytest.MonkeyPatch,
    publication: _Publication,
) -> None:
    resolver = PublishedSomuaTextResolver(publication)
    observations = ObservationCache()
    deps = PlayerShortcutDependencies(
        cast("Any", None), cast("Any", None), 1, 3, 1, observations, TTL, resolver
    )
    game = SimpleNamespace(send_and_wait=AsyncMock(return_value=(None, _wire())))
    first = await fetch_somua_detail_reply(
        deps, game, player_id=PLAYER, sequence=SEQUENCE, anchor_only=False
    )
    assert first.complete and "性格：示例性格" in first.text
    assert first.fetched_at is not None
    stamp = first.fetched_at
    with publication.engine.begin() as connection:
        connection.execute(
            text("UPDATE somua_entry SET name = '新版性格' WHERE id = 2001")
        )
    monkeypatch.setattr(
        clock, "now", lambda: datetime.fromtimestamp(stamp + TTL - 1, timezone.utc)
    )
    cached = cached_detail_reply(
        observations, TTL, PLAYER, SEQUENCE, text_resolver=resolver
    )
    assert cached is not None and "性格：新版性格" in cached.text
    assert cached.fetched_at == stamp
    assert cached.query_work is not None and not cached.query_work.billable_units
    game.send_and_wait.assert_awaited_once_with(45969, PLAYER, SEQUENCE)
    monkeypatch.setattr(
        clock, "now", lambda: datetime.fromtimestamp(stamp + TTL + 1, timezone.utc)
    )
    assert (
        cached_detail_reply(observations, TTL, PLAYER, SEQUENCE, text_resolver=resolver)
        is None
    )


def test_zero_and_unknown_fields_keep_explicit_unknowns(detail: SomuaDetail) -> None:
    snapshot = SomuaTextSnapshot(entries={0: SomuaEntryText("不可信零性格", "", 1)})
    message = format_somua_detail(
        replace(detail, personality=0, attributes=(0,)), snapshot
    )
    assert "性格：未识别（编号0）" in message
    assert "1. 未识别（编号0）" in message
    assert "不可信零性格" not in message


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.asyncio
async def test_public_menu_renders_readable_detail_and_returns_without_queries(
    platform: Platform,
    detail: SomuaDetail,
    publication: _Publication,
) -> None:
    actor = ActorRef(platform, "101")
    conversation = ConversationRef(platform, "group", "456")
    context = MessageInputContext(
        IncomingMessageRef(platform, actor, conversation, "message", "苏摩"),
        mentions_bot=False,
    )
    features = FeatureService(
        {conversation: frozenset({"seer_player"})}, {}, frozenset()
    )
    sessions = PortableQuerySessions()
    resolver = PlayerIdResolver(lambda *_: PLAYER, lambda _: PLAYER)
    deps = PlayerShortcutDependencies(
        cast("Any", None),
        cast("Any", None),
        1,
        3,
        1,
        ObservationCache(),
        TTL,
        PublishedSomuaTextResolver(publication),
    )
    game = SimpleNamespace(send_and_wait=AsyncMock(return_value=(None, _wire())))

    async def query(command: Any, *_args: Any, **_kwargs: Any) -> QueryReply:
        if command.kind == "somua_detail":
            return await fetch_somua_detail_reply(
                deps,
                game,
                player_id=PLAYER,
                sequence=command.somua_sequence,
                anchor_only=False,
            )
        return SomuaOverviewReply(
            text="苏摩积分与排名",
            common_somua=(SomuaCommonSlot(SEQUENCE, detail.parts),),
        )

    operations = build_portable_player_operations(
        cast("PlayerService", SimpleNamespace(shortcut=AsyncMock(side_effect=query))),
        resolver,
        sessions,
        features,
        PlayerDetailExtensionRegistry(),
    )
    assert isinstance(
        await operations["seer.player.default"]("苏摩", context), PortableReply
    )
    selected = await sessions.select("1", context, allow_deferred=True)
    assert isinstance(selected, PortableReply)
    assert "魂印：示例魂印" in str(selected.message)
    assert "身体：部件来源甲" in str(selected.message)
    assert "返回上级" not in str(selected.message)
    assert "父系" not in str(selected.message) and "母系" not in str(selected.message)
    assert isinstance(
        await sessions.select("1", context, allow_deferred=True), PortableReply
    )
    game.send_and_wait.assert_awaited_once_with(45969, PLAYER, SEQUENCE)
    assert await sessions.select("0", context) is not None
    assert await sessions.select("1", context, allow_deferred=True) is None


@pytest.mark.asyncio
async def test_missing_text_does_not_fail_a_successful_game_observation() -> None:
    deps = PlayerShortcutDependencies(cast("Any", None), cast("Any", None), 1, 3, 1)
    game = SimpleNamespace(send_and_wait=AsyncMock(return_value=(None, _wire())))
    reply = await fetch_somua_detail_reply(
        deps,
        game,
        player_id=PLAYER,
        sequence=SEQUENCE,
        anchor_only=False,
    )
    assert reply.complete and reply.query_work is not None
    assert reply.query_work.billable_units
    assert "部分中文配置暂不可用：资料配置" in reply.text
    assert "未识别（编号2001）" in reply.text
