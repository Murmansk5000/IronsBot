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

## Restarting Commands

`/重启机器人` and `/更新镜像` open the shared maintenance menu on both transports.
The image update path acknowledges the selection before contacting the registry or
pulling an image. Its prepared final reply is itself delivery-aware: the process or
container restart runs only after the transport confirms that final reply.

`PortableReply.follow_up` may return another `PortableReply`. Transports commit each
stage independently and stop the chain after a failed delivery. Asynchronous
delivery commits are generic lifecycle hooks rather than Docker-specific transport
branches; no untracked restart task is created.

## Footprint

This increment adds no runtime dependency, database, configuration field, binary
asset, or image layer. Portable command coverage is 69/75; the remaining six
commands depend on numeric QQ-account configuration used by the lucky skin window.
