# Player Configuration Boundary

Status: `verified`

Target: validated configuration is authoritative; no reflective legacy defaults.
Owner: PlayerService composition of its existing PlayerQueryCache.

- Pass SeerConfig.player.background_refresh.cache_ttl_seconds directly into the
  existing cache constructor. Remove from_config(object), nested getattr and
  its duplicate 300-second fallback. No replacement adapter or compatibility API.
- Delete unused shortcut_timeout_seconds and its Any/cast imports; repository
  search finds no callers. Active detail deadlines remain unchanged.
- Tests use real SeerConfig rather than partial namespace objects which relied
  on the deleted fallback. Assert a non-default cache TTL is actually applied.
- No user-visible configuration change, migration, dependencies or main merge.

Verification: focused player binding/quota/cache/background tests, Ruff, types,
compileall and diff check; full regression deferred to the phase gate. Rollback:
code revert. Program 4/8, item estimate 20-40 minutes, overall ETA unestablished.

Evidence: 84 focused player tests passed in 6.14 seconds; private extension
26 passed in 1.82 seconds. Ruff, BasedPyright (zero errors/warnings), compileall
and diff checks passed. Non-default five-second TTL is verified through the
actual PlayerService-created cache. No full-suite or live deployment claim.
