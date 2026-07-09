# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from nonebot import logger

if TYPE_CHECKING:
    from .docker_update_models import DockerImageInfo

GITHUB_REPO_PATH_PARTS = 2

def github_repo_from_image_labels(labels: dict[str, str]) -> tuple[str, str] | None:
    source = labels.get("org.opencontainers.image.source", "").strip()
    if not source:
        return None
    parsed = urlparse(source)
    if parsed.netloc.lower() != "github.com":
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < GITHUB_REPO_PATH_PARTS:
        return None
    repo = parts[1].removesuffix(".git")
    if not parts[0] or not repo:
        return None
    return parts[0], repo

async def resolve_image_commit_summary(
    image_info: DockerImageInfo,
    *,
    fallback_repo: tuple[str, str] | None = None,
) -> str:
    revision = image_info.labels.get("org.opencontainers.image.revision", "").strip()
    if not revision:
        return ""

    short_revision = revision[:12]
    repo = github_repo_from_image_labels(image_info.labels) or fallback_repo
    if repo is not None:
        owner, name = repo
        try:
            async with httpx.AsyncClient(
                timeout=8.0,
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    f"https://api.github.com/repos/{owner}/{name}/commits/{revision}",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "IronsBot-DockerUpdate",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "failed to fetch docker image commit message: "
                "repo={}/{} revision={} error={}",
                owner,
                name,
                short_revision,
                e,
            )
        else:
            commit = data.get("commit")
            if isinstance(commit, dict):
                message = commit.get("message")
                if isinstance(message, str):
                    first_line = (
                        message.strip().splitlines()[0].strip()
                        if message.strip()
                        else ""
                    )
                    if first_line:
                        return f"{short_revision} {first_line}"
    return ""
