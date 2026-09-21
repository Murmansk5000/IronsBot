# SPDX-License-Identifier: MIT
"""Convert legacy OneBot-owned state into principal-owned tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.platform_state_copy_helpers import (
    legacy_conversation,
    legacy_user_ids,
    onebot_actor,
    onebot_group,
    optional_onebot_actor,
    state_rows,
)
from ironsbot.services.identity_principals import (
    default_actor_principal,
    default_conversation_principal,
)

if TYPE_CHECKING:
    import sqlite3

    from ironsbot.core.platform import ConversationRef


def copy_legacy_player_bindings(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in state_rows(source, "player_bindings"):
        actor = onebot_actor(row["qq_user_id"], "player_bindings")
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO player_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["player_id"],
                row["player_nick"],
                row["choice_completed"],
                row["last_changed_at"],
                row["created_at"],
                row["updated_at"],
            ),
        )


def copy_legacy_player_query_usage(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in state_rows(source, "player_query_usage"):
        actor = onebot_actor(row["qq_user_id"], "player_query_usage")
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO player_query_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["local_date"],
                principal.kind,
                principal.id,
                row["scope"],
                row["player_id"],
                row["action_key"],
                row["usage_count"],
                row["updated_at"],
            ),
        )


def copy_legacy_lucky_skin_preferences(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in state_rows(source, "lucky_skin_watch_preferences"):
        actor = onebot_actor(row["qq_user_id"], "lucky_skin_watch_preferences")
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO lucky_skin_watch_preferences VALUES (?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["skin_ids_json"],
                row["initialized_at"],
                row["updated_at"],
            ),
        )


def copy_legacy_conversation_preferences(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    table_columns = {
        "push_unsubscriptions": ("subscription_key", "feature", "created_at"),
        "push_time_preferences": (
            "subscription_key",
            "preference_type",
            "value",
            "updated_at",
        ),
        "push_daily_hints": ("hint_key", "delivered_on", "updated_at"),
        "bili_push_preferences": ("uid", "mode", "updated_at"),
        "bili_push_category_preferences": (
            "uid",
            "category",
            "muted",
            "updated_at",
        ),
    }
    principal_owned = {
        "bili_push_category_preferences",
        "bili_push_preferences",
        "push_unsubscriptions",
        "push_time_preferences",
        "push_daily_hints",
    }
    for table, columns in table_columns.items():
        owner_column_count = 2 if table in principal_owned else 0
        placeholders = ", ".join(
            "?" for _ in range(owner_column_count + 4 + len(columns))
        )
        for row in state_rows(source, table):
            conversation = legacy_conversation(
                row["target_type"],
                row["target_id"],
                table,
            )
            owner = default_conversation_principal(conversation)
            target.execute(
                f"INSERT INTO {table} VALUES ({placeholders})",
                (
                    *((owner.kind, owner.id) if table in principal_owned else ()),
                    *ConversationIdentityColumns.from_conversation(
                        conversation
                    ).values(),
                    *(row[column] for column in columns),
                ),
            )


def copy_legacy_rank_display_limits(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in state_rows(source, "group_rank_display_limits"):
        conversation = onebot_group(row["group_id"], "group_rank_display_limits")
        principal = default_conversation_principal(conversation)
        actor = onebot_actor(row["updated_by"], "group_rank_display_limits")
        target.execute(
            "INSERT INTO group_rank_display_limits VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["display_limit"],
                row["updated_at"],
                *ActorIdentityColumns.from_actor(actor).values(),
            ),
        )


def copy_legacy_team_resources(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in state_rows(source, "team_resource_subscriptions"):
        conversation = onebot_group(row["group_id"], "team_resource_subscriptions")
        principal = default_conversation_principal(conversation)
        created_by = onebot_actor(row["created_by"], "team_resource_subscriptions")
        updated_by = onebot_actor(row["updated_by"], "team_resource_subscriptions")
        target.execute(
            "INSERT INTO team_resource_subscriptions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["team_id"],
                row["team_name"],
                row["threshold"],
                *ActorIdentityColumns.from_actor(created_by).values(),
                *ActorIdentityColumns.from_actor(updated_by).values(),
                row["created_at"],
                row["updated_at"],
            ),
        )
        copy_legacy_team_mentions(target, conversation, row)
    for row in state_rows(source, "team_resource_private_subscriptions"):
        actor = onebot_actor(row["user_id"], "team_resource_private_subscriptions")
        principal = default_actor_principal(actor)
        target.execute(
            "INSERT INTO team_resource_private_subscriptions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ActorIdentityColumns.from_actor(actor).values(),
                row["team_id"],
                row["team_name"],
                row["threshold"],
                row["created_at"],
                row["updated_at"],
            ),
        )
    copy_legacy_team_prompts(source, target)


def copy_legacy_team_mentions(
    target: sqlite3.Connection,
    conversation: ConversationRef,
    row: sqlite3.Row,
) -> None:
    principal = default_conversation_principal(conversation)
    for position, user_id in enumerate(legacy_user_ids(row["at_user_ids"])):
        actor = onebot_actor(user_id, "team_resource_subscriptions.at_user_ids")
        target.execute(
            "INSERT INTO team_resource_subscription_mentions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["team_id"],
                *ActorIdentityColumns.from_actor(actor).values(),
                position,
            ),
        )


def copy_legacy_team_prompts(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
) -> None:
    for row in state_rows(source, "team_resource_subscription_prompts"):
        conversation = onebot_group(
            row["group_id"],
            "team_resource_subscription_prompts",
        )
        prompted = onebot_actor(
            row["prompted_by"],
            "team_resource_subscription_prompts",
        )
        handled = optional_onebot_actor(
            row["handled_by"],
            "team_resource_subscription_prompts",
        )
        principal = default_conversation_principal(conversation)
        updated_at = row["handled_at"] or row["prompted_at"]
        target.execute(
            "INSERT INTO team_resource_subscription_prompts VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["team_id"],
                row["team_name"],
                *ActorIdentityColumns.from_actor(prompted).values(),
                row["prompted_at"],
                *handled,
                row["handled_at"],
                row["accepted"],
                updated_at,
            ),
        )
