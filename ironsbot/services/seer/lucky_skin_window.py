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
from time import monotonic
from typing import TYPE_CHECKING, Protocol
from zoneinfo import ZoneInfo

from seerapi_models import PetSkinORM
from sqlmodel import Session, col, select

from ironsbot.core.messaging import DeliveryReceipt, MessageTarget
from ironsbot.services.messaging.subscriptions import PushSubscriptionOption
from ironsbot.services.seer.skin_price import (
    FASHION_TICKET_VALUE,
    SkinStorePrice,
    load_active_skin_store_prices,
)

if TYPE_CHECKING:
    from ironsbot.config.models.seer import LuckySkinWindowConfig
    from ironsbot.config.player_accounts import PlayerAccount, PlayerAccountRegistry
    from ironsbot.core.features import FeatureService
    from ironsbot.core.onebot_references import OneBotReferenceResolver
    from ironsbot.services.messaging.delivery import MessageDelivery
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.operations.headless_session import HeadlessSessionFactory
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.player_binding import PlayerBindingStore

logger = logging.getLogger(__name__)

LuckySkinWindowRenderer = Callable[
    ["LuckySkinWindowResult", tuple["LuckySkinWindowOffer", ...]],
    Awaitable[bytes],
]


class LuckySkinWindowMessageFormatter(Protocol):
    async def __call__(
        self,
        result: LuckySkinWindowResult,
        *,
        user_id: int,
    ) -> object: ...

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
    def get(self, *, player_id: int, day: str) -> tuple[int, ...] | None: ...

    def prepare_day(self, *, day: str) -> None: ...

    def put_if_absent(
        self,
        *,
        player_id: int,
        skin_ids: tuple[int, ...],
    ) -> tuple[int, ...]: ...


class LuckySkinWatchPreferenceStore(Protocol):
    def get(self, qq_user_id: int) -> tuple[int, ...] | None: ...

    def set(self, qq_user_id: int, skin_ids: tuple[int, ...]) -> None: ...


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


class LuckySkinWindowService:
    def __init__(  # noqa: PLR0913 - explicit composition dependencies
        self,
        config: LuckySkinWindowConfig,
        references: OneBotReferenceResolver,
        player_accounts: PlayerAccountRegistry,
        features: FeatureService,
        headless_sessions: HeadlessSessionFactory,
        data: SeerDataAccess,
        bindings: PlayerBindingStore,
        subscriptions: PushSubscriptionRepository,
        watch_preferences: LuckySkinWatchPreferenceStore,
        cache: LuckySkinWindowCache,
        *,
        today: Callable[[], date] | None = None,
        renderer: LuckySkinWindowRenderer | None = None,
    ) -> None:
        self._config = config
        self._features = features
        self._player_accounts = player_accounts
        self._headless_sessions = headless_sessions
        self._data = data
        self._bindings = bindings
        self._subscriptions = subscriptions
        self._watch_preferences = watch_preferences
        self._cache = cache
        self._today = today or (lambda: datetime.now(ZoneInfo(config.timezone)).date())
        self._renderer = renderer
        self._accounts = {
            references.resolve_user(
                account.user,
                location=f"seer.lucky_skin_window.accounts[{index}].user",
            ): (
                account,
                player_accounts.resolve(
                    account.account,
                    location=f"seer.lucky_skin_window.accounts[{index}].account",
                ),
            )
            for index, account in enumerate(config.accounts)
        }
        self._accounts_by_player_id = {
            account.player_id for _subscription, account in self._accounts.values()
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

    def account_for_user(self, user_id: int) -> PlayerAccount | None:
        configured = self._accounts.get(user_id)
        return configured[1] if configured is not None else None

    @property
    def player_accounts(self) -> PlayerAccountRegistry:
        return self._player_accounts

    def default_player_id(self, user_id: int) -> int | None:
        return self._bindings.get(user_id).player_id

    def account_for_player_id(self, player_id: int) -> PlayerAccount | None:
        if player_id not in self._accounts_by_player_id:
            return None
        return self._player_accounts.account_for_player_id(player_id)

    def can_login_account(self, user_id: int, player_id: int) -> bool:
        """Return whether this QQ user owns and still binds the login account."""

        account = self.account_for_user(user_id)
        return (
            account is not None
            and account.player_id == player_id
            and self.default_player_id(user_id) == player_id
        )

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

    def watched_skins(self, user_id: int) -> tuple[LuckySkinWatchItem, ...]:
        skin_ids = self._watched_skin_ids(user_id)
        if not skin_ids:
            return ()
        with self._data.get_many(self._data.pet_skin, set(skin_ids)) as skins:
            return tuple(
                _watch_item(skins.get(skin_id), skin_id)
                for skin_id in skin_ids
            )

    def resolve_watch_candidates(
        self,
        user_id: int,
        arg: str,
    ) -> tuple[LuckySkinWatchItem, ...]:
        self._validated_account_for_user(user_id)
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

    def add_watched_skin(self, user_id: int, skin_id: int) -> bool:
        current = self._watched_skin_ids(user_id)
        if skin_id in current:
            return False
        self._watch_preferences.set(user_id, (*current, skin_id))
        return True

    def remove_watched_skin(self, user_id: int, skin_id: int) -> bool:
        current = self._watched_skin_ids(user_id)
        if skin_id not in current:
            return False
        self._watch_preferences.set(
            user_id,
            tuple(value for value in current if value != skin_id),
        )
        return True

    def clear_watched_skins(self, user_id: int) -> bool:
        current = self._watched_skin_ids(user_id)
        self._watch_preferences.set(user_id, ())
        return bool(current)

    def reset_watched_skins(
        self,
        user_id: int,
    ) -> tuple[LuckySkinWatchItem, ...]:
        self._validated_account_for_user(user_id)
        defaults = self._default_watched_skin_ids(user_id)
        self._watch_preferences.set(user_id, defaults)
        return self.watched_skins(user_id)

    async def check_for_user(self, user_id: int) -> LuckySkinWindowResult:
        account = self._validated_account_for_user(user_id)
        if cached := self._cached_result(account.player_id):
            return cached
        return await self._check(account, background=False)

    def cached_for_user(self, user_id: int) -> LuckySkinWindowResult | None:
        """Return today's result without opening the dedicated game session."""
        account = self._validated_account_for_user(user_id)
        return self._cached_result(account.player_id)

    def cached_for_account(self, player_id: int) -> LuckySkinWindowResult | None:
        account = self.account_for_player_id(player_id)
        if account is None:
            raise LuckySkinWindowNotConfiguredError
        return self._cached_result(account.player_id)

    async def check_for_account(self, player_id: int) -> LuckySkinWindowResult:
        account = self.account_for_player_id(player_id)
        if account is None:
            raise LuckySkinWindowNotConfiguredError
        return await self._check(account, background=False)

    async def send_daily_notifications(
        self,
        delivery: MessageDelivery,
        *,
        format_message: LuckySkinWindowMessageFormatter | None = None,
    ) -> None:
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
        day = self.day_key()
        logger.info(
            "lucky skin window daily task started: day=%s targets=%s",
            day,
            len(target_ids),
        )
        notices: list[tuple[MessageTarget, object]] = []
        audit_contexts: dict[MessageTarget, tuple[int, tuple[int, ...]]] = {}
        for user_id in target_ids:
            _subscription, account = self._accounts[user_id]
            started_at = monotonic()
            skin_ids: tuple[int, ...] = ()
            logger.info(
                "lucky skin window daily query started: day=%s player_id=%s "
                "target_id=%s",
                day,
                account.player_id,
                user_id,
            )
            try:
                result = await self._check(account, background=True)
                skin_ids = tuple(offer.skin_id for offer in result.offers)
                logger.info(
                    "lucky skin window daily query succeeded: day=%s player_id=%s "
                    "target_id=%s source=%s skin_ids=%s elapsed=%.3fs",
                    result.day,
                    account.player_id,
                    user_id,
                    "cache" if result.from_cache else "live",
                    skin_ids,
                    monotonic() - started_at,
                )
                message = (
                    await format_message(result, user_id=user_id)
                    if format_message is not None
                    else self.format_result(result, user_id=user_id)
                )
            except Exception:
                logger.exception(
                    "lucky skin window scheduled check failed: player_id=%s",
                    account.player_id,
                )
                message = "❌ 幸运橱窗数据暂时不可用，请稍后使用“橱窗”查询。"
            if self._subscriptions.mark_daily_hint_sent(
                "private",
                user_id,
                "lucky_skin_window_delivery",
                today=self.day_key(),
            ):
                target = MessageTarget("private", user_id)
                notices.append((target, message))
                audit_contexts[target] = (account.player_id, skin_ids)
        if notices:
            await delivery.send_target_messages(
                notices,
                action_name="lucky skin window daily notice",
                subscription_key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
                receipt_handler=partial(
                    self._log_daily_delivery_receipt,
                    day=day,
                    contexts=audit_contexts,
                ),
                verify_history=True,
            )

    @staticmethod
    def _log_daily_delivery_receipt(
        receipt: DeliveryReceipt,
        *,
        day: str,
        contexts: dict[MessageTarget, tuple[int, tuple[int, ...]]],
    ) -> None:
        player_id, skin_ids = contexts.get(receipt.target, (None, ()))
        details = (
            "lucky skin window daily delivery receipt: day=%s player_id=%s "
            "target_id=%s bot_id=%s skin_ids=%s message_id=%s "
            "history_status=%s"
        )
        values = (
            day,
            player_id,
            receipt.target.target_id,
            receipt.bot_id,
            skin_ids,
            receipt.message_id,
            receipt.history_status,
        )
        if receipt.history_status == "confirmed":
            logger.info(details, *values)
            return
        logger.error(
            details + " history_error=%s",
            *values,
            receipt.history_error,
        )

    def _validated_account_for_user(
        self,
        user_id: int,
    ) -> PlayerAccount:
        account = self.account_for_user(user_id)
        if not self.enabled or account is None:
            raise LuckySkinWindowNotConfiguredError
        if self._bindings.get(user_id).player_id != account.player_id:
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
        if skin_ids := self._cache.get(player_id=player_id, day=day):
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
        with self._data.query(
            partial(load_active_skin_store_prices, skin_ids=skin_ids)
        ) as store_prices:
            for reference in skin_ids:
                item = resolved.get(reference)
                skin_id = item.skin_id if item is not None else reference
                if skin_id not in store_prices:
                    logger.warning(
                        "lucky skin window store price missing: day=%s skin_id=%s "
                        "resource_id=%s",
                        day,
                        skin_id,
                        item.resource_id if item is not None else 0,
                    )
            offers = tuple(
                LuckySkinWindowOffer(
                    skin_id=(item.skin_id if item is not None else reference),
                    resource_id=(item.resource_id if item is not None else 0),
                    name=(item.name if item is not None else f"皮肤 {reference}"),
                    watched=False,
                    store_price=store_prices.get(
                        item.skin_id if item is not None else reference
                    ),
                )
                for reference in skin_ids
                for item in (resolved.get(reference),)
            )
        return LuckySkinWindowResult(day, player_id, offers, from_cache)

    def format_result(self, result: LuckySkinWindowResult, *, user_id: int) -> str:
        offers = self._offers_for_user(result, user_id=user_id)
        lines = ["【幸运橱窗】", "今日刷新皮肤："]
        for index, offer in enumerate(offers, start=1):
            marker = " ★ 关注" if offer.watched else ""
            identifiers = _skin_identifiers(offer.skin_id, offer.resource_id)
            lines.append(f"{index}. {offer.name}（{identifiers}）{marker}")
            if offer.store_price is None:
                lines.append("   橱窗价格数据异常")
            else:
                lines.extend(_format_offer_price(offer.store_price))
        lines.append("发送 1-4 查看对应皮肤详情 · 0 退出")
        return "\n".join(lines)

    async def render_result(
        self,
        result: LuckySkinWindowResult,
        *,
        user_id: int,
    ) -> bytes | None:
        if self._renderer is None:
            return None
        try:
            return await self._renderer(
                result,
                self._offers_for_user(result, user_id=user_id),
            )
        except Exception:
            logger.exception(
                "lucky skin window render failed: player_id=%s day=%s",
                result.player_id,
                result.day,
            )
            return None

    def _offers_for_user(
        self,
        result: LuckySkinWindowResult,
        *,
        user_id: int,
    ) -> tuple[LuckySkinWindowOffer, ...]:
        watched_ids = frozenset(self._watched_skin_ids(user_id))
        return tuple(
            replace(offer, watched=offer.skin_id in watched_ids)
            for offer in result.offers
        )

    def _watched_skin_ids(self, user_id: int) -> tuple[int, ...]:
        self._validated_account_for_user(user_id)
        stored = self._watch_preferences.get(user_id)
        if stored is not None:
            return stored
        defaults = self._default_watched_skin_ids(user_id)
        self._watch_preferences.set(user_id, defaults)
        return defaults

    def _default_watched_skin_ids(self, user_id: int) -> tuple[int, ...]:
        subscription, _account = self._accounts[user_id]
        references = tuple(subscription.watched_skin_ids)
        if not references:
            return ()
        resolved = self._skin_items_by_reference(references)
        missing = tuple(value for value in references if value not in resolved)
        if missing:
            logger.warning(
                "lucky skin watch defaults could not be resolved: "
                "user_id=%s references=%s",
                user_id,
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
            resolved[reference]
            for reference in references
            if reference in resolved
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
            partial(_load_skin_records_by_resource_id, references=unresolved)
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


def _load_skin_records_by_resource_id(
    session: Session,
    *,
    references: frozenset[int],
) -> tuple[PetSkinORM, ...]:
    if not references:
        return ()
    statement = select(PetSkinORM).where(col(PetSkinORM.resource_id).in_(references))
    return tuple(session.exec(statement).all())


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


def _format_offer_price(price: SkinStorePrice) -> tuple[str, ...]:
    if price.price <= 0:
        return ("   橱窗价格数据异常",)

    price_text = f"   橱窗价：{price.price}钻"
    if price.original_price > 0 and price.original_price != price.price:
        price_text += f"（原价{price.original_price}钻）"
    if price.ticket_num <= 0:
        return (price_text,)

    ticket_discount = price.ticket_num * FASHION_TICKET_VALUE
    if ticket_discount < price.price:
        minimum = price.price - ticket_discount
        ticket_text = f"   最多用{price.ticket_num}张风尚券，最低{minimum}钻"
    else:
        ticket_text = f"   最多用{price.ticket_num}张风尚券，可抵扣{ticket_discount}钻"
    return price_text, ticket_text
