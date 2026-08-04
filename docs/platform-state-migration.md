# Platform State Migration

This document is the implementation contract for the one-time migration from
OneBot-only integer identifiers to platform-neutral state identities. It is
written before the executable migration so each source column, target column,
and ownership boundary is reviewable. The migration command remains dry-run by
default and must never be invoked by normal application startup.

## Identity Columns

Actor-owned state uses four independent columns:

```text
actor_platform     TEXT NOT NULL
actor_kind         TEXT NOT NULL
actor_id           TEXT NOT NULL
actor_scope_id     TEXT NOT NULL DEFAULT ''
```

Conversation-owned state uses three independent columns:

```text
conversation_platform  TEXT NOT NULL
conversation_kind      TEXT NOT NULL
conversation_id        TEXT NOT NULL
```

An empty `actor_scope_id` is the stored representation of `ActorRef.scope_id`
being absent. It is not a reversible composite identifier. A future QQ Official
member actor uses `actor_kind = 'member'` and its group OpenID in
`actor_scope_id`; a OneBot QQ account uses `actor_platform = 'onebot'`,
`actor_kind = 'user'`, and the decimal QQ number as `actor_id`.

The application will only read these target columns after the migration. Old
integer identity columns and their readers must be removed in the same change.

## Current Table Mapping

| Database | Source table | Old identity | Target identity | Target table ownership |
| --- | --- | --- | --- | --- |
| `state/qq_state.sqlite` | `player_bindings` | `qq_user_id` | actor | Player binding |
| `state/qq_state.sqlite` | `player_query_usage` | `qq_user_id` | actor | Player live-query quota |
| `state/qq_state.sqlite` | `lucky_skin_watch_preferences` | `qq_user_id` | actor | Lucky-window preferences |
| `state/qq_state.sqlite` | `push_unsubscriptions` | `target_type`, `target_id` | conversation | Scheduled push preferences |
| `state/qq_state.sqlite` | `push_time_preferences` | `target_type`, `target_id` | conversation | Scheduled push preferences |
| `state/qq_state.sqlite` | `push_daily_hints` | `target_type`, `target_id` | conversation | Scheduled push preferences |
| `state/qq_state.sqlite` | `bili_push_preferences` | `target_type`, `target_id` | conversation | Bilibili delivery preferences |
| `state/qq_state.sqlite` | `group_rank_display_limits` | `group_id`, `updated_by` | conversation, actor | Group rank display policy |
| `state/qq_state.sqlite` | `team_resource_subscriptions` | `group_id`, `created_by`, `updated_by`, `at_user_ids` | conversation, actors | Team resource subscriptions |
| `state/qq_state.sqlite` | `team_resource_subscription_prompts` | `group_id`, `prompted_by`, `handled_by` | conversation, actors | Team resource confirmation prompt |
| `state/qq_state.sqlite` | `team_resource_private_subscriptions` | `user_id` | actor | Private team subscriptions |
| `state/runtime_state.sqlite` | `pending_team_audit_reminders` | `group_id`, `user_id` | conversation, scoped member actor | Team audit follow-up |
| AI memory database | `messages` | `user_id`, `chat_scope`, `chat_id` | actor, conversation | AI history |

`sent_activity_reminders` contains no platform identity and remains unchanged.
Large Seer caches remain outside this migration because their keys are Seer
player IDs, rankings, or payload hashes rather than delivery-platform
identities.

## Legacy Conversion Rules

| Old field | Target conversion |
| --- | --- |
| QQ `user_id` / `qq_user_id` / `created_by` / `updated_by` | `ActorRef(Platform.ONEBOT, str(value), kind='user')` |
| QQ `group_id` | `ConversationRef(Platform.ONEBOT, 'group', str(value))` |
| private `target_type='private'`, `target_id` | `ConversationRef(Platform.ONEBOT, 'private', str(target_id))` |
| group `target_type='group'`, `target_id` | `ConversationRef(Platform.ONEBOT, 'group', str(target_id))` |
| comma-separated `at_user_ids` | validated sequence of OneBot user actors, stored as structured JSON actor records rather than integer CSV |
| team audit `(group_id, user_id)` | group conversation plus `ActorRef(Platform.ONEBOT, str(user_id), kind='member', scope_id=str(group_id))` |

Malformed integers, unknown `target_type` values, invalid JSON, duplicate target
keys, and missing required timestamps are migration errors. The tool must list
the offending source table and primary key; it must not silently discard,
coerce, or merge them.

## Required Migration Procedure

1. Stop the container and copy the entire data directory at the filesystem
   level. The migration tool makes an additional timestamped backup itself.
2. Run the migration command without `--apply`. It validates every source row,
   shows source/target counts, and writes nothing.
3. Run it with `--apply`. It creates temporary target database files, copies
   all rows inside transactions, verifies row counts, key uniqueness, foreign
   keys, and `PRAGMA integrity_check`, then atomically replaces the targets.
4. Keep the timestamped backup for seven days. Restart only after the new
   application version confirms the target schema.
5. Re-running the tool after success must report that the database is already
   migrated and must not duplicate rows or change timestamps.

The executable command will be added with the storage implementation. Until
then, no production data must be migrated manually by SQL snippets.
