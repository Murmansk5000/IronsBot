from __future__ import annotations

import asyncio
import struct
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.seer import PlayerBindingConfig, RankQueryConfig
from ironsbot.core import time as clock
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.integrations.storage.rank_page_cache import SqliteRankPageCache
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.operations.headless_errors import SocketRecvError
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.observation_cache import ObservationCache
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    PlayerShortcutDependencies,
)
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.rank import RankService
from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.somua_codec import (
    decode_common_slots,
    encode_common_slots,
    parse_somua_detail,
)
from ironsbot.services.seer.somua_detail import (
    cached_detail_reply,
    fetch_somua_detail_reply,
)
from ironsbot.services.seer.somua_models import (
    SomuaCommonSlot,
    SomuaOverviewReply,
    SomuaParts,
    SomuaRankEntry,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.seer.player_service import PlayerService

PLAYER = 700001
SEQUENCE = 111
THIRD = 333
SCORE = 90
DETAIL_BYTES = 341
TTL = 300
PREPARE_COMMAND = 45941
TWO_QUERIES = 2
SCORE_COMMAND = 40002
DETAIL_COMMAND = 45969


def test_detail_and_overview_share_quota_but_not_instance_identity() -> None:
    from ironsbot.core.semantic_requests import SemanticRequestSource
    from ironsbot.services.seer.player_shortcut_contracts import (
        player_shortcut_semantic_request,
    )

    command = PlayerShortcutCommand("somua_detail", PLAYER, somua_sequence=SEQUENCE)
    assert command.quota_action == PlayerShortcutCommand("somua", PLAYER).quota_action
    first = player_shortcut_semantic_request(
        kind="somua_detail",
        player_id=PLAYER,
        sequence=SEQUENCE,
        source=SemanticRequestSource.MENU,
    )
    second = player_shortcut_semantic_request(
        kind="somua_detail",
        player_id=PLAYER,
        sequence=THIRD,
        source=SemanticRequestSource.MENU,
    )
    assert first.target != second.target


def _slots() -> tuple[SomuaCommonSlot, ...]:
    return tuple(
        SomuaCommonSlot(sequence, SomuaParts(*range(9)))
        for sequence in (SEQUENCE, 0, THIRD)
    )


def _wire(
    player: int = PLAYER, sequence: int = SEQUENCE, *, name: bytes = b"Demo"
) -> bytes:
    head = struct.pack(
        "!I32s6I6I3I4I9I",
        sequence,
        name,
        *range(6),
        *range(6),
        *range(3),
        *range(4),
        *range(9),
    )
    parent = struct.pack("!32sI9I16sI", b"Parent", 2, *range(9), b"Owner", 10)
    return head + parent + parent + struct.pack("!IBI", 4, 1, player)


def test_detail_decode_and_cache_payload_are_lossless() -> None:
    raw = _wire()
    assert len(raw) == DETAIL_BYTES
    detail = parse_somua_detail(raw, player_id=PLAYER, sequence=SEQUENCE)
    assert (detail.name, detail.father.name, detail.mother.owner_name) == (
        "Demo",
        "Parent",
        "Owner",
    )
    assert detail.genes == tuple(range(6)) and detail.attributes == tuple(range(4))
    assert decode_common_slots(encode_common_slots(_slots())) == _slots()
    assert decode_common_slots(None) is None
    assert decode_common_slots("[]") is None
    assert decode_common_slots("null") is None
    assert decode_common_slots("invalid") is None


@pytest.mark.parametrize("suffix", [b"x", b"", b"xx"])
def test_detail_identity_and_length_are_strict(suffix: bytes) -> None:
    raw = _wire()
    with pytest.raises(ValueError, match="不一致"):
        parse_somua_detail(raw, player_id=PLAYER + 1, sequence=SEQUENCE)
    with pytest.raises(ValueError, match="不一致"):
        parse_somua_detail(raw, player_id=PLAYER, sequence=THIRD)
    with pytest.raises(ValueError, match="长度"):
        parse_somua_detail(
            raw[:-1] + suffix + b"extra", player_id=PLAYER, sequence=SEQUENCE
        )


def test_rank_cache_preserves_common_slots_across_restart_and_old_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rank.sqlite"
    cache = SqliteRankPageCache(path, enabled=True, ttl_seconds=TTL, allow_stale=False)
    stamp = clock.now().timestamp()
    cache.save(
        key=45965,
        sub_key=1,
        start=0,
        end=0,
        items=[SomuaRankEntry(PLAYER, "Demo", SCORE, _slots())],
        fetched_at=stamp,
    )
    restarted = SqliteRankPageCache(
        path, enabled=True, ttl_seconds=TTL, allow_stale=False
    )
    page = restarted.page(key=45965, sub_key=1, start=0, end=0)
    item = restarted.item(key=45965, sub_key=1, user_id=PLAYER)
    assert page is not None and item is not None
    assert isinstance(page.items[0], SomuaRankEntry)
    assert page.items[0].common_somua == item.common_somua == _slots()
    assert page.fetched_at == item.fetched_at == stamp


def _game() -> tuple[SeerGame, Any]:
    game = SeerGame(
        PLAYER,
        "unused",
        login_server_url="https://invalid.example/",
        operations=HeadlessOperationTracker(),
        spawn=Mock(),
    )
    client = SimpleNamespace(
        send_and_wait=AsyncMock(return_value=(None, b"\0\0\0\0")), is_connected=True
    )
    game._impl = cast("Any", client)
    game._is_logged_in = True
    return game, client


@pytest.mark.asyncio
async def test_read_preparation_once_per_connection_and_not_for_other_queries() -> None:
    game, client = _game()
    await asyncio.gather(
        game.send_and_wait(cast("Any", 45965), 1, 0, 0),
        game.send_and_wait(cast("Any", 45969), PLAYER, SEQUENCE),
    )
    commands = [int(call.args[0]) for call in client.send_and_wait.await_args_list]
    assert commands[0] == PREPARE_COMMAND and commands.count(PREPARE_COMMAND) == 1
    await game.send_and_wait(cast("Any", 40002), PLAYER, 152801)
    assert client.send_and_wait.await_count == len(commands) + 1
    new_client = SimpleNamespace(
        send_and_wait=AsyncMock(return_value=(None, b"\0\0\0\0")), is_connected=True
    )
    game._impl = cast("Any", new_client)
    await game.send_and_wait(cast("Any", 45965), 1, 0, 0)
    assert [int(call.args[0]) for call in new_client.send_and_wait.await_args_list] == [
        45941,
        45965,
    ]


@pytest.mark.asyncio
async def test_failed_preparation_is_not_remembered() -> None:
    game, client = _game()
    client.send_and_wait.side_effect = [
        SocketRecvError(12345),
        (None, b"\0\0\0\0"),
        (None, b"\0\0\0\0"),
    ]
    with pytest.raises(SocketRecvError):
        await game.send_and_wait(cast("Any", 45965), 1, 0, 0)
    assert game._somua_read_client is None
    await game.send_and_wait(cast("Any", 45965), 1, 0, 0)
    assert [int(call.args[0]) for call in client.send_and_wait.await_args_list] == [
        45941,
        45941,
        45965,
    ]


@pytest.mark.asyncio
async def test_reconnect_while_queued_does_not_send_unprepared_request() -> None:
    from ironsbot.services.operations.headless_errors import DisconnectedError

    game, _client = _game()
    await game._prepare_somua_read(None)
    await game._request_gate.acquire()
    task = asyncio.create_task(game.send_and_wait(cast("Any", 45965), 1, 0, 0))
    await asyncio.sleep(0)
    new_client = SimpleNamespace(
        send_and_wait=AsyncMock(return_value=(None, b"\0\0\0\0")), is_connected=True
    )
    game._impl = cast("Any", new_client)
    game._request_gate.release()
    with pytest.raises(DisconnectedError, match="排队期间"):
        await task
    new_client.send_and_wait.assert_not_awaited()
    await game.send_and_wait(cast("Any", 45965), 1, 0, 0)
    assert [int(call.args[0]) for call in new_client.send_and_wait.await_args_list] == [
        45941,
        45965,
    ]


@pytest.mark.asyncio
async def test_detail_observation_cache_does_not_extend_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = ObservationCache()
    deps = PlayerShortcutDependencies(
        cast("Any", None), cast("Any", None), 1, 3, 1, observations, TTL
    )
    game = SimpleNamespace(send_and_wait=AsyncMock(return_value=(None, _wire())))
    first = await fetch_somua_detail_reply(
        deps, game, player_id=PLAYER, sequence=SEQUENCE, anchor_only=False
    )
    cached = await fetch_somua_detail_reply(
        deps, game, player_id=PLAYER, sequence=SEQUENCE, anchor_only=False
    )
    game.send_and_wait.assert_awaited_once_with(45969, PLAYER, SEQUENCE)
    assert first.fetched_at == cached.fetched_at and cached.query_work is not None
    assert not cached.query_work.billable_units
    assert first.fetched_at is not None
    stamp = first.fetched_at
    monkeypatch.setattr(
        clock, "now", lambda: datetime.fromtimestamp(stamp + TTL + 1, timezone.utc)
    )
    assert cached_detail_reply(observations, TTL, PLAYER, SEQUENCE) is None
    denied = await fetch_somua_detail_reply(
        deps, game, player_id=PLAYER, sequence=SEQUENCE, anchor_only=True
    )
    assert not denied.complete
    game.send_and_wait.assert_awaited_once()


def _context(
    platform: Platform,
    text: str = "苏摩",
    *,
    kind: Literal["group", "private"] = "group",
) -> MessageInputContext:
    actor = ActorRef(platform, "101")
    conv = ConversationRef(platform, kind, actor.id if kind == "private" else "456")
    return MessageInputContext(
        IncomingMessageRef(platform, actor, conv, "event", text), mentions_bot=False
    )


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("in_profile", [False, True])
@pytest.mark.parametrize("picture_available", [False, True])
@pytest.mark.parametrize("conversation_kind", ["group", "private"])
@pytest.mark.parametrize("all_slots", [False, True])
@pytest.mark.asyncio
async def test_public_shortcut_common_menu_detail_and_return_are_lazy(
    platform: Platform,
    *,
    in_profile: bool,
    picture_available: bool,
    conversation_kind: Literal["group", "private"],
    all_slots: bool,
) -> None:
    context = _context(platform, kind=conversation_kind)
    features = FeatureService(
        {context.message.conversation: frozenset({"seer_player"})},
        {context.message.actor: frozenset({"seer_player"})},
        frozenset(),
    )
    sessions = PortableQuerySessions()
    resolver = PlayerIdResolver(lambda *_: PLAYER, lambda _: PLAYER)
    common_slots = _slots()
    if all_slots:
        common_slots = (
            common_slots[0],
            replace(common_slots[0], sequence=SEQUENCE + 1),
            common_slots[2],
        )
    overview = SomuaOverviewReply(
        text="积分：90\n全服排名：第1名",
        common_somua=common_slots,
        fetched_at=clock.now().timestamp(),
    )

    async def query(command: Any, *_args: Any, **_kwargs: Any) -> QueryReply:
        return (
            QueryReply(
                text=f"苏摩详情 {command.somua_sequence}",
                image=b"synthetic PNG" if picture_available else None,
                image_error="图片不可用" if not picture_available else "",
                complete=picture_available,
            )
            if command.kind == "somua_detail"
            else overview
        )

    service = SimpleNamespace(shortcut=AsyncMock(side_effect=query))
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        resolver,
        sessions,
        features,
        PlayerDetailExtensionRegistry(),
    )
    if in_profile:

        async def select_profile(_value: str, selected: MessageInputContext):
            reply = await operations["seer.player.default"]("苏摩", selected)
            assert isinstance(reply, PortableReply)
            return reply

        sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=("somua",),
                select=select_profile,
                keep_open=True,
                prompt=OutboundMessage.from_text("米米号详情\n1. 苏摩\n0. 【退出】"),
            ),
        )
        reply = await sessions.select("1", context, allow_deferred=True)
    else:
        reply = await operations["seer.player.default"]("苏摩", context)
    assert isinstance(reply, PortableReply)
    assert "常用苏摩1" in str(reply.message) and "常用苏摩3" in str(reply.message)
    assert ("常用苏摩2" in str(reply.message)) is all_slots
    assert service.shortcut.await_count == 1
    detail = await sessions.select("3", context, allow_deferred=True)
    assert isinstance(detail, PortableReply) and f"苏摩详情 {THIRD}" in str(
        detail.message
    )
    assert "返回上级" not in str(detail.message)
    assert "0. 【退出】" not in str(detail.message)
    assert isinstance(detail.message, OutboundMessage)
    assert [
        part.content
        for part in detail.message.parts
        if isinstance(part, BinaryImagePart)
    ] == ([b"synthetic PNG"] if picture_available else [])
    if not picture_available:
        assert "图片不可用" in str(detail.message)
    assert detail.message.request_succeeded is picture_available
    if platform is Platform.QQ_OFFICIAL:
        from ironsbot.integrations.qq_official.message_rendering import (
            QQOfficialImagePayload,
            render_qq_official_outbound_message,
        )

        payloads = render_qq_official_outbound_message(detail.message)
        assert (
            any(isinstance(item, QQOfficialImagePayload) for item in payloads)
            is picture_available
        )
    for index, slot in enumerate(common_slots, 1):
        if not slot.sequence:
            continue
        repeated = await sessions.select(str(index), context, allow_deferred=True)
        assert isinstance(repeated, PortableReply)
        assert f"苏摩详情 {slot.sequence}" in str(repeated.message)
        assert "返回上级" not in str(repeated.message)
    assert service.shortcut.await_count == TWO_QUERIES + sum(
        bool(slot.sequence) for slot in common_slots
    )
    exited = await sessions.select("0", context)
    assert exited is not None
    if in_profile:
        assert "米米号详情" in str(exited)
        assert await sessions.select("0", context) is not None
    else:
        assert "退出" in str(exited)


@pytest.mark.parametrize("platform", list(Platform))
def test_common_menu_uses_names_without_instance_numbers(platform: Platform) -> None:
    from ironsbot.services.portable_somua_commands import present_somua_overview

    context = _context(platform)
    features = FeatureService(
        {context.message.conversation: frozenset({"seer_player"})}, {}, frozenset()
    )
    message = present_somua_overview(
        SomuaOverviewReply(
            text="overview",
            common_somua=_slots(),
            common_names=((SEQUENCE, "示例苏摩"),),
        ),
        PLAYER,
        context,
        sessions=PortableQuerySessions(),
        features=features,
        resolver=PlayerIdResolver(lambda *_: PLAYER, lambda _: PLAYER),
        source="numeric",
        query=AsyncMock(),
    )
    text = str(message)
    assert "1. 示例苏摩" in text
    assert f"实例 {SEQUENCE}" not in text
    assert f"常用苏摩3（实例 {THIRD}）" in text


@pytest.mark.parametrize("cached_overview", [False, True])
@pytest.mark.asyncio
async def test_overview_fetches_names_without_images_then_reuses_detail(
    *, cached_overview: bool
) -> None:
    from ironsbot.services.seer.player_shortcut_queries import (
        fetch_player_shortcut_reply,
    )

    slots = tuple(SomuaCommonSlot(n, SomuaParts(*range(9))) for n in (111, 222, 333))
    rank = SimpleNamespace(
        fetch_somua_summary=AsyncMock(
            return_value=RankLookupResult(
                title="苏摩全服榜",
                score_name="分",
                score=SCORE,
                rank=1,
                queried=True,
                common_somua=slots,
                fetched_at=clock.now().timestamp(),
            )
        )
    )
    avatar = SimpleNamespace(
        attach=AsyncMock(side_effect=lambda _parts, reply: replace(reply, image=b"PNG"))
    )
    deps = PlayerShortcutDependencies(
        cast("Any", rank),
        cast("Any", None),
        1,
        5,
        1,
        ObservationCache(),
        TTL,
        somua_avatar=cast("Any", avatar),
    )

    async def send(command: int, *args: int):
        if command == SCORE_COMMAND:
            return None, SimpleNamespace(value=SCORE)
        assert command == DETAIL_COMMAND
        return None, _wire(args[0], args[1], name=f"Name{args[1]}".encode())

    game = SimpleNamespace(
        send_and_wait=AsyncMock(side_effect=send),
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="Demo")),
    )
    if cached_overview:
        assert deps.observations is not None
        stamp = clock.now().timestamp()
        deps.observations.save((PLAYER, "somua_score"), SCORE, stamp)
        deps.observations.save(
            (PLAYER, "user_info"), SimpleNamespace(nick="Demo"), stamp
        )
    overview = await fetch_player_shortcut_reply(
        deps,
        game,
        command=PlayerShortcutCommand("somua", PLAYER),
        player_id=PLAYER,
    )
    assert isinstance(overview, SomuaOverviewReply)
    assert dict(overview.common_names) == {n: f"Name{n}" for n in (111, 222, 333)}
    assert overview.rank_lookup_should_charge_quota
    avatar.attach.assert_not_awaited()
    count = game.send_and_wait.await_count
    detail = await fetch_somua_detail_reply(
        deps, game, player_id=PLAYER, sequence=333, anchor_only=False
    )
    assert detail.image == b"PNG"
    assert game.send_and_wait.await_count == count
    assert detail.query_work is not None and not detail.query_work.billable_units
    avatar.attach.assert_awaited_once()
    repeated = await fetch_player_shortcut_reply(
        deps,
        game,
        command=PlayerShortcutCommand("somua", PLAYER),
        player_id=PLAYER,
    )
    assert isinstance(repeated, SomuaOverviewReply)
    assert repeated.common_names == overview.common_names
    assert not repeated.rank_lookup_should_charge_quota
    assert game.send_and_wait.await_count == count


@pytest.mark.parametrize(
    "case", ["anchor", "deadline", "partial", "duplicate", "empty", "cancel"]
)
@pytest.mark.asyncio
async def test_name_completion_preserves_budget_and_partial_choices(case: str) -> None:
    from ironsbot.core.tasks import OperationDeadline
    from ironsbot.core.time import ObservationTime
    from ironsbot.services.seer.somua_query import _fetch_common_names

    deps = PlayerShortcutDependencies(
        cast("Any", None), cast("Any", None), 1, 3, 1, ObservationCache(), TTL
    )
    sequences = (
        (SEQUENCE, SEQUENCE, THIRD) if case == "duplicate" else (SEQUENCE, THIRD)
    )
    rank = RankLookupResult(
        title="苏摩全服榜",
        score_name="分",
        common_somua=tuple(
            SomuaCommonSlot(n, SomuaParts(*range(9))) for n in sequences
        ),
    )

    async def send(_command: int, player: int, sequence: int):
        if case == "cancel":
            raise asyncio.CancelledError
        if case == "partial" and sequence == SEQUENCE:
            raise TimeoutError
        name = b"" if case == "empty" else f"Name{sequence}".encode()
        return None, _wire(player, sequence, name=name)

    game = SimpleNamespace(send_and_wait=AsyncMock(side_effect=send))
    task = _fetch_common_names(
        deps,
        game,
        player_id=PLAYER,
        result=rank,
        deadline=OperationDeadline.after(0 if case == "deadline" else 3),
        anchor_only=case == "anchor",
        observation=ObservationTime(),
    )
    if case == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await task
        return
    names = await task
    if case in {"anchor", "deadline"}:
        game.send_and_wait.assert_not_awaited()
        assert not names.names and names.errors
    else:
        assert game.send_and_wait.await_count == TWO_QUERIES
        if case == "partial":
            assert names.names == ((THIRD, f"Name{THIRD}"),) and names.errors
        elif case == "empty":
            assert not names.names and names.errors
        else:
            assert names.names == (
                (SEQUENCE, f"Name{SEQUENCE}"),
                (THIRD, f"Name{THIRD}"),
            )
            assert not names.errors


@pytest.mark.asyncio
async def test_cached_names_remain_available_without_online_budget() -> None:
    from ironsbot.core.tasks import OperationDeadline
    from ironsbot.core.time import ObservationTime
    from ironsbot.services.seer.somua_query import _fetch_common_names

    cache = ObservationCache()
    stamp = clock.now().timestamp() - 10
    cache.save(
        (PLAYER, f"somua_detail:{SEQUENCE}"),
        parse_somua_detail(_wire(), player_id=PLAYER, sequence=SEQUENCE),
        stamp,
    )
    deps = PlayerShortcutDependencies(
        cast("Any", None), cast("Any", None), 1, 3, 1, cache, TTL
    )
    game = SimpleNamespace(send_and_wait=AsyncMock())
    observation = ObservationTime()
    names = await _fetch_common_names(
        deps,
        game,
        player_id=PLAYER,
        result=RankLookupResult(
            title="苏摩全服榜", score_name="分", common_somua=(_slots()[0],)
        ),
        deadline=OperationDeadline.after(0),
        anchor_only=True,
        observation=observation,
    )
    assert names.names == ((SEQUENCE, "Demo"),) and not names.errors
    assert observation.fetched_at == stamp
    assert not names.work.billable_units
    game.send_and_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_preparation_cancellation_does_not_mark_connection_ready() -> None:
    game, client = _game()
    entered = asyncio.Event()

    async def blocked(*_args: Any, **_kwargs: Any):
        entered.set()
        await asyncio.Event().wait()

    client.send_and_wait.side_effect = blocked
    task = asyncio.create_task(game.send_and_wait(cast("Any", 45965), 1, 0, 0))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert game._somua_read_client is None
    client.send_and_wait.side_effect = None
    await game.send_and_wait(cast("Any", 45965), 1, 0, 0)
    assert game._somua_read_client is game.client


@pytest.mark.parametrize("anchor_only", [False, True])
@pytest.mark.asyncio
async def test_old_cache_metadata_refresh_is_one_position_and_budgeted(
    tmp_path: Path, *, anchor_only: bool
) -> None:
    import sqlite3

    from ironsbot.services.seer.rank_models import RankEntry

    path = tmp_path / "old-cache.sqlite"
    cache = SqliteRankPageCache(path, enabled=True, ttl_seconds=TTL, allow_stale=False)
    cache.save(
        key=45965, sub_key=1, start=0, end=0, items=[RankEntry(PLAYER, "Demo", SCORE)]
    )
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE player_rank_facts SET somua_payload = NULL")
    online = AsyncMock(return_value=[SomuaRankEntry(PLAYER, "Demo", SCORE, _slots())])
    service = RankService(RankQueryConfig(), cache, lambda: None, online)
    stamp = clock.now().timestamp()
    result = RankLookupResult(
        title="苏摩全服榜",
        score_name="分",
        rank=1,
        score=SCORE,
        queried=True,
        fetched_at=stamp,
    )
    service._confirmed.save((PLAYER, 45965, 1), result, stamp)
    selected = await service.fetch_somua_summary(
        cast("Any", object()), PLAYER, score=SCORE, anchor_only=anchor_only
    )
    assert selected.rank == 1
    if anchor_only:
        assert selected.common_somua is None and selected.common_failure
        online.assert_not_awaited()
    else:
        assert selected.common_somua == _slots()
        assert online.await_count == 1
        assert online.await_args is not None
        assert online.await_args.kwargs["start"] == online.await_args.kwargs["end"] == 0
        await service.fetch_somua_summary(cast("Any", object()), PLAYER, score=SCORE)
        assert online.await_count == 1


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.asyncio
async def test_shared_menu_rechecks_actual_actor_and_changed_permissions(
    platform: Platform,
) -> None:
    from ironsbot.services.portable_somua_commands import present_somua_overview

    context = _context(platform)
    policies = {context.message.conversation: frozenset({"seer_player"})}
    features = FeatureService(policies, {}, frozenset())
    resolver = PlayerIdResolver(
        lambda *_: PLAYER,
        lambda actor: PLAYER if actor == context.message.actor else None,
        binding_config=PlayerBindingConfig(allow_unbound_alias_queries=False),
    )
    sessions = PortableQuerySessions()
    query = AsyncMock(return_value=PortableReply(OutboundMessage.from_text("detail")))
    present_somua_overview(
        SomuaOverviewReply(text="overview", common_somua=_slots()),
        PLAYER,
        context,
        sessions=sessions,
        features=features,
        resolver=resolver,
        source="default",
        query=query,
    )
    other = replace(
        context, message=replace(context.message, actor=ActorRef(platform, "202"))
    )
    await sessions.select_shared("1", context, other, allow_deferred=True)
    query.assert_not_awaited()
    policies[context.message.conversation] = frozenset()
    await sessions.select("1", context, allow_deferred=True)
    query.assert_not_awaited()
