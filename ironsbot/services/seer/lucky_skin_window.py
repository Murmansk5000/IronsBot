# SPDX-License-Identifier: MIT
"""Public lucky skin window lookup backed by an authenticated game session."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from functools import partial
from struct import unpack
from typing import TYPE_CHECKING, Protocol
from zoneinfo import ZoneInfo

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage
from ironsbot.integrations.seer_data.skin_price_repository import (
    load_active_skin_store_prices,
)
from ironsbot.integrations.seer_data.skin_reference_repository import (
    load_skins_by_resource_id,
)
from ironsbot.services.seer.data import PublishedDataIncompleteError
from ironsbot.services.seer.pet_query import PetImageSelection
from ironsbot.services.seer.query_result import QueryChoice
from ironsbot.services.seer.skin_price import (
    SkinStorePrice,
    format_lucky_window_price_lines,
)

if TYPE_CHECKING:
    from ironsbot.config.models.seer_lucky import LuckySkinWindowConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ActorRef
    from ironsbot.services.identity.player_accounts import (
        PlayerAccount,
        PlayerAccountRegistry,
    )
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.operations.headless_session import HeadlessSessionFactory
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.player_binding import PlayerBindingStore

logger = logging.getLogger(__name__)

LuckySkinWindowRenderer = Callable[
    ["LuckySkinWindowResult", tuple["LuckySkinWindowOffer", ...]],
    Awaitable[bytes],
]

LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY = "lucky_skin_window"
_GET_LUCKY_SKIN_WINDOW = 45866
_REQUEST = (
    # The official-client capture includes 668 in the packet head's result
    # field. SeerGame derives that value from its connection state, so it must
    # not be copied into this request body.
    0,
    0,
    18,
    203247,
    31101,
    31102,
    31103,
    31104,
    108937,
    108938,
    108939,
    108940,
    108941,
    108942,
    108943,
    401009,
    401010,
    401007,
    401008,
    351005,
    351004,
)
# The server returns the four refreshed skin IDs immediately after the eight
# fixed response fields.  The following field is unrelated metadata, so using
# offset 9 silently dropped the first offer and appended that metadata instead.
_SKIN_OFFSET = 8
_SKIN_COUNT = 4


class LuckySkinWindowCache(Protocol):
    def get(self, *, player_id: int) -> tuple[int, ...] | None: ...

    def prepare_day(self, *, day: str) -> None: ...

    def put_if_absent(
        self,
        *,
        player_id: int,
        skin_ids: tuple[int, ...],
    ) -> tuple[int, ...]: ...


class LuckySkinWatchPreferenceStore(Protocol):
    def get(self, actor: ActorRef) -> tuple[int, ...] | None: ...

    def set(self, actor: ActorRef, skin_ids: tuple[int, ...]) -> None: ...


class LuckySkinWindowNotificationSender(Protocol):
    """Deliver a scheduled lucky-window result to one platform actor."""

    async def send_daily_notice(
        self,
        actor: ActorRef,
        message: str,
        *,
        day: str,
    ) -> bool: ...


class LuckySkinWindowError(RuntimeError):
    @classmethod
    def packet_request_failed(cls) -> LuckySkinWindowError:
        return cls("lucky skin window packet request failed")


class LuckySkinWindowNotConfiguredError(LuckySkinWindowError):
    pass


class LuckySkinWindowConfigurationError(LuckySkinWindowError):
    @classmethod
    def duplicate_actor(cls) -> LuckySkinWindowConfigurationError:
        return cls("lucky skin window accounts repeat an actor")


class LuckySkinWindowBindingError(LuckySkinWindowError):
    pass


class LuckySkinWindowPayloadError(LuckySkinWindowError):
    @classmethod
    def unaligned(cls) -> LuckySkinWindowPayloadError:
        return cls("skin window payload is not uint32 aligned")

    @classmethod
    def truncated(cls) -> LuckySkinWindowPayloadError:
        return cls("skin window payload is truncated")

    @classmethod
    def invalid_skin_ids(cls) -> LuckySkinWindowPayloadError:
        return cls("skin window payload has invalid skin IDs")


@dataclass(frozen=True, slots=True)
class LuckySkinWindowOffer:
    skin_id: int
    resource_id: int
    name: str
    watched: bool
    store_price: SkinStorePrice | None = None


@dataclass(frozen=True, slots=True)
class LuckySkinWindowResult:
    day: str
    player_id: int
    offers: tuple[LuckySkinWindowOffer, ...]
    from_cache: bool


@dataclass(frozen=True, slots=True)
class LuckySkinWatchItem:
    skin_id: int
    resource_id: int
    name: str

    @property
    def identifiers(self) -> str:
        return _skin_identifiers(self.skin_id, self.resource_id)

    @property
    def label(self) -> str:
        return f"{self.name}（{self.identifiers}）"


@dataclass(frozen=True, slots=True)
class LuckySkinWindowAccount:
    """Platform-neutral owner and Seer account for one window subscription."""

    actor: ActorRef
    player_account: PlayerAccount
    watched_skin_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class LuckySkinQuery:
    requester: ActorRef
    owner: ActorRef | None
    player_id: int | None = None


class LuckySkinWindowAccessError(ValueError):
    """The requested account cannot be queried by this actor."""


class LuckySkinWindowService:
    def __init__(  # noqa: PLR0913 - explicit composition dependencies
        self,
        config: LuckySkinWindowConfig,
        accounts: tuple[LuckySkinWindowAccount, ...],
        features: FeatureService,
        headless_sessions: HeadlessSessionFactory,
        data: SeerDataAccess,
        bindings: PlayerBindingStore,
        watch_preferences: LuckySkinWatchPreferenceStore,
        cache: LuckySkinWindowCache,
        notification_sender: LuckySkinWindowNotificationSender,
        *,
        player_accounts: PlayerAccountRegistry,
        today: Callable[[], date] | None = None,
        renderer: LuckySkinWindowRenderer | None = None,
    ) -> None:
        self._config = config
        self._player_accounts = player_accounts
        self._features = features
        self._headless_sessions = headless_sessions
        self._data = data
        self._bindings = bindings
        self._watch_preferences = watch_preferences
        self._cache = cache
        self._notification_sender = notification_sender
        self._today = today or (lambda: datetime.now(ZoneInfo(config.timezone)).date())
        self._renderer = renderer
        self._accounts = {configured.actor: configured for configured in accounts}
        if len(self._accounts) != len(accounts):
            raise LuckySkinWindowConfigurationError.duplicate_actor()
        self._query_lock = asyncio.Lock()
        self._memory: dict[int, tuple[int, ...]] = {}
        self._cache_day: str | None = None

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def config(self) -> LuckySkinWindowConfig:
        return self._config

    def day_key(self) -> str:
        return self._today().isoformat()

    def clear_previous_days(self) -> None:
        self._prepare_day(self.day_key())

    def account_for_actor(self, actor: ActorRef) -> PlayerAccount | None:
        configured = self._accounts.get(actor)
        return configured.player_account if configured is not None else None

    def is_eligible_actor(self, actor: ActorRef) -> bool:
        account = self.account_for_actor(actor)
        if not self.enabled or account is None:
            return False
        return self._bindings.get(actor).player_id == account.player_id

    def watched_skins(self, actor: ActorRef) -> tuple[LuckySkinWatchItem, ...]:
        skin_ids = self._watched_skin_ids(actor)
        if not skin_ids:
            return ()
        with self._data.get_many(self._data.pet_skin, set(skin_ids)) as skins:
            return tuple(
                _watch_item(skins.get(skin_id), skin_id) for skin_id in skin_ids
            )

    def watch_list_message(self, actor: ActorRef) -> str:
        items = self.watched_skins(actor)
        lines = ["【幸运橱窗关注】"]
        if items:
            lines.extend(
                f"{index}. {item.label}"
                for index, item in enumerate(items, start=1)
            )
        else:
            lines.append("暂无关注皮肤。")
        lines.extend(
            (
                "发送“关注橱窗 / 订阅橱窗 + ID或名称”新增，",
                "发送“取消关注橱窗 / 退订橱窗 + ID或名称”取消。",
            )
        )
        return "\n".join(lines)

    def resolve_watch_candidates(
        self,
        actor: ActorRef,
        arg: str,
    ) -> tuple[LuckySkinWatchItem, ...]:
        self._validated_account_for_actor(actor)
        normalized = arg.strip()
        if not normalized:
            return ()
        if normalized.isdigit():
            return self._skin_items_for_references((int(normalized),))
        with self._data.resolve(self._data.pet_skin, normalized) as skins:
            return tuple(
                LuckySkinWatchItem(
                    skin_id=int(skin.id),
                    resource_id=int(skin.resource_id),
                    name=str(skin.name),
                )
                for skin in sorted(skins, key=lambda item: int(item.id))
            )

    def watch_change_message(
        self,
        actor: ActorRef,
        item: LuckySkinWatchItem,
        *,
        watched: bool,
    ) -> str:
        current = self._watched_skin_ids(actor)
        if watched:
            if item.skin_id in current:
                return f"已经关注：{item.label}"
            self._watch_preferences.set(actor, (*current, item.skin_id))
            return f"已关注：{item.label}"
        if item.skin_id not in current:
            return f"尚未关注：{item.label}"
        self._watch_preferences.set(
            actor,
            tuple(value for value in current if value != item.skin_id),
        )
        return f"已取消关注：{item.label}"

    def watch_clear_message(self, actor: ActorRef) -> str:
        current = self._watched_skin_ids(actor)
        self._watch_preferences.set(actor, ())
        return "已清空关注皮肤。" if current else "当前没有关注皮肤。"

    def watch_reset_message(self, actor: ActorRef) -> str:
        self._validated_account_for_actor(actor)
        defaults = self._default_watched_skin_ids(actor)
        self._watch_preferences.set(actor, defaults)
        return "已恢复 TOML 初始关注列表。\n" + self.watch_list_message(actor)

    async def query(self, request: LuckySkinQuery) -> LuckySkinWindowResult:
        account = self._account_for_query(request)
        if cached := self._cached_result(account.player_id):
            return cached
        return await self._check(account, background=False)

    def cached_query(self, request: LuckySkinQuery) -> LuckySkinWindowResult | None:
        """Return today's result without opening the dedicated game session."""
        account = self._account_for_query(request)
        return self._cached_result(account.player_id)

    def _account_for_query(self, request: LuckySkinQuery) -> PlayerAccount:
        if request.player_id is None:
            if request.owner is None:
                raise LuckySkinWindowNotConfiguredError
            return self._validated_account_for_actor(request.owner)
        if not self._features.is_actor_superuser(request.requester):
            if request.owner is None:
                raise LuckySkinWindowAccessError("只能查询你本人已配置的幸运橱窗账号。")
            own = self._validated_account_for_actor(request.owner)
            if own.player_id != request.player_id:
                raise LuckySkinWindowAccessError("只能查询你本人已配置的幸运橱窗账号。")
            return own
        account = self._player_accounts.account_for_player_id(request.player_id)
        if not self.enabled or account is None or account.password is None:
            raise LuckySkinWindowAccessError("该米米号未配置可用的幸运橱窗登录账号。")
        return account

    async def send_daily_notifications(self) -> None:
        if not self.enabled:
            return
        for actor, configured in self._accounts.items():
            feature_enabled = self._features.actor_has_feature(
                actor,
                "lucky_skin_window",
            )
            if not self.is_eligible_actor(actor) or not feature_enabled:
                continue
            account = configured.player_account
            try:
                result = await self._check(account, background=True)
                message = self.format_result(result, actor=actor)
            except Exception:
                logger.exception(
                    "lucky skin window scheduled check failed: player_id=%s",
                    account.player_id,
                )
                message = "❌ 幸运橱窗数据暂时不可用，请稍后使用“橱窗”查询。"
            await self._notification_sender.send_daily_notice(
                actor,
                message,
                day=self.day_key(),
            )

    def _validated_account_for_actor(
        self,
        actor: ActorRef,
    ) -> PlayerAccount:
        account = self.account_for_actor(actor)
        if not self.enabled or account is None:
            raise LuckySkinWindowNotConfiguredError
        if self._bindings.get(actor).player_id != account.player_id:
            raise LuckySkinWindowBindingError(account.player_id)
        return account

    async def _check(
        self,
        account: PlayerAccount,
        *,
        background: bool,
    ) -> LuckySkinWindowResult:
        player_id = account.player_id
        day = self.day_key()
        if cached := self._cached_result(player_id):
            return cached

        # asyncio.Lock wakes waiters in arrival order, so dedicated account
        # logins never overlap even when scheduled and manual checks coincide.
        async with self._query_lock:
            if cached := self._cached_result(player_id):
                return cached
            async with self._headless_sessions.open(
                user_id=player_id,
                password=_required_password(account),
                label="幸运橱窗",
            ) as game:
                skin_ids = await _fetch_skin_ids(
                    game,
                    timeout_seconds=self._config.timeout_seconds,
                    background=background,
                )
            day = self.day_key()
            self._prepare_day(day)
            self._memory[player_id] = skin_ids
            persisted = self._cache.put_if_absent(
                player_id=player_id,
                skin_ids=skin_ids,
            )
            self._memory[player_id] = persisted
            logger.info(
                "lucky skin window cache stored: player_id=%s day=%s",
                player_id,
                day,
            )
            return self._result(player_id, day, persisted, from_cache=False)

    def _cached_result(self, player_id: int) -> LuckySkinWindowResult | None:
        day = self.day_key()
        self._prepare_day(day)
        if skin_ids := self._memory.get(player_id):
            logger.info(
                "lucky skin window cache hit: player_id=%s day=%s source=memory",
                player_id,
                day,
            )
            return self._result(player_id, day, skin_ids, from_cache=True)
        if skin_ids := self._cache.get(player_id=player_id):
            self._memory[player_id] = skin_ids
            logger.info(
                "lucky skin window cache hit: player_id=%s day=%s source=sqlite",
                player_id,
                day,
            )
            return self._result(player_id, day, skin_ids, from_cache=True)
        logger.info(
            "lucky skin window cache miss: player_id=%s day=%s",
            player_id,
            day,
        )
        return None

    def _prepare_day(self, day: str) -> None:
        if self._cache_day == day:
            return
        self._cache.prepare_day(day=day)
        self._memory.clear()
        self._cache_day = day

    def _result(
        self,
        player_id: int,
        day: str,
        skin_ids: tuple[int, ...],
        *,
        from_cache: bool,
    ) -> LuckySkinWindowResult:
        resolved = self._skin_items_by_reference(skin_ids)
        skin_ids_by_reference = {
            reference: (item.skin_id if item is not None else reference)
            for reference in skin_ids
            for item in (resolved.get(reference),)
        }
        try:
            with self._data.query(
                partial(
                    load_active_skin_store_prices,
                    skin_ids=tuple(skin_ids_by_reference.values()),
                )
            ) as store_prices:
                active_prices = store_prices
        except PublishedDataIncompleteError as error:
            logger.warning(
                "lucky skin window prices unavailable: day=%s error=%s",
                day,
                error,
            )
            active_prices = {}
        offers = tuple(
            LuckySkinWindowOffer(
                skin_id=skin_ids_by_reference[reference],
                resource_id=(item.resource_id if item is not None else 0),
                name=(item.name if item is not None else f"皮肤 {reference}"),
                watched=False,
                store_price=active_prices.get(skin_ids_by_reference[reference]),
            )
            for reference in skin_ids
            for item in (resolved.get(reference),)
        )
        return LuckySkinWindowResult(day, player_id, offers, from_cache)

    def format_result(
        self, result: LuckySkinWindowResult, *, actor: ActorRef | None,
    ) -> str:
        offers = self._offers_for_actor(result, actor)
        lines = ["【幸运橱窗】", "今日刷新皮肤："]
        for index, offer in enumerate(offers, start=1):
            marker = " ★ 关注" if offer.watched else ""
            identifiers = _skin_identifiers(offer.skin_id, offer.resource_id)
            lines.append(f"{index}. {offer.name}（{identifiers}）{marker}")
            lines.extend(
                f"   {line}"
                for line in format_lucky_window_price_lines(offer.store_price)
            )
        lines.append("发送 1-4 查看对应皮肤详情 · 0 退出")
        return "\n".join(lines)

    @staticmethod
    def detail_choices(
        result: LuckySkinWindowResult,
    ) -> tuple[QueryChoice[PetImageSelection], ...]:
        return tuple(
            QueryChoice(
                offer.name,
                _skin_identifiers(offer.skin_id, offer.resource_id),
                PetImageSelection(
                    offer.resource_id,
                    offer.name,
                    skin_id=offer.skin_id,
                ),
            )
            for offer in result.offers
        )

    async def render_result(
        self,
        result: LuckySkinWindowResult,
        *,
        actor: ActorRef | None,
    ) -> bytes | None:
        if self._renderer is None:
            return None
        try:
            return await self._renderer(result, self._offers_for_actor(result, actor))
        except Exception:
            logger.exception(
                "lucky skin window render failed: player_id=%s day=%s",
                result.player_id,
                result.day,
            )
            return None

    async def result_message(
        self,
        result: LuckySkinWindowResult,
        *,
        actor: ActorRef | None,
    ) -> OutboundMessage:
        rendered = await self.render_result(result, actor=actor)
        if rendered is not None:
            return OutboundMessage((BinaryImagePart(rendered, "image/png"),))
        return OutboundMessage.from_text(self.format_result(result, actor=actor))

    def _offers_for_actor(
        self,
        result: LuckySkinWindowResult,
        actor: ActorRef | None,
    ) -> tuple[LuckySkinWindowOffer, ...]:
        watched_ids = frozenset(
            self._watched_skin_ids(actor)
            if actor is not None and self.is_eligible_actor(actor)
            else ()
        )
        return tuple(
            replace(offer, watched=offer.skin_id in watched_ids)
            for offer in result.offers
        )

    def _watched_skin_ids(self, actor: ActorRef) -> tuple[int, ...]:
        self._validated_account_for_actor(actor)
        stored = self._watch_preferences.get(actor)
        if stored is not None:
            return stored
        defaults = self._default_watched_skin_ids(actor)
        self._watch_preferences.set(actor, defaults)
        return defaults

    def _default_watched_skin_ids(self, actor: ActorRef) -> tuple[int, ...]:
        configured = self._accounts[actor]
        references = configured.watched_skin_ids
        if not references:
            return ()
        resolved = self._skin_items_by_reference(references)
        missing = tuple(value for value in references if value not in resolved)
        if missing:
            logger.warning(
                "lucky skin watch defaults could not be resolved: "
                "actor=%s references=%s",
                actor,
                missing,
            )
        return tuple(
            dict.fromkeys(
                resolved[reference].skin_id
                for reference in references
                if reference in resolved
            )
        )

    def _skin_items_for_references(
        self,
        references: tuple[int, ...],
    ) -> tuple[LuckySkinWatchItem, ...]:
        resolved = self._skin_items_by_reference(references)
        return tuple(
            resolved[reference] for reference in references if reference in resolved
        )

    def _skin_items_by_reference(
        self,
        references: tuple[int, ...],
    ) -> dict[int, LuckySkinWatchItem]:
        if not references:
            return {}
        with self._data.get_many(self._data.pet_skin, set(references)) as by_id:
            resolved = {
                reference: _watch_item(skin, reference)
                for reference in references
                if (skin := by_id.get(reference)) is not None
            }
        unresolved = frozenset(
            reference for reference in references if reference not in resolved
        )
        if not unresolved:
            return resolved
        with self._data.query(
            partial(load_skins_by_resource_id, references=unresolved)
        ) as skins:
            by_resource_id = {int(skin.resource_id): skin for skin in skins}
            resolved.update(
                {
                    reference: _watch_item(skin, reference)
                    for reference in unresolved
                    if (skin := by_resource_id.get(reference)) is not None
                }
            )
        return resolved


async def _fetch_skin_ids(
    game: HeadlessGame,
    *,
    timeout_seconds: float,
    background: bool,
) -> tuple[int, ...]:
    try:
        with game.operations.track(
            "幸运橱窗检查",
            source="幸运橱窗专用会话",
            background=background,
        ):
            _head, payload = await game.send_and_wait(
                _GET_LUCKY_SKIN_WINDOW,
                *_REQUEST,
                timeout=timeout_seconds,
            )
    except (ConnectionError, TimeoutError) as error:
        raise LuckySkinWindowError.packet_request_failed() from error
    return _parse_skin_ids(payload)


def _parse_skin_ids(payload: bytes | bytearray | memoryview) -> tuple[int, ...]:
    data = bytes(payload)
    if len(data) % 4:
        raise LuckySkinWindowPayloadError.unaligned()
    values = unpack(f"!{len(data) // 4}I", data)
    if len(values) < _SKIN_OFFSET + _SKIN_COUNT:
        raise LuckySkinWindowPayloadError.truncated()
    skin_ids = tuple(values[_SKIN_OFFSET : _SKIN_OFFSET + _SKIN_COUNT])
    if len(skin_ids) != _SKIN_COUNT or any(skin_id <= 0 for skin_id in skin_ids):
        raise LuckySkinWindowPayloadError.invalid_skin_ids()
    return skin_ids


def _required_password(account: PlayerAccount) -> str:
    if account.password is None:
        raise LuckySkinWindowNotConfiguredError
    return account.password


def _watch_item(skin: object | None, fallback_id: int) -> LuckySkinWatchItem:
    if skin is None:
        return LuckySkinWatchItem(fallback_id, 0, f"皮肤 {fallback_id}")
    skin_id = int(getattr(skin, "id", fallback_id))
    resource_id = int(getattr(skin, "resource_id", 0) or 0)
    name = str(getattr(skin, "name", "") or f"皮肤 {skin_id}")
    return LuckySkinWatchItem(skin_id, resource_id, name)


def _skin_identifiers(skin_id: int, resource_id: int) -> str:
    if resource_id > 0 and resource_id != skin_id:
        return f"皮肤ID：{skin_id}，资源ID：{resource_id}"
    return f"皮肤ID：{skin_id}"
