from __future__ import annotations

import asyncio
import os
from base64 import b64decode
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from functools import partial
from io import BytesIO
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core.outbound import ReplyContext, TextPart
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.seer_data.type_matchup_repository import (
    PublishedTypeMatchupRepository,
)
from ironsbot.integrations.storage.render_cache import FileRenderCache
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.render_cache import RenderCacheEntry
from ironsbot.services.seer.type_calc import (
    ElementTypeSnapshot,
    TypeCombinationSnapshot,
    TypeMatchup,
    TypeMatchupDataset,
)
from ironsbot.services.seer.type_query import (
    INCOMPLETE_TYPE_DATA_MESSAGE,
    NORMAL_TYPE_MESSAGE,
    TypeQueryService,
    TypeRenderSession,
)
from tests.helpers.fake_official_platform import (
    RESTRICTED_CAPABILITIES,
    FakeOfficialPlatform,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.type_query import (
        TypeMatchupRenderer,
        TypeRenderSessionFactory,
    )


class FakeData:
    def __init__(self) -> None:
        self.combinations: tuple[Any, ...] = ()
        self.dataset = TypeMatchupDataset((), (), ())
        self.query_open = False
        self.queries = 0

    @contextmanager
    def query(self, _operation: object) -> Iterator[Any]:
        self.queries += 1
        self.query_open = True
        try:
            yield self.combinations if isinstance(_operation, partial) else self.dataset
        finally:
            self.query_open = False


def _type(type_id: int, name: str, *, primary_id: int | None = None) -> Any:
    return SimpleNamespace(
        id=type_id,
        name=name,
        primary_id=type_id if primary_id is None else primary_id,
        secondary_id=None,
    )


def _dataset(target: Any) -> TypeMatchupDataset:
    snapshot = TypeCombinationSnapshot(
        id=int(target.id),
        name=str(target.name),
        primary_id=int(target.primary_id),
        secondary_id=target.secondary_id,
    )
    return TypeMatchupDataset(
        combinations=(snapshot,),
        elements=(ElementTypeSnapshot(snapshot.primary_id, snapshot.name),),
        relations=((snapshot.primary_id, snapshot.primary_id, 1.0),),
    )


def _neutral_relations(*type_ids: int) -> tuple[tuple[int, int, float], ...]:
    return tuple((source, target, 1.0) for source in type_ids for target in type_ids)


def _service(
    data: FakeData,
    rendered: list[TypeMatchup] | None = None,
) -> TypeQueryService:
    rendered = [] if rendered is None else rendered

    async def render(matchup: TypeMatchup) -> bytes:
        rendered.append(matchup)
        return b"rendered"

    return TypeQueryService(_render_session(data, render))


def _render_session(
    data: FakeData, render: TypeMatchupRenderer
) -> TypeRenderSessionFactory:
    @contextmanager
    def session() -> Iterator[TypeRenderSession]:
        yield TypeRenderSession(_repository(data), render, NoCache())

    return session


def _repository(data: object) -> PublishedTypeMatchupRepository:
    return PublishedTypeMatchupRepository(cast("SeerDataReader", data))


class NoCache:
    def entry(self, category: str, content_key: str) -> RenderCacheEntry:  # noqa: ARG002
        return RenderCacheEntry(lambda: None, lambda _data: None)


@pytest.mark.asyncio
async def test_single_type_query_renders_matchup() -> None:
    data = FakeData()
    target = _type(1, "草")
    data.combinations = (target,)
    data.dataset = _dataset(target)
    rendered: list[TypeMatchup] = []
    render_session_states: list[bool] = []

    async def render(matchup: TypeMatchup) -> bytes:
        render_session_states.append(data.query_open)
        rendered.append(matchup)
        return b"rendered"

    result = await TypeQueryService(_render_session(data, render)).search("草")

    assert result.reply is not None
    assert result.reply.image == b"rendered"
    assert [item.target for item in rendered] == [
        TypeCombinationSnapshot(1, "草", 1, None)
    ]
    assert render_session_states == [False]


@pytest.mark.asyncio
async def test_normal_type_query_returns_message_without_rendering() -> None:
    data = FakeData()
    data.combinations = (_type(8, "普通"),)

    result = await _service(data).search("普通")

    assert result.message == NORMAL_TYPE_MESSAGE


@pytest.mark.asyncio
async def test_multiple_type_query_returns_choices() -> None:
    data = FakeData()
    data.combinations = (_type(1, "草"), _type(2, "水"))

    result = await _service(data).search("属性")

    assert [(choice.name, choice.value) for choice in result.choices] == [
        ("草", 1),
        ("水", 2),
    ]


@pytest.mark.asyncio
async def test_type_selection_reports_missing_matchup() -> None:
    result = await _service(FakeData()).select(99)

    assert result.message == ("❌未找到属性 99（这是一个bug，请反馈给开发者）")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["search", "select", "custom"])
@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
async def test_matchup_preparation_and_render_share_one_session(
    mode: str, failure: type[BaseException] | None
) -> None:
    global_data = FakeData()
    target = _type(1, "草")
    global_data.combinations = () if mode == "custom" else (target,)
    bound = FakeData()
    bound.combinations = global_data.combinations
    bound.dataset = TypeMatchupDataset(
        combinations=(TypeCombinationSnapshot(1, "草", 1, None),),
        elements=(ElementTypeSnapshot(1, "草"), ElementTypeSnapshot(2, "水")),
        relations=_neutral_relations(1, 2),
    )
    active = False
    rendered: list[TypeMatchup] = []

    async def render(matchup: TypeMatchup) -> bytes:
        await asyncio.sleep(0)
        assert active
        assert not bound.query_open
        rendered.append(matchup)
        if failure is not None:
            raise failure
        return b"bound"

    @contextmanager
    def session() -> Iterator[TypeRenderSession]:
        nonlocal active
        active = True
        try:
            yield TypeRenderSession(_repository(bound), render, NoCache())
        finally:
            active = False

    service = TypeQueryService(session)
    request = (
        service.select(1)
        if mode == "select"
        else service.search("草+水" if mode == "custom" else "草")
    )
    if failure is None:
        result = await request
        assert result.reply is not None
        assert result.reply.image == b"bound"
    else:
        with pytest.raises(failure):
            await request
    assert not active
    assert not bound.query_open
    assert len(rendered) == 1
    assert rendered[0].target.primary_id == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["search", "select", "custom"])
@pytest.mark.parametrize("allowed", [False, True])
async def test_query_cache_skips_all_reads_and_is_publication_bound(
    tmp_path: Path, mode: str, *, allowed: bool
) -> None:
    data = FakeData()
    data.combinations = () if mode == "custom" else (_type(1, "草"),)
    data.dataset = TypeMatchupDataset(
        combinations=(TypeCombinationSnapshot(1, "草", 1, None),),
        elements=(ElementTypeSnapshot(1, "草"), ElementTypeSnapshot(2, "水")),
        relations=_neutral_relations(1, 2),
    )
    cache = FileRenderCache(tmp_path, 1024 * 1024, version_getter=lambda: "unused")
    version = "first"
    calls: list[str] = []

    @contextmanager
    def session() -> Iterator[TypeRenderSession]:
        captured = version

        async def render(matchup: TypeMatchup) -> bytes:
            assert not data.query_open
            calls.append(captured)
            return (captured + matchup.target.name).encode()

        yield TypeRenderSession(
            _repository(data),
            render,
            cache.bind(captured, lambda _category: allowed),
        )

    service = TypeQueryService(session)

    async def request() -> Any:
        return (
            await service.select(1)
            if mode == "select"
            else await service.search("草+水" if mode == "custom" else "草")
        )

    first = await request()
    queries = data.queries
    second = await request()
    assert second == first
    assert data.queries == queries * (1 if allowed else 2)
    assert calls == ["first"] * (1 if allowed else 2)
    version = "second"
    third = await request()
    assert third != first
    assert calls[-1] == "second"
    queries = data.queries
    version = "first"
    assert await request() == first
    assert data.queries == queries + (0 if allowed else (1 if mode == "select" else 2))


@pytest.mark.asyncio
async def test_custom_query_order_and_failed_render_do_not_poison_cache(
    tmp_path: Path,
) -> None:
    data = FakeData()
    data.dataset = TypeMatchupDataset(
        (), (ElementTypeSnapshot(1, "草"), ElementTypeSnapshot(2, "水")), ()
    )
    cache = FileRenderCache(tmp_path, 1024 * 1024, version_getter=lambda: "release")
    failed = True
    calls: list[str] = []

    async def render(matchup: TypeMatchup) -> bytes:
        calls.append(matchup.target.name)
        if failed:
            raise RuntimeError("render failed")  # noqa: TRY003
        return matchup.target.name.encode()

    @contextmanager
    def session() -> Iterator[TypeRenderSession]:
        yield TypeRenderSession(_repository(data), render, cache)

    service = TypeQueryService(session)
    with pytest.raises(RuntimeError, match="render failed"):
        await service.search("草+水")
    failed = False
    for arg, title in (("草+水", "草水（DIY 属性）"), ("水+草", "水草（DIY 属性）")):
        result = await service.search(arg)
        assert result.reply is not None and result.reply.image == title.encode()
        queries = data.queries
        assert await service.search(arg) == result
        assert data.queries == queries
    assert calls == ["草水（DIY 属性）", "草水（DIY 属性）", "水草（DIY 属性）"]


@pytest.mark.asyncio
async def test_incomplete_type_relations_fail_without_render_or_cache(
    tmp_path: Path,
) -> None:
    data = FakeData()
    target = _type(1, "草")
    data.combinations = (target,)
    data.dataset = TypeMatchupDataset(
        combinations=(TypeCombinationSnapshot(1, "草", 1, None),),
        elements=(ElementTypeSnapshot(1, "草"),),
        relations=(),
    )
    cache = FileRenderCache(tmp_path, 1024 * 1024, version_getter=lambda: "release")
    render_calls = 0

    async def render(_matchup: TypeMatchup) -> bytes:
        nonlocal render_calls
        render_calls += 1
        return b"must not render"

    @contextmanager
    def session() -> Iterator[TypeRenderSession]:
        yield TypeRenderSession(_repository(data), render, cache)

    service = TypeQueryService(session)
    result = await service.search("草")

    assert result.message == INCOMPLETE_TYPE_DATA_MESSAGE
    assert result.reply is None
    assert render_calls == 0
    first_query_count = data.queries
    assert (await service.search("草")).message == INCOMPLETE_TYPE_DATA_MESSAGE
    assert data.queries > first_query_count
    assert render_calls == 0


def test_type_query_and_calculator_are_render_fingerprint_inputs() -> None:
    from ironsbot.app.rendering_composition import FINAL_RENDER_CACHE_INPUTS

    paths = {path.name for path in FINAL_RENDER_CACHE_INPUTS}
    assert {"type_query.py", "type_calc.py"} <= paths
    assert all(path.exists() for path in FINAL_RENDER_CACHE_INPUTS)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["image", "text", "denied", "expired"])
async def test_type_query_result_crosses_restricted_platform_boundary(
    mode: str,
) -> None:
    data = FakeData()
    target = _type(8, "普通") if mode == "text" else _type(1, "草")
    data.combinations = (target,)
    data.dataset = _dataset(target)
    rendered: list[TypeMatchup] = []
    result = await _service(data, rendered).search(target.name)
    message = (
        result.reply.to_outbound()
        if result.reply is not None
        else QueryReply(text=result.message).to_outbound()
    )
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    context = ReplyContext(
        ConversationRef(Platform.QQ_OFFICIAL, "group", "opaque:group"),
        "opaque:event",
        sequence="opaque:sequence",
        reply_deadline=now + timedelta(seconds=5),
    )
    transport = FakeOfficialPlatform(
        now + timedelta(seconds=5) if mode == "expired" else now,
        capabilities=replace(RESTRICTED_CAPABILITIES, supports_images=mode != "denied"),
    )
    delivered = await transport.reply(context, message)
    assert not data.query_open
    assert bool(rendered) == (mode != "text")
    if mode in {"denied", "expired"}:
        assert delivered.error_code == (
            "fake_images_denied" if mode == "denied" else "fake_reply_expired"
        )
        assert transport.uploads == []
    else:
        assert delivered.delivered
        if mode == "text":
            assert message.parts == (TextPart(NORMAL_TYPE_MESSAGE),)
            assert transport.uploads == []
        else:
            assert len(transport.uploads) == 1
            assert result.reply is not None
            assert transport.uploads[0].content == result.reply.image


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "type_matchup",
        "peak_pool",
        "expert_pool",
        "pet_info",
        "peak_pool_vote",
        "peak_pet_rank",
        "player_lineup",
    ],
)
@pytest.mark.skipif(
    not os.environ.get("IRONSBOT_RENDER_RELEASE"),
    reason="native release smoke requires IRONSBOT_RENDER_RELEASE and official assets",
)
async def test_native_published_queries_cache_and_delivery(  # noqa: C901, PLR0915 - shared release acceptance
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    import nonebot
    from httpx import AsyncClient
    from PIL import Image
    from sqlalchemy import event

    from ironsbot.app.lifecycle import TaskOwner
    from ironsbot.app.rendering_composition import build_seer_rendering_components
    from ironsbot.config.models.seer import RenderConfig
    from ironsbot.core import time
    from ironsbot.integrations.db_registry import DatabaseManager
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.onebot.message_rendering import (
        render_onebot_outbound_message,
    )
    from ironsbot.integrations.seer_data.database import SeerDatabase
    from ironsbot.integrations.seer_data.peak_pet_rank_renderer import (
        render_peak_pet_rank,
    )
    from ironsbot.integrations.seer_data.peak_pool_renderer import render_peak_pool
    from ironsbot.integrations.seer_data.peak_pool_vote_renderer import (
        render_peak_pool_vote,
    )
    from ironsbot.integrations.seer_data.peak_repository import load_peak_vote_snapshots
    from ironsbot.integrations.seer_data.pet_info_renderer import (
        render_published_pet_info,
    )
    from ironsbot.integrations.seer_data.type_matchup_renderer import (
        render_type_matchup,
    )
    from ironsbot.runtime.cache_paths import CachePaths
    from ironsbot.services.seer.peak import (
        LIMIT_POOL_VOTE_COUNT,
        PeakItemData,
        PeakQueryService,
        PeakRenderSession,
        normalize_peak_vote_time,
    )
    from ironsbot.services.seer.rank_models import RankEntry

    if kind == "player_lineup":
        if not (private_root := os.environ.get("IRONSBOT_PRIVATE_ROOT")):
            pytest.skip("lineup release acceptance requires IRONSBOT_PRIVATE_ROOT")
        monkeypatch.syspath_prepend(private_root)

    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init()
        driver = nonebot.get_driver()
    if fontconfig := os.environ.get("IRONSBOT_RENDER_FONTCONFIG"):
        monkeypatch.setattr(driver.config, "fontconfig_file", fontconfig, raising=False)
    from nonebot_plugin_htmlkit import init_fontconfig

    init_fontconfig()
    databases = DatabaseManager()
    database = SeerDatabase(databases, merge_connected_mintmarks=True)
    owner = TaskOwner()
    queries: list[str] = []
    requests: list[str] = []
    native_calls = 0

    def track_sql(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        queries.append(statement)

    async def track_http(request: Any) -> None:
        requests.append(str(request.url))

    try:
        databases.load_from_file("seerapi", os.environ["IRONSBOT_RENDER_RELEASE"])
        category = "peak_pool" if kind == "expert_pool" else kind
        cache_allowed = database.render_category_available(category)
        vote_ids: dict[int, tuple[int, ...]] = {}
        if kind == "peak_pool_vote":
            with database.query(load_peak_vote_snapshots) as votes:
                active_vote = next(
                    vote
                    for vote in votes
                    if vote.count == LIMIT_POOL_VOTE_COUNT and vote.pets
                )
                fixture_time = normalize_peak_vote_time(
                    active_vote.start_time
                ) + timedelta(minutes=1)
                vote_ids = {
                    vote.count: tuple(pet.id for pet in vote.pets[:3]) for vote in votes
                }
            monkeypatch.setattr(time, "now", lambda *, tz: fixture_time.astimezone(tz))
        elif kind == "peak_pet_rank":
            fixture_time = datetime(2026, 9, 12, 14, 0, tzinfo=time.TZ_CN)
            monkeypatch.setattr(time, "now", lambda *, tz: fixture_time.astimezone(tz))
        engine = databases.get_engine("seerapi")
        assert engine is not None
        event.listen(engine, "before_cursor_execute", track_sql)
        async with AsyncClient(
            timeout=30, follow_redirects=True, event_hooks={"request": [track_http]}
        ) as client:
            _, coordinator, sessions = build_seer_rendering_components(
                HttpClients(cache=client, origin=client),
                CachePaths(tmp_path / "cache"),
                RenderConfig(),
                database,
                spawn=owner.create,
            )
            native_renderer = coordinator.renderer

            async def count_render(*args: Any, **kwargs: Any) -> bytes:
                nonlocal native_calls
                native_calls += 1
                return await native_renderer(*args, **kwargs)

            coordinator.renderer = count_render

            @contextmanager
            def session() -> Iterator[TypeRenderSession]:
                with sessions.open() as inputs:
                    yield TypeRenderSession(
                        PublishedTypeMatchupRepository(inputs.data),
                        partial(render_type_matchup, inputs.images, coordinator.render),
                        inputs.cache,
                    )

            @contextmanager
            def peak_session() -> Iterator[PeakRenderSession]:
                with sessions.open() as inputs:
                    yield PeakRenderSession(
                        inputs.data,
                        partial(
                            render_peak_pool,
                            inputs.cache,
                            inputs.images,
                            coordinator.render,
                        ),
                        partial(
                            render_peak_pool_vote,
                            inputs.cache,
                            inputs.images,
                            coordinator.render,
                        ),
                        partial(
                            render_peak_pet_rank,
                            inputs.cache,
                            inputs.images,
                            coordinator.render,
                        ),
                    )

            class FixtureGame:
                async def get_limit_pool_vote(self, _key: int) -> list[RankEntry]:
                    return [RankEntry(id_, "fixture", 100) for id_ in vote_ids[2]]

                async def get_semi_limit_pool_vote(self, _key: int) -> list[RankEntry]:
                    return [RankEntry(id_, "fixture", 50) for id_ in vote_ids[3]]

                async def get_peak_pet_rank(self, *_args: Any) -> Any:
                    return [PeakItemData(3549, 10, 6)], [RankEntry(3407, "fixture", 4)]

            async def progress(_message: str) -> None:
                return None

            async def request_reply() -> QueryReply:
                if kind == "type_matchup":
                    result = await TypeQueryService(session).select(1)
                    assert result.reply is not None
                    return result.reply
                if kind == "pet_info":
                    with sessions.open() as inputs:
                        image = await render_published_pet_info(
                            inputs.cache,
                            inputs.data,
                            inputs.images,
                            coordinator.render,
                            3549,
                        )
                    return QueryReply(image=image)
                if kind == "player_lineup":
                    from importlib import import_module

                    from ironsbot.extensions.contracts import PlayerLineupSlot
                    from ironsbot.extensions.player_lineup import (
                        PlayerLineupRenderServices,
                    )
                    from ironsbot.integrations.seer_data.player_lineup_entries import (
                        PublishedPlayerLineupEntryResolver,
                    )

                    models = import_module("ironsbot_private_lineup.models")
                    adapter = import_module("ironsbot_private_lineup.renderer_adapter")
                    with sessions.open() as inputs:
                        slots = tuple(
                            PlayerLineupSlot(id_, 100, 1)
                            for id_ in (3549, 3407, 70, 4554, 5000, 4903)
                        )
                        entries = tuple(
                            models.PlayerLineupEntry(**asdict(entry))
                            for entry in PublishedPlayerLineupEntryResolver(
                                inputs.data
                            ).resolve(slots)
                        )
                        result = await adapter.render_player_lineup(
                            PlayerLineupRenderServices(
                                inputs.images, inputs.cache, coordinator.render
                            ),
                            entries,
                        )
                        assert result.complete
                    return QueryReply(image=result.image)
                if kind in {"peak_pool_vote", "peak_pet_rank"}:
                    service = PeakQueryService(
                        database,
                        cast("Any", SimpleNamespace(get_game=FixtureGame)),
                        peak_session,
                    )
                    result = (
                        await service.vote(progress)
                        if kind == "peak_pool_vote"
                        else await service.pet_rank("竞技精灵总榜", progress)
                    )
                    assert result.image is not None, result.message
                    return QueryReply(image=result.image)
                # Pool queries use release data without an account/game API.
                result = await PeakQueryService(
                    database, cast("Any", None), peak_session
                ).pool(expert=kind == "expert_pool", progress=progress)
                assert result.image is not None, result.message
                return QueryReply(image=result.image)

            first = await request_reply()
            assert first.image is not None
            image_bytes = first.image
            with Image.open(BytesIO(image_bytes)) as image:
                assert image.format == "PNG"
                minimum_side, minimum_colors = 300, 100
                assert min(image.size) >= minimum_side
                colors = image.convert("RGB").getcolors(image.width * image.height)
                assert colors is not None and len(colors) > minimum_colors
            (tmp_path / f"{kind}.png").write_bytes(image_bytes)
            cold_counts = (len(queries), len(requests), native_calls)
            assert all(cold_counts)
            assert native_calls == 1
            second = await request_reply()
            assert second.image == first.image
            assert len(requests) == cold_counts[1]
            if cache_allowed:
                assert native_calls == cold_counts[2]
                if kind in {"type_matchup", "pet_info"}:
                    assert len(queries) == cold_counts[0]
            else:
                assert native_calls == cold_counts[2] + 1
            print(  # noqa: T201 - opt-in native acceptance diagnostics
                f"{kind}: cache_allowed={cache_allowed}, SQL/HTTP/native="
                f"{cold_counts} -> {(len(queries), len(requests), native_calls)}"
            )
            now = datetime(2026, 9, 12, tzinfo=timezone.utc)
            context = ReplyContext(
                ConversationRef(Platform.QQ_OFFICIAL, "group", "opaque:group"),
                "opaque:event",
                reply_deadline=now + timedelta(seconds=5),
            )
            transport = FakeOfficialPlatform(now)
            message = first.to_outbound()
            assert (await transport.reply(context, message)).delivered
            assert transport.uploads[0].content == image_bytes
            onebot = render_onebot_outbound_message(message)
            assert (
                b64decode(onebot[0].data["file"].removeprefix("base64://"))
                == image_bytes
            )
    finally:
        await owner.cancel_all()
        databases.close()
