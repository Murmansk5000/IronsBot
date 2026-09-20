# Portable Maintenance Commands

## Goal

Administrative maintenance must preserve the existing service behavior while obeying
the reply deadline and delivery guarantees of every transport. Long checks and writes
must not begin before the user receives an acknowledgement.

## Data Synchronization

- `/更新数据` and `/强制更新数据` report that the remote check is starting before
  `check_all_databases()` runs.
- The completed check is presented through `PortableQuerySessions` using the same
  options produced by `DataSyncService`.
- A selected action reports its own start message before any upstream build or
  database download begins.
- Both stages use `progress_operation_reply()`. Failed initial delivery cancels the
  corresponding work.
- OneBot and QQ Official call the same progress-aware service methods.

Portable numeric menus may return either a plain `OutboundMessage` or a
`PortableReply`. This is a generic session capability, not a data-sync special case.

## Docker Image Check

`/检查更新镜像` reports progress before contacting the registry and returns the
existing formatted result as its follow-up. It remains read-only: it does not pull an
image or restart a process or container.

## Deferred Commands

`/重启机器人` and `/更新镜像` remain outside portable execution in this increment.
They require a separate asynchronous delivery-commit contract: the final prepared
message must be confirmed delivered before the service executes a restart that may
terminate the current process. They must not be implemented by starting an untracked
task or by sending a fake final reply.

## Footprint

This increment adds no runtime dependency, database, configuration field, binary
asset, or image layer.
