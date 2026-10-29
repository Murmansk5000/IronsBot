# Repository History Rules

- Read `docs/engineering-workflow.md` before changing history or publishing.
- New commits require a specific English Conventional Commit title and equivalent
  English/Chinese reasons, scope and evidence-backed verification notes.
- Authorized pushes to `main` must also pass the original-history archive workflow.
  Preserve original commits; archive links append snapshots, never replace history.
- Before any rewrite or branch deletion, verify old source heads are reachable in
  the cumulative archive and save/verify a complete bundle under
  `E:/IronsBot-history-validation`. Do not rely on after-the-fact automation.
- A request to commit without pushing also forbids pushing to the history archive.
- By default, finish each independently verified change with a separate commit
  and append its original snapshot to the designated history archive before any
  historical folding. A later explicit no-commit/no-push instruction overrides
  this default. Archive authorization does not authorize development-branch
  publication, production configuration changes or deployment.
- Preserve work in progress, backups and source branches unless cleanup is
  explicitly authorized. Do not deploy or modify production configuration implicitly.
- Do not read, edit, stage, format or restore the reserved working files
  `ironsbot/integrations/seer_data/mintmark_series_resolvers.py` and
  `tests/test_mintmark_series_ordinal_resolver.py` without separate user authorization.
