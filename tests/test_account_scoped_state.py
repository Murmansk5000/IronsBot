# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.integrations.storage.lucky_skin_watch import (
    SqliteLuckySkinWatchPreferenceStore,
)
from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
from ironsbot.integrations.storage.player_query_limits import (
    SqlitePlayerQueryLimitStore,
)
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.integrations.storage.rank_display import SqliteRankDisplayStore
from ironsbot.integrations.storage.team_resources import TeamResourceSubscriptionStore
from ironsbot.services.team.resource_subscriptions import (
    TeamResourceSubscriptionUpdate,
)

if TYPE_CHECKING:
    from pathlib import Path

_PLAYER_A = 100001
_PLAYER_B = 100002
_RANK_LIMIT_A = 10
_RANK_LIMIT_B = 20


def _actor(account_id: str) -> ActorRef:
    return ActorRef(
        Platform.QQ_OFFICIAL,
        "same-user-openid",
        account_id=account_id,
    )


def _group(account_id: str) -> ConversationRef:
    return ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "same-group-openid",
        account_id=account_id,
    )


def test_actor_state_is_isolated_by_qq_official_account(tmp_path: Path) -> None:
    path = tmp_path / "qq_state.sqlite"
    actor_a = _actor("app-a")
    actor_b = _actor("app-b")
    bindings = SqlitePlayerBindingStore(path)
    watches = SqliteLuckySkinWatchPreferenceStore(path)
    quotas = SqlitePlayerQueryLimitStore(path)

    bindings.bind(actor=actor_a, player_id=_PLAYER_A, player_nick="A")
    bindings.bind(actor=actor_b, player_id=_PLAYER_B, player_nick="B")
    watches.set(actor_a, (1400001,))
    watches.set(actor_b, (1400002,))
    quotas.consume(
        local_date=date(2026, 9, 14),
        actor=actor_a,
        scope="unbound",
        player_id=_PLAYER_A,
        action_key="profile",
        limit=3,
    )

    assert bindings.get(actor_a).player_id == _PLAYER_A
    assert bindings.get(actor_b).player_id == _PLAYER_B
    assert watches.get(actor_a) == (1400001,)
    assert watches.get(actor_b) == (1400002,)
    assert (
        quotas.status(
            local_date=date(2026, 9, 14),
            actor=actor_b,
            scope="unbound",
            player_id=_PLAYER_A,
            action_key="profile",
            limit=3,
        ).used_count
        == 0
    )


def test_player_binding_uses_canonical_cross_platform_actor(tmp_path: Path) -> None:
    path = tmp_path / "qq_state.sqlite"
    onebot_actor = ActorRef(Platform.ONEBOT, "10001")
    official_actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        "member",
        "group-openid",
        account_id="app-id",
    )
    bindings = SqlitePlayerBindingStore(path)
    bindings.bind(actor=onebot_actor, player_id=_PLAYER_A, player_nick="A")
    canonical = SqlitePlayerBindingStore(
        path,
        canonicalize_actor=lambda actor: (
            onebot_actor if actor == official_actor else actor
        ),
    )

    assert canonical.get(official_actor).player_id == _PLAYER_A
    canonical.bind(actor=official_actor, player_id=_PLAYER_B, player_nick="B")
    assert bindings.get(onebot_actor).player_id == _PLAYER_B


def test_conversation_state_is_isolated_by_qq_official_account(
    tmp_path: Path,
) -> None:
    path = tmp_path / "qq_state.sqlite"
    actor_a = _actor("app-a")
    actor_b = _actor("app-b")
    group_a = _group("app-a")
    group_b = _group("app-b")
    ranks = SqliteRankDisplayStore(path)
    pushes = PushUnsubscribeStore(path)
    bilibili = SqliteBiliPushPreferenceStore(path)

    ranks.set(group_a, actor_a, _RANK_LIMIT_A)
    ranks.set(group_b, actor_b, _RANK_LIMIT_B)
    pushes.unsubscribe(group_a, "daily", "example")
    bilibili.set_mode(group_a, 123456, "full")
    bilibili.set_mode(group_b, 123456, "link")

    assert ranks.get(group_a) == _RANK_LIMIT_A
    assert ranks.get(group_b) == _RANK_LIMIT_B
    assert pushes.is_unsubscribed(group_a, "daily")
    assert not pushes.is_unsubscribed(group_b, "daily")
    assert bilibili.get_mode(group_a, 123456) == "full"
    assert bilibili.get_mode(group_b, 123456) == "link"


def test_team_resource_relations_preserve_account_ownership(tmp_path: Path) -> None:
    store = TeamResourceSubscriptionStore(tmp_path / "qq_state.sqlite")
    actor_a = _actor("app-a")
    actor_b = _actor("app-b")
    group_a = _group("app-a")
    group_b = _group("app-b")

    store.upsert(
        TeamResourceSubscriptionUpdate(
            group_a,
            3001,
            "A",
            1000,
            (actor_a,),
            actor_a,
        )
    )
    store.upsert(
        TeamResourceSubscriptionUpdate(
            group_b,
            3001,
            "B",
            2000,
            (actor_b,),
            actor_b,
        )
    )

    subscription_a = store.list_conversation(group_a)[0]
    subscription_b = store.list_conversation(group_b)[0]
    assert subscription_a.team_name == "A"
    assert subscription_a.mention_actors == (actor_a,)
    assert subscription_b.team_name == "B"
    assert subscription_b.mention_actors == (actor_b,)
