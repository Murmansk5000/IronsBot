# Platform State Identity Migration Target

This document specifies the later one-time platform-identity migration. At this snapshot the platform migration module and its CLI entry are absent; current state repositories still use OneBot integer identities. The target column and conversion rules below are not the currently installed schema.

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
| comma-separated `at_user_ids` | validated sequence of OneBot user actors in the normalized `team_resource_subscription_mentions` relation |
| team audit `(group_id, user_id)` | group conversation plus `ActorRef(Platform.ONEBOT, str(user_id), kind='member', scope_id=str(group_id))` |

Malformed integers, unknown `target_type` values, invalid JSON, duplicate target
keys, and missing required timestamps are migration errors. The tool must list
the offending source table and primary key; it must not silently discard,
coerce, or merge them.

## Available Offline Tool at This Snapshot

The existing ironsbot.state_migration module only consolidates the legacy state files.
Its supported options are --data-root, --qq-state, --runtime-state, --backup-root
and --apply. It does not accept --platform-identities or --ai-memory, and does
not create the platform-qualified identities specified above.

There is no platform-identity dry-run/apply procedure to execute for this snapshot.
The executable commands and identity-migration runbook belong at the later node
that introduces both the migration module and the application readers. Do not
run a later command against this snapshot or treat legacy consolidation as an
identity migration. Current startup never performs either migration implicitly.
