# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from random import choice
from typing import TYPE_CHECKING, Literal, Protocol

from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ironsbot.core.features import HelpConfig


class HintFeaturePolicy(Protocol):
    def is_group_feature_allowed(
        self,
        user_id: int,
        group_id: int,
        feature: str,
    ) -> bool: ...

    def is_private_feature_allowed(self, user_id: int, feature: str) -> bool: ...


class PokeLikeEvent(Protocol):
    self_id: int
    target_id: int


@dataclass(frozen=True, slots=True)
class PokeHint:
    feature: str
    plugin_id: str
    group_text: str | None
    private_text: str | None
    audience: Literal["regular", "group_admin", "superuser"] = "regular"


DEFAULT_POKE_HINTS: tuple[PokeHint, ...] = (
    PokeHint(
        "seer_player",
        "seer_query",
        "发送“米米号123456”查询玩家信息。",
        "发送“米米号123456”查询玩家信息。",
    ),
    PokeHint(
        "pet_config",
        "pet_config",
        "发送“精灵名配置”获取配置图。",
        "发送“精灵名配置”获取配置图。",
    ),
    PokeHint(
        "server_status_query",
        "server_status",
        "发送“开服了吗”查询维护状态。",
        "发送“开服了吗”查询维护状态。",
    ),
    PokeHint(
        "seer_activity_query",
        "activity",
        "发送“当前活动”查询活动。",
        "发送“当前活动”查询活动。",
    ),
    PokeHint(
        "bili_query",
        "bilibili",
        "发送“动态”查看订阅动态。",
        "发送“动态”查看订阅动态。",
    ),
    PokeHint(
        "team_resource_subscription",
        "team_resource",
        "发送“战队”查看本群战队订阅。",
        None,
    ),
)
POKE_HINT_HELP_SUFFIX = "发送“帮助”可查看全部指令。"


def is_poke_at_bot(event: PokeLikeEvent) -> bool:
    return event.target_id == event.self_id


def _get_poke_reply(
    target_id: int | None,
    *,
    aliases: Mapping[str, int],
    replies: Mapping[str, str],
) -> str | None:
    if target_id is None:
        return None

    for raw_target, message in replies.items():
        resolved_target = aliases.get(raw_target)
        if resolved_target is None and raw_target.isdigit():
            resolved_target = int(raw_target)
        if resolved_target == target_id:
            return message
    return None


@dataclass(slots=True)
class HelpHintService:
    config: HelpConfig
    group_aliases: Mapping[str, int]
    user_aliases: Mapping[str, int]
    features: HintFeaturePolicy | None = None
    chooser: Callable[[Sequence[str]], str] = choice
    limiter: SlidingWindowRateLimiter = field(
        default_factory=SlidingWindowRateLimiter
    )

    def get_poke_reply(self, *, group_id: int | None, user_id: int) -> str | None:
        return _get_poke_reply(
            user_id,
            aliases=self.user_aliases,
            replies=self.config.poke_user_replies,
        ) or _get_poke_reply(
            group_id,
            aliases=self.group_aliases,
            replies=self.config.poke_replies,
        )

    def get_default_poke_hint(
        self,
        *,
        group_id: int | None,
        user_id: int,
    ) -> str | None:
        if self.features is None:
            return None
        visible = [
            text
            for hint in DEFAULT_POKE_HINTS
            if hint.audience == "regular"
            if hint.plugin_id not in self.config.ignored_plugins
            if (
                text := hint.group_text if group_id is not None else hint.private_text
            ) is not None
            if self._feature_is_visible(
                feature=hint.feature,
                group_id=group_id,
                user_id=user_id,
            )
        ]
        if not visible:
            return None
        return f"{self.chooser(visible)}\n{POKE_HINT_HELP_SUFFIX}"

    def _feature_is_visible(
        self,
        *,
        feature: str,
        group_id: int | None,
        user_id: int,
    ) -> bool:
        if self.features is None:
            return False
        if group_id is not None:
            return self.features.is_group_feature_allowed(
                user_id,
                group_id,
                feature,
            )
        return self.features.is_private_feature_allowed(user_id, feature)

    def can_send(self, group_id: int | None, *, now: float | None = None) -> bool:
        if group_id is None:
            return True
        return (
            self.limiter.hit(
                "help_hint",
                group_id,
                window_seconds=self.config.hint_window_seconds,
                max_events=self.config.hint_max_per_window,
                now=now,
            )
            >= 0
        )
