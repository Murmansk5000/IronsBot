# Portable Operational Queries

## Status

Implemented on `codex/multiplatform-architecture-v5`.

## Goal

Expose low-risk operational queries through the shared command router without
copying OneBot handlers into the QQ Official adapter.

## Scope

The portable router executes these catalog-owned commands:

- `server_status.query`
- `server_status.admin_query`
- `server_status.headless_instances`
- `meeting`

The command catalog remains authoritative for feature, scope and audience
checks. In particular, administrator status and instance diagnostics remain
restricted to the configured superusers for the receiving bot account.

Data synchronization, image updates, Docker lifecycle commands and rank-cache
maintenance are intentionally excluded. They require progress delivery,
stronger operational authorization or transport-specific recovery semantics.

## Architecture

- `ServerStatusService` owns status inspection and reconnect behavior.
- `build_meeting_reply` owns configured meeting formatting.
- `PortableCommandRouter` only maps authorized catalog IDs to those services.
- Platform adapters only translate inbound and outbound messages.

No SDK-specific token, OpenID or message implementation enters these services.

## Acceptance

- Normal status queries return the shared service result.
- Superuser status and instance queries route to their distinct service calls.
- Meeting replies preserve configured formatting and report missing numbers.
- Commands absent from the loaded catalog are not exposed.
- Existing OneBot behavior remains unchanged.
