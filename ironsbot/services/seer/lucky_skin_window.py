# SPDX-License-Identifier: MIT
"""Public lucky skin window lookup backed by an authenticated game session."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from struct import unpack
from typing import TYPE_CHECKING, Protocol
from zoneinfo import ZoneInfo

from ironsbot.core.messaging import MessageTarget
from ironsbot.services.messaging.subscriptions import PushSubscriptionOption

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.seer import (
        LuckySkinWindowAccountConfig,
        LuckySkinWindowConfig,
    )
    from ironsbot.core.features import FeatureService
    from ironsbot.core.onebot_references import OneBotReferenceResolver
    from ironsbot.services.messaging.delivery import MessageDelivery
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.operations.headless_session import HeadlessSessionFactory
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.player_binding import PlayerBindingStore

logger = logging.getLogger(__name__)

LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY = "lucky_skin_window"
_GET_LUCKY_SKIN_WINDOW = 45866
_REQUEST = (
    # Captured from the official client before the two reserved zero fields.
    668,
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
_SKIN_OFFSET = 9
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


class LuckySkinWindowError(RuntimeError):
    @classmethod
    def packet_request_failed(cls) -> LuckySkinWindowError:
        return cls("lucky skin window packet request failed")


class LuckySkinWindowNotConfiguredError(LuckySkinWindowError):
    pass


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
    name: str
    watched: bool


@dataclass(frozen=True, slots=True)
class LuckySkinWindowResult:
    day: str
    player_id: int
    offers: tuple[LuckySkinWindowOffer, ...]
    from_cache: bool


class LuckySkinWindowService:
    def __init__(  # noqa: PLR0913 - explicit composition dependencies
        self,
        config: LuckySkinWindowConfig,
        references: OneBotReferenceResolver,
        features: FeatureService,
        headless_sessions: HeadlessSessionFactory,
        data: SeerDataAccess,
        bindings: PlayerBindingStore,
        subscriptions: PushSubscriptionRepository,
        cache: LuckySkinWindowCache,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._config = config
        self._features = features
        self._headless_sessions = headless_sessions
        self._data = data
        self._bindings = bindings
        self._subscriptions = subscriptions
        self._cache = cache
        self._today = today or (lambda: datetime.now(ZoneInfo(config.timezone)).date())
        self._accounts = {
            references.resolve_user(
                account.user,
                location=f"seer.lucky_skin_window.accounts[{index}].user",
            ): account
            for index, account in enumerate(config.accounts)
        }
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

    def account_for_user(self, user_id: int) -> LuckySkinWindowAccountConfig | None:
        return self._accounts.get(user_id)

    def is_eligible_user(self, user_id: int) -> bool:
        account = self.account_for_user(user_id)
        if not self.enabled or account is None:
            return False
        return self._bindings.get(user_id).player_id == account.player_id

    def subscription_options(
        self,
        target_type: str,
        target_id: int,
    ) -> list[PushSubscriptionOption]:
        if target_type != "private" or not self.is_eligible_user(target_id):
            return []
        return [
            PushSubscriptionOption(
                key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
                label="幸运橱窗提醒",
                feature="lucky_skin_window",
                unsubscribed=self._subscriptions.is_target_unsubscribed(
                    "private",
                    target_id,
                    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
                ),
            )
        ]

    async def check_for_user(self, user_id: int) -> LuckySkinWindowResult:
        account = self._validated_account_for_user(user_id)
        if cached := self._cached_result(account.player_id):
            return cached
        return await self._check(account, background=False)

    async def send_daily_notifications(self, delivery: MessageDelivery) -> None:
        if not self.enabled:
            return
        target_ids = self._subscriptions.filter_subscribed_user_ids(
            [
                user_id
                for user_id in self._accounts
                if self.is_eligible_user(user_id)
                and self._features.is_private_feature_allowed(
                    user_id,
                    "lucky_skin_window",
                )
            ],
            LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
        )
        if not target_ids:
            return
        for user_id in target_ids:
            account = self._accounts[user_id]
            try:
                result = await self._check(account, background=True)
                message = self.format_result(result, user_id=user_id)
            except Exception:
                logger.exception(
                    "lucky skin window scheduled check failed: player_id=%s",
                    account.player_id,
                )
                message = "❌ 幸运橱窗数据暂时不可用，请稍后使用“橱窗”查询。"
            await self._send_daily_notice(delivery, user_id, message)

    async def _send_daily_notice(
        self,
        delivery: MessageDelivery,
        user_id: int,
        message: str,
    ) -> None:
        if not self._subscriptions.mark_daily_hint_sent(
            "private",
            user_id,
            "lucky_skin_window_delivery",
            today=self.day_key(),
        ):
            return
        await delivery.send_targets(
            [MessageTarget("private", user_id)],
            message,
            action_name="lucky skin window daily notice",
            interval_seconds=0,
            subscription_key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
        )

    def _validated_account_for_user(
        self,
        user_id: int,
    ) -> LuckySkinWindowAccountConfig:
        account = self.account_for_user(user_id)
        if not self.enabled or account is None:
            raise LuckySkinWindowNotConfiguredError
        if self._bindings.get(user_id).player_id != account.player_id:
            raise LuckySkinWindowBindingError(account.player_id)
        return account

    async def _check(
        self,
        account: LuckySkinWindowAccountConfig,
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
                password=account.password,
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
            return self._result(player_id, day, persisted, from_cache=False)

    def _cached_result(self, player_id: int) -> LuckySkinWindowResult | None:
        day = self.day_key()
        self._prepare_day(day)
        if skin_ids := self._memory.get(player_id):
            return self._result(player_id, day, skin_ids, from_cache=True)
        if skin_ids := self._cache.get(player_id=player_id):
            self._memory[player_id] = skin_ids
            return self._result(player_id, day, skin_ids, from_cache=True)
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
        with self._data.get_many(self._data.pet_skin, set(skin_ids)) as skins:
            offers = tuple(
                LuckySkinWindowOffer(
                    skin_id=skin_id,
                    name=_skin_name(skins.get(skin_id), skin_id),
                    watched=False,
                )
                for skin_id in skin_ids
            )
        return LuckySkinWindowResult(day, player_id, offers, from_cache)

    def format_result(self, result: LuckySkinWindowResult, *, user_id: int) -> str:
        account = self._accounts[user_id]
        watched_ids = frozenset(account.watched_skin_ids)
        lines = ["【幸运橱窗】", "今日刷新皮肤："]
        for index, offer in enumerate(result.offers, start=1):
            marker = " ★ 关注" if offer.skin_id in watched_ids else ""
            lines.append(f"{index}. {offer.name}（皮肤ID：{offer.skin_id}）{marker}")
        return "\n".join(lines)


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


def _skin_name(skin: object | None, skin_id: int) -> str:
    name = getattr(skin, "name", "")
    return str(name) if isinstance(name, str) and name else f"皮肤 {skin_id}"
