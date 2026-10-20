"""Notify maintainers once per upstream revision; never modify Git history."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UPSTREAM = "Nattsu39/IronsBot"
MAX_COMMITS = 50
PAGE_SIZE = 100
logger = logging.getLogger(__name__)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()


def github_request(method: str, path: str, token: str, data: object = None) -> Any:
    request = Request(
        f"https://api.github.com{path}",
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "IronsBot-upstream-notifier",
        },
        method=method,
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def notify(repository: str, token: str) -> int | None:
    head = git("rev-parse", "upstream/main")
    count = int(git("rev-list", "--count", f"HEAD..{head}"))
    if count == 0:
        logger.info("No upstream updates; no issue created.")
        return None

    marker = f"<!-- ironsbot-upstream-update:{head} -->"
    endpoint = f"/repos/{repository}/issues"
    page = 1
    while True:
        query = urlencode(
            {
                "state": "all",
                "creator": "github-actions[bot]",
                "per_page": PAGE_SIZE,
                "page": page,
            }
        )
        issues = github_request("GET", f"{endpoint}?{query}", token)
        for issue in issues:
            if not issue.get("pull_request") and (issue.get("body") or "").startswith(
                marker + "\n"
            ):
                logger.info(
                    "Upstream revision already reported in issue #%s.", issue["number"]
                )
                return None
        if len(issues) < PAGE_SIZE:
            break
        page += 1

    lines = [
        marker,
        "## 上游有新提交待审查",
        "",
        f"来源：[{UPSTREAM}](https://github.com/{UPSTREAM})",
        f"最新提交：[{head[:8]}](https://github.com/{UPSTREAM}/commit/{head})",
        f"当前主分支尚未包含的上游提交：**{count}** 个。",
        "",
        "这里只通知更新，不代表功能尚未实现，也不会自动合并或部署。",
        "请对照本项目当前架构，逐项确认已有等价实现、需要适配或不适用。",
        "",
    ]
    commits = git(
        "log", f"--max-count={MAX_COMMITS}", "--format=%H%x09%s", f"HEAD..{head}"
    )
    for entry in commits.splitlines():
        sha, subject = entry.split("\t", 1)
        # Upstream subjects are data, not Markdown or notification mentions.
        subject = subject[:160].translate(
            str.maketrans(
                {"@": "＠", "<": "＜", ">": "＞", "`": "＇", "[": "［", "]": "］"}
            )
        )
        lines.append(
            f"- [{sha[:8]}](https://github.com/{UPSTREAM}/commit/{sha}) {subject}"
        )
    if count > MAX_COMMITS:
        lines.append(
            f"\n仅列出最近 {MAX_COMMITS} 个提交，完整列表请查看 Actions 巡检报告。"
        )

    issue = github_request(
        "POST",
        endpoint,
        token,
        {
            "title": f"上游更新待审查：{UPSTREAM} {head[:8]}",
            "body": "\n".join(lines),
            "assignees": [repository.split("/", 1)[0]],
        },
    )
    number = int(issue["number"])
    logger.info("Created upstream update issue #%s.", number)
    return number


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    notify(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
