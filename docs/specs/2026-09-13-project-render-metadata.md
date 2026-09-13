# Project Render Metadata

Status: `completed`

Contract: `target`

Owner: build workflow, runtime metadata adapter, HTML integration and render cache

## Goal

Rendered images identify the repository that built the running image without
hard-coding a maintainer or upstream fork in product templates.

## Contract

- Candidate and published Docker builds receive the same project URL.
- The HTML adapter supplies project metadata centrally; presenters stay pure.
- Missing metadata omits the URL and never guesses a deployer-owned repository.
- Final render cache keys include the URL because it changes visible output.
- No image asset, package dependency or runtime data bundle is added.

## Verification

Project metadata, render cache, Docker workflow and Seer rendering tests passed
55 cases. Ruff and diff checks passed. Real Linux image execution remains a
separate Phase 7 gate because this host has no connected Docker daemon.
