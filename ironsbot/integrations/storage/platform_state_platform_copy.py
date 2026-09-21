# SPDX-License-Identifier: MIT
"""Copy account-scoped platform state into principal-owned tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.platform_state_copy import PlatformStateDataError
from ironsbot.integrations.storage.platform_state_copy_helpers import (
    copy_rows_when_current,
    state_rows,
)
from ironsbot.services.identity_principals import (
    default_actor_principal,
    default_conversation_principal,
)

if TYPE_CHECKING:
    import sqlite3


def copy_platform_player_bindings(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    for row in state_rows(source, "player_bindings"):
        if "principal_kind" in row:
            target.execute(
                "INSERT INTO player_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
            continue
        actor = platform_actor_from_row(row, qq_official_account_id)
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


def copy_platform_player_query_usage(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    for row in state_rows(source, "player_query_usage"):
        if "principal_kind" in row:
            target.execute(
                "INSERT INTO player_query_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )
            continue
        principal = default_actor_principal(
            platform_actor_from_row(row, qq_official_account_id)
        )
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


def copy_platform_lucky_skin_preferences(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    for row in state_rows(source, "lucky_skin_watch_preferences"):
        if "principal_kind" in row:
            target.execute(
                "INSERT INTO lucky_skin_watch_preferences VALUES (?, ?, ?, ?, ?)",
                tuple(row),
            )
            continue
        principal = default_actor_principal(
            platform_actor_from_row(row, qq_official_account_id)
        )
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


def copy_platform_conversation_preferences(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
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
    for table, value_columns in table_columns.items():
        if copy_rows_when_current(source, target, table):
            continue
        placeholders = ", ".join("?" for _ in range(6 + len(value_columns)))
        for row in state_rows(source, table):
            conversation = platform_conversation_from_row(
                row,
                qq_official_account_id,
                location=table,
            )
            principal = default_conversation_principal(conversation)
            target.execute(
                f"INSERT INTO {table} VALUES ({placeholders})",
                (
                    principal.kind,
                    principal.id,
                    *ConversationIdentityColumns.from_conversation(
                        conversation
                    ).values(),
                    *(row[column] for column in value_columns),
                ),
            )


def copy_platform_rank_display_limits(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "group_rank_display_limits"
    if copy_rows_when_current(source, target, table):
        return
    for row in state_rows(source, table):
        conversation = platform_conversation_from_row(
            row,
            qq_official_account_id,
            location=table,
        )
        principal = default_conversation_principal(conversation)
        updated_by = platform_actor_from_prefixed_row(
            row,
            "updated_by",
            qq_official_account_id,
            location=table,
        )
        target.execute(
            "INSERT INTO group_rank_display_limits VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                *ConversationIdentityColumns.from_conversation(conversation).values(),
                row["display_limit"],
                row["updated_at"],
                *ActorIdentityColumns.from_actor(updated_by).values(),
            ),
        )


def copy_platform_team_resources(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    copy_platform_team_subscriptions(
        source,
        target,
        qq_official_account_id=qq_official_account_id,
    )
    copy_platform_team_mentions(
        source,
        target,
        qq_official_account_id=qq_official_account_id,
    )
    copy_platform_team_private_subscriptions(
        source,
        target,
        qq_official_account_id=qq_official_account_id,
    )
    copy_platform_team_prompts(
        source,
        target,
        qq_official_account_id=qq_official_account_id,
    )


def copy_platform_team_subscriptions(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "team_resource_subscriptions"
    if copy_rows_when_current(source, target, table):
        return
    for row in state_rows(source, table):
        conversation = platform_conversation_from_row(
            row,
            qq_official_account_id,
            location=table,
        )
        principal = default_conversation_principal(conversation)
        created_by = platform_actor_from_prefixed_row(
            row,
            "created_by",
            qq_official_account_id,
            location=table,
        )
        updated_by = platform_actor_from_prefixed_row(
            row,
            "updated_by",
            qq_official_account_id,
            location=table,
        )
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


def copy_platform_team_mentions(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "team_resource_subscription_mentions"
    if copy_rows_when_current(source, target, table):
        return
    for row in state_rows(source, table):
        conversation = platform_conversation_from_row(
            row,
            qq_official_account_id,
            location=table,
        )
        principal = default_conversation_principal(conversation)
        actor = platform_actor_from_prefixed_row(
            row,
            "actor",
            qq_official_account_id,
            location=table,
        )
        target.execute(
            "INSERT INTO team_resource_subscription_mentions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.kind,
                principal.id,
                row["team_id"],
                *ActorIdentityColumns.from_actor(actor).values(),
                row["position"],
            ),
        )


def copy_platform_team_private_subscriptions(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "team_resource_private_subscriptions"
    if copy_rows_when_current(source, target, table):
        return
    for row in state_rows(source, table):
        actor = platform_actor_from_prefixed_row(
            row,
            "actor",
            qq_official_account_id,
            location=table,
        )
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


def copy_platform_team_prompts(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    qq_official_account_id: str | None,
) -> None:
    table = "team_resource_subscription_prompts"
    if copy_rows_when_current(source, target, table):
        return
    for row in state_rows(source, table):
        conversation = platform_conversation_from_row(
            row,
            qq_official_account_id,
            location=table,
        )
        principal = default_conversation_principal(conversation)
        prompted_by = platform_actor_from_prefixed_row(
            row,
            "prompted_by",
            qq_official_account_id,
            location=table,
        )
        handled_by = _optionalplatform_actor_from_prefixed_row(
            row,
            "handled_by",
            qq_official_account_id,
            location=table,
        )
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
                *ActorIdentityColumns.from_actor(prompted_by).values(),
                row["prompted_at"],
                *handled_by,
                row["handled_at"],
                row["accepted"],
                updated_at,
            ),
        )


def platform_actor_from_row(
    row: sqlite3.Row,
    qq_official_account_id: str | None,
) -> ActorRef:
    platform = str(row["actor_platform"])
    account_id = (
        str(row["actor_account_id"])
        if "actor_account_id" in row
        else (
            qq_official_account_id or ""
            if platform == Platform.QQ_OFFICIAL.value
            else ""
        )
    )
    return ActorIdentityColumns(
        platform,
        account_id,
        str(row["actor_kind"]),
        str(row["actor_id"]),
        str(row["actor_scope_id"]),
    ).to_actor()


def platform_conversation_from_row(
    row: sqlite3.Row,
    qq_official_account_id: str | None,
    *,
    location: str,
) -> ConversationRef:
    platform = str(row["conversation_platform"])
    account_id = platform_account_id(
        row,
        "conversation",
        platform,
        qq_official_account_id,
        location=location,
    )
    return ConversationIdentityColumns(
        platform,
        account_id,
        str(row["conversation_kind"]),
        str(row["conversation_id"]),
    ).to_conversation()


def platform_actor_from_prefixed_row(
    row: sqlite3.Row,
    prefix: str,
    qq_official_account_id: str | None,
    *,
    location: str,
) -> ActorRef:
    platform = str(row[f"{prefix}_platform"])
    account_id = platform_account_id(
        row,
        prefix,
        platform,
        qq_official_account_id,
        location=location,
    )
    return ActorIdentityColumns(
        platform,
        account_id,
        str(row[f"{prefix}_kind"]),
        str(row[f"{prefix}_id"]),
        str(row[f"{prefix}_scope_id"]),
    ).to_actor()


def _optionalplatform_actor_from_prefixed_row(
    row: sqlite3.Row,
    prefix: str,
    qq_official_account_id: str | None,
    *,
    location: str,
) -> tuple[str | None, ...]:
    if row[f"{prefix}_platform"] is None:
        return (None, None, None, None, None)
    actor = platform_actor_from_prefixed_row(
        row,
        prefix,
        qq_official_account_id,
        location=location,
    )
    return ActorIdentityColumns.from_actor(actor).values()


def platform_account_id(
    row: sqlite3.Row,
    prefix: str,
    platform: str,
    qq_official_account_id: str | None,
    *,
    location: str,
) -> str:
    column = f"{prefix}_account_id"
    if column in row and row[column] not in {None, ""}:
        return str(row[column])
    if platform != Platform.QQ_OFFICIAL.value:
        return ""
    account_id = str(qq_official_account_id or "").strip()
    if not account_id:
        raise PlatformStateDataError.missing_qq_official_account_id(
            f"{location}.{column}"
        )
    return account_id
