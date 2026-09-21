# SPDX-License-Identifier: MIT
from __future__ import annotations

import sqlite3
from datetime import date
from typing import TYPE_CHECKING

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    OfficialUnionIdentity,
    Platform,
)
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
from ironsbot.services.identity_link_store import (
    CrossPlatformGroupLink,
    OfficialIdentity,
)
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.team.resource_subscriptions import (
    TeamResourcePrivateSubscriptionUpdate,
    TeamResourceSubscriptionUpdate,
)

if TYPE_CHECKING:
    from pathlib import Path

_PLAYER_A = 100001
_PLAYER_B = 100002
_RANK_LIMIT_A = 10
_RANK_LIMIT_B = 20
_TEAM_THRESHOLD_A = 1000
_TEAM_THRESHOLD_B = 2000


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
    principals = IdentityPrincipalService()
    bindings = SqlitePlayerBindingStore(
        path,
        principal_for=principals.actor_principal,
    )
    bindings.bind(actor=onebot_actor, player_id=_PLAYER_A, player_nick="A")
    for merge in principals.register_official_link(
        onebot_qq_id="10001",
        official=OfficialIdentity("app-id", "member", "member-openid"),
    ):
        bindings.merge_principals(merge.source, merge.target)

    assert bindings.get(official_actor).player_id == _PLAYER_A
    bindings.bind(actor=official_actor, player_id=_PLAYER_B, player_nick="B")
    assert bindings.get(onebot_actor).player_id == _PLAYER_B


def test_player_binding_is_shared_by_union_principal_across_apps(
    tmp_path: Path,
) -> None:
    principals = IdentityPrincipalService()
    bindings = SqlitePlayerBindingStore(
        tmp_path / "qq_state.sqlite",
        principal_for=principals.actor_principal,
    )
    actor_a = _actor("app-a")
    actor_b = _actor("app-b")
    bindings.bind(actor=actor_a, player_id=_PLAYER_A, player_nick="shared")

    for actor in (actor_a, actor_b):
        for merge in principals.observe_union_identity(
            actor=actor,
            evidence=OfficialUnionIdentity("shared-union"),
        ):
            bindings.merge_principals(merge.source, merge.target)

    assert bindings.get(actor_b).player_id == _PLAYER_A


def test_actor_preferences_and_quotas_are_shared_by_union_principal(
    tmp_path: Path,
) -> None:
    principals = IdentityPrincipalService()
    watches = SqliteLuckySkinWatchPreferenceStore(
        tmp_path / "qq_state.sqlite",
        principal_for=principals.actor_principal,
    )
    quotas = SqlitePlayerQueryLimitStore(
        tmp_path / "qq_state.sqlite",
        principal_for=principals.actor_principal,
    )
    actor_a = _actor("app-a")
    actor_b = _actor("app-b")
    watches.set(actor_a, (1400001,))
    quotas.consume(
        local_date=date(2026, 9, 22),
        actor=actor_a,
        scope="unbound",
        player_id=_PLAYER_A,
        action_key="profile",
        limit=3,
    )

    for actor in (actor_a, actor_b):
        for merge in principals.observe_union_identity(
            actor=actor,
            evidence=OfficialUnionIdentity("shared-union"),
        ):
            watches.merge_principals(merge.source, merge.target)
            quotas.merge_principals(merge.source, merge.target)

    assert watches.get(actor_b) == (1400001,)
    assert quotas.status(
        local_date=date(2026, 9, 22),
        actor=actor_b,
        scope="unbound",
        player_id=_PLAYER_A,
        action_key="profile",
        limit=3,
    ).used_count == 1


def _link_binding_principals(
    bindings: SqlitePlayerBindingStore,
    principals: IdentityPrincipalService,
) -> None:
    for merge in principals.register_official_link(
        onebot_qq_id="10001",
        official=OfficialIdentity("app-id", "member", "member-openid"),
    ):
        bindings.merge_principals(merge.source, merge.target)


def test_identity_link_reuses_legacy_binding_and_removes_duplicate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "qq_state.sqlite"
    onebot_actor = ActorRef(Platform.ONEBOT, "10001")
    official_actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        "member",
        "group-openid",
        account_id="app-id",
    )
    principals = IdentityPrincipalService()
    bindings = SqlitePlayerBindingStore(
        path,
        principal_for=principals.actor_principal,
    )
    bindings.bind(actor=onebot_actor, player_id=_PLAYER_A, player_nick="legacy")
    bindings.bind(actor=official_actor, player_id=_PLAYER_B, player_nick="duplicate")

    _link_binding_principals(bindings, principals)

    assert bindings.get(onebot_actor).player_id == _PLAYER_A
    assert SqlitePlayerBindingStore(path).get(official_actor).player_id is None


def test_identity_link_preserves_official_rebinding_when_legacy_is_missing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "qq_state.sqlite"
    onebot_actor = ActorRef(Platform.ONEBOT, "10001")
    official_actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        "member",
        "group-openid",
        account_id="app-id",
    )
    principals = IdentityPrincipalService()
    bindings = SqlitePlayerBindingStore(
        path,
        principal_for=principals.actor_principal,
    )
    bindings.bind(actor=official_actor, player_id=_PLAYER_B, player_nick="official")

    _link_binding_principals(bindings, principals)

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


def test_team_resource_group_state_merges_by_latest_complete_record(
    tmp_path: Path,
) -> None:
    path = tmp_path / "qq_state.sqlite"
    principals = IdentityPrincipalService()
    store = TeamResourceSubscriptionStore(
        path,
        conversation_principal_for=principals.conversation_principal,
    )
    actor_a = _actor("app-a")
    actor_b = _actor("app-b")
    group_a = _group("app-a")
    group_b = _group("app-b")
    store.upsert(
        TeamResourceSubscriptionUpdate(
            group_a,
            3001,
            "A",
            _TEAM_THRESHOLD_A,
            (actor_a,),
            actor_a,
        )
    )
    store.mark_conversation_prompted(
        conversation=group_a,
        team_id=3001,
        team_name="A",
        prompted_by=actor_a,
    )
    store.upsert(
        TeamResourceSubscriptionUpdate(
            group_b,
            3001,
            "B",
            _TEAM_THRESHOLD_B,
            (actor_b,),
            actor_b,
        )
    )
    store.mark_conversation_prompted(
        conversation=group_b,
        team_id=3001,
        team_name="B",
        prompted_by=actor_b,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE team_resource_subscriptions SET updated_at = ? "
            "WHERE conversation_account_id = ? AND conversation_id = ?",
            ("2026-09-21T00:00:00+00:00", group_a.account_id, group_a.id),
        )
        connection.execute(
            "UPDATE team_resource_subscriptions SET updated_at = ? "
            "WHERE conversation_account_id = ? AND conversation_id = ?",
            ("2026-09-22T00:00:00+00:00", group_b.account_id, group_b.id),
        )
        connection.execute(
            "UPDATE team_resource_subscription_prompts SET updated_at = ? "
            "WHERE conversation_account_id = ? AND conversation_id = ?",
            ("2026-09-21T00:00:00+00:00", group_a.account_id, group_a.id),
        )
        connection.execute(
            "UPDATE team_resource_subscription_prompts SET updated_at = ? "
            "WHERE conversation_account_id = ? AND conversation_id = ?",
            ("2026-09-22T00:00:00+00:00", group_b.account_id, group_b.id),
        )

    for link in (
        CrossPlatformGroupLink("686376929", "app-a", group_a.id, 1.0),
        CrossPlatformGroupLink("686376929", "app-b", group_b.id, 2.0),
    ):
        for merge in principals.register_group_link(link):
            store.merge_conversation_principals(merge.source, merge.target)

    merged = store.list_conversation(group_a)
    assert len(merged) == 1
    assert merged[0].team_name == "B"
    assert merged[0].threshold == _TEAM_THRESHOLD_B
    assert merged[0].mention_actors == (actor_b,)
    prompt = store.get_pending_prompt(group_b)
    assert prompt is not None
    assert prompt.team_name == "B"
    assert prompt.prompted_by == actor_b
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM team_resource_subscriptions"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM team_resource_subscription_mentions"
        ).fetchone() == (1,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_team_resource_private_state_merges_by_actor_principal(tmp_path: Path) -> None:
    path = tmp_path / "qq_state.sqlite"
    principals = IdentityPrincipalService()
    store = TeamResourceSubscriptionStore(
        path,
        actor_principal_for=principals.actor_principal,
    )
    actor_a = _actor("app-a")
    actor_b = _actor("app-b")
    store.upsert_private(
        TeamResourcePrivateSubscriptionUpdate(
            actor_a,
            3001,
            "A",
            _TEAM_THRESHOLD_A,
        )
    )
    store.upsert_private(
        TeamResourcePrivateSubscriptionUpdate(
            actor_b,
            3001,
            "B",
            _TEAM_THRESHOLD_B,
        )
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE team_resource_private_subscriptions SET updated_at = ? "
            "WHERE actor_account_id = ?",
            ("2026-09-21T00:00:00+00:00", "app-a"),
        )
        connection.execute(
            "UPDATE team_resource_private_subscriptions SET updated_at = ? "
            "WHERE actor_account_id = ?",
            ("2026-09-22T00:00:00+00:00", "app-b"),
        )

    for actor in (actor_a, actor_b):
        for merge in principals.observe_union_identity(
            actor=actor,
            evidence=OfficialUnionIdentity("shared-team-user"),
        ):
            store.merge_actor_principals(merge.source, merge.target)

    merged = store.list_actor(actor_a)
    assert len(merged) == 1
    assert merged[0].team_name == "B"
    assert merged[0].threshold == _TEAM_THRESHOLD_B
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM team_resource_private_subscriptions"
        ).fetchone() == (1,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
