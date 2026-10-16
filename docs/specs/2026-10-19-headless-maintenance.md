# Headless maintenance packet boundary

Status: `implementing`

Contract: `target`

Owner: headless integration and operations notification service

## Evidence and behavior

Upstream `9f1d3b93` registers command 41457, but its signed read and timestamp
threshold are superseded by independent client implementation evidence at
`QianChang927/SeerDatabase`, commit
`976ce5bff85ab82aa16a94781cdce731d1e8e376`:

- [ServerCloseNoticeController.as](https://github.com/QianChang927/SeerDatabase/blob/976ce5bff85ab82aa16a94781cdce731d1e8e376/Flash/RobotAppDLL/com/robot/app/control/ServerCloseNoticeController.as)
  registers 41457, reads `readUnsignedInt()` and computes remaining minutes
  relative to `SystemTimerManager.time`.
- [SystemTimerManager.as](https://github.com/QianChang927/SeerDatabase/blob/976ce5bff85ab82aa16a94781cdce731d1e8e376/Flash/RobotCoreDLL/com/robot/core/manager/SystemTimerManager.as)
  exposes uint seconds, creates dates using seconds multiplied by 1000 and
  advances the clock by elapsed milliseconds divided by 1000.

The integration accepts exactly one network-order unsigned four-byte integer
(`!I`), preserves the raw value and converts Unix seconds to an aware UTC date
through an explicit typed callback. No speculative future horizon is imposed.
Unsupported
payloads, observer failures and notification failures do not disconnect the game
client. Tasks belong to the existing application task owner.

The operations boundary can deliver a verified, timezone-aware future deadline
through the existing admin notice sender and `headless_seer_notice` subscription.
It deduplicates equal deadlines across workers in this service and permits
changed deadlines. Zero, expired and naive dates do not notify. Existing
notification opt-outs and routing remain owned by the established sender.

## Verification

- Decoder tests cover truncated/extended payloads and the full unsigned integer
  range, including values above 2^31, interpreted as UTC Unix seconds.
- Service tests use explicitly synthetic dates to verify Shanghai formatting,
  concurrency, corrected times, opt-out and delivery failure isolation.
- Client tests verify event registration, task ownership and observer isolation.
- A generated protocol-shaped fixture exercises the real packet handler,
  service and admin-notice sender together; it is not a live packet capture.

## Remaining acceptance gate

Protocol meaning is confirmed by the fixed client source above. Actual server
maintenance reception and delivery remain a live acceptance item. Generated
fixtures prove the implementation path, not a captured production event.

## Announcement and login readiness

Following the accepted upstream behavior (e702bccd), login no longer requests
the maintenance announcement or treats its presence as a reason to stop login.
Readiness comes from the actual authentication and game connection outcome.
Announcements remain available through ServerStatusService for open-server
queries, including when an old notice remains after the game has reopened.
Announcement availability does not control 41457 notification delivery.
