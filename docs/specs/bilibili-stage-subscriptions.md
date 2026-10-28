# Bilibili Stage Subscriptions

## Target Contract

TD exposes three conversation-wide gates and one submenu per configured account.
Each account has independent notification (`link`), body (`text`), and image
switches. Only category-configured accounts append category choices. Notification
switches require a superuser at mutation time; media and category switches retain
the existing conversation-management policy. Both transports use the public TD
operation. Submenus return one level with zero; the root exits.

The keys are `bili_all:<stage>` and `bili_media:<uid>:<stage>`. Effective delivery
requires both gates, existing target eligibility, push mode and category policy.
Conversation-wide gates never overwrite account preferences. Link mode never
gains body or image delivery. Notification opt-out does not suppress other stages.

## Migration and Recovery

Startup atomically snapshots legacy Bilibili opt-outs into
`bili_subscription_legacy`, expands account-wide opt-outs into all three stages,
and discards previously ignored ordinary-account media opt-outs from live state.
The migration marker prevents later starts from resetting new choices. Existing
category-account media and category choices are preserved. No production database
is edited manually. Rollback requires the previous database snapshot and code.

Initial sends and every retry check the same stage gates. Disabled safe unfinished
units become terminally skipped; successful and uncertain units are not reset.
Re-enabling a gate does not replay skipped history. Each target retains its own
receipt and each image retains its own durable unit. No TOML option is added.

## Acceptance

Tests cover all stage combinations, independent gates, link mode, both platform
identities, mutation-time permission checks, submenu navigation, migration
idempotence, pruning, restart recovery and cancellation of safe unfinished units.
Production configuration and deployment are outside this change.
