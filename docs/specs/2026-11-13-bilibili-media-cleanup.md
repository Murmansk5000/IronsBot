# Bilibili persistent media cleanup

Status: completed (implementation; not deployed)

Contract: baseline lifecycle correction.
Owner: common Bilibili recovery and delivery storage.

## Scope

Retain frozen images for the existing 24-hour delivery window, based on both
delivery creation and publication time. Keep any active sending reference even
after expiry. Shared bytes survive while any valid task references them.
Orphan digests and abandoned .media- files receive a one-hour grace period.

仅清理B站专用delivery_media目录。保留有效或发送中的全部引用；孤儿及崩溃临时
文件至少等待一小时。不删除历史、回执、订阅、数据库或其他缓存，不延长补发窗口。

## Design

- Collect media, text and unit-message references before deleting anything.
  Corrupt manifests abort the sweep. Preserve unknown names, directories and
  links. File deletion failures are counted without breaking delivery.
- Freeze bytes and register references under BEGIN IMMEDIATE; cleanup shares the
  same writer boundary. Do not follow symlinks or recursively traverse paths.
- Reuse application recovery scanning with an hourly monotonic throttle. The
  first startup scan runs cleanup in a worker thread, independently of accounts.
- Return typed summary counts; log summaries and failures without private paths,
  message content or URLs. No new TOML or production maintenance command.

## Acceptance

Cover expiry boundaries, old publication, shared references, sending across expiry,
all snapshot formats, grace periods, restart, idempotence, concurrent freeze,
corruption, filesystem errors and links. Verify receipts/budgets remain intact.
Run targeted/full tests and static gates, archive independently, then fold into
7312c380af's recovery node while preserving upstream objects. Publish and verify
archive/image; do not deploy, restart or manually clean production files.

Verification on 2026-11-13: initial isolated full suite passed 6955 with 11 skips;
Ruff, BasedPyright, compilation, static and diff checks passed. Final manifest
metadata checks passed 21 cleanup tests, with two Windows symlink-capability skips.
The final snapshot rerun, historical-node checks, original archive and publication
evidence are recorded separately in
E:/IronsBot-history-validation/bilibili-cleanup-20261113. Initial and final test
counts are distinct executions, not historical-author-date validation.
