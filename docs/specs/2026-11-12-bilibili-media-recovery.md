# Bilibili media recovery and bounded retries

Status: completed (implementation and regression; not deployed)

Contract: baseline correction. Owner: common Bilibili delivery and storage ports.

## Scope / 范围

Repair preparation-only image stages, durable retry budgets and frozen media
storage. Keep successful receipts and uncertain submissions unchanged. Change
half-hour polling offsets to 2, 5, 10, 30 seconds. Save production comments and
offsets without restarting or editing production delivery state.

修复图片准备失败后的逐图接续、持久重试预算与素材存储。成功回执和不确定提交
不重发；半小时偏移改为 2、5、10、30 秒。生产仅保存备注与秒位，不重启。

## Evidence / 证据

Read-only production inspection on 2026-11-12 found two dynamics with 4 and 13
preparation-only image stages stuck in retry despite a frozen manifest. Recovery
cycle counters exceeded 2600 while those stages had only one charged attempt.
Another earlier dynamic had seven FileNotFoundError preparation failures after
restart. Composition stores manifests beside the persistent SQLite database but
their bytes under disposable cache/rendering/assets/bilibili.

上述为阶段与目标计数，不是向腾讯上传两千次；没有证据把所有失败归为 11001。

## Contract / 契约

- Only explicitly recorded media_prepare failures may expand into image units.
  Expansion is transactional; legacy submitted/uncertain images remain protected.
- Each stage has four charged attempts across reconnects/restarts. Offline waits
  refund the attempt. Recovery cycles are not a second sending budget; no-op cycles
  must not accumulate. Preparation and each submitted image are separate stages.
- Frozen bytes belong to persistent Bilibili storage, not disposable render cache.
  Missing or corrupt frozen bytes fail explicitly and are never regenerated from
  an untrusted replacement. Existing missing bytes cannot be reconstructed.
- Preparation failures shared by targets are logged once per preparation task.
- No new TOML fields, no production ledger edits, no historical resend or deploy.

## Acceptance / 验收

Cover preparation recovery, multiple targets, transaction races, four-attempt
exhaustion, repeated scans, offline waits, interrupted rounds, missing/corrupt
bytes and cache removal across restarts. Run targeted/full pytest, Ruff,
BasedPyright, compileall, static and diff checks. Archive independent changes
before folding polling changes into their introduction and Bilibili repairs into
the previous corresponding delivery repair, preserving upstream SHAs.

Verification on 2026-11-12: 121 targeted tests passed; combined-workspace full
pytest passed 6936 with 9 skips. Ruff, compilation, static and diff checks passed;
BasedPyright passed after correcting one test return annotation. The unchanged
native dependency was restored offline from its previously verified frozen cache
after a download timeout; no dependency version or TLS policy changed.

Publication, original archive, folding maps and final workflow evidence are kept
in E:/IronsBot-history-validation/bilibili-recovery-20261112. These are actual
2026-11-12 checks, not tests claimed to have run on a historical author date.
