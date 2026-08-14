# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime


def format_remote_build_failures(
    failed_names: list[str],
    remote_build_results: dict[str, Any],
) -> str:
    lines: list[str] = []
    for name in failed_names:
        result = remote_build_results.get(name)
        if result is None:
            continue
        lines.append(f"远程构建失败：{name}（{result.message}）")
        if result.html_url:
            lines.append(f"Actions: {result.html_url}")
    return "\n".join(lines)


def format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "未知"

    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def format_fingerprint(value: str | None) -> str:
    if not value:
        return "未知"

    return value[:12]


def format_local_versions(local_versions: dict[str, Any]) -> str:
    lines = ["当前本地数据版本："]
    for name, version in local_versions.items():
        if version is None:
            lines.append(f"{name}：未安装")
            continue
        lines.append(
            f"{name}：{format_timestamp(version.timestamp)} "
            f"sha256={format_fingerprint(version.fingerprint)}"
        )
    return "\n".join(lines)


def format_sync_statuses(
    results: dict[str, bool],
    sync_statuses: dict[str, Any],
) -> str:
    lines: list[str] = []
    for name in results:
        status = sync_statuses.get(name)
        if status is None:
            continue

        state = (
            "无需更新"
            if status.ok and status.skipped
            else "已更新"
            if status.ok
            else "失败"
        )
        lines.append(f"{name}：{state}")
        lines.append(
            "  本地："
            f"{format_timestamp(status.local_before.timestamp)} "
            f"sha256={format_fingerprint(status.local_before.fingerprint)}"
        )
        lines.append(
            "  远端："
            f"{format_timestamp(status.remote.timestamp)} "
            f"sha256={format_fingerprint(status.remote.fingerprint)}"
        )
        hidden_messages = {"已更新", "本地与远端一致，无需更新"}
        if status.message and status.message not in hidden_messages:
            lines.append(f"  说明：{status.message}")

    return "\n".join(lines)


def format_sync_check_statuses(sync_statuses: Mapping[str, Any]) -> str:
    """Format a read-only remote fingerprint comparison."""

    lines: list[str] = []
    for name, status in sync_statuses.items():
        state = (
            "无需更新"
            if status.ok and status.skipped
            else "发现新版本"
            if status.ok
            else "检查失败"
        )
        lines.append(f"{name}：{state}")
        lines.append(
            "  本地："
            f"{format_timestamp(status.local_before.timestamp)} "
            f"sha256={format_fingerprint(status.local_before.fingerprint)}"
        )
        lines.append(
            "  远端："
            f"{format_timestamp(status.remote.timestamp)} "
            f"sha256={format_fingerprint(status.remote.fingerprint)}"
        )
        if status.message:
            lines.append(f"  说明：{status.message}")
    return "\n".join(lines)


def format_sync_result_notice(
    results: dict[str, bool],
    *,
    sync_statuses: dict[str, Any],
    remote_build_results: dict[str, Any],
    title_prefix: str = "数据更新",
) -> str:
    if not results:
        return f"{title_prefix}未执行。"

    failed = [name for name, ok in results.items() if not ok]
    succeeded = [name for name, ok in results.items() if ok]
    skipped = [
        name
        for name, ok in results.items()
        if ok and (status := sync_statuses.get(name)) is not None and status.skipped
    ]
    if failed:
        title = (
            f"{title_prefix}完成，但有失败项。\n"
            f"成功：{', '.join(succeeded) if succeeded else '无'}\n"
            f"失败：{', '.join(failed)}"
        )
    elif skipped and len(skipped) == len(results):
        title = f"{title_prefix}已是最新，无需更新：{', '.join(skipped)}"
    else:
        title = f"{title_prefix}完成：{', '.join(succeeded)}"

    sections = [title]
    status_text = format_sync_statuses(results, sync_statuses)
    if status_text:
        sections.append(status_text)

    if failed:
        remote_failure_text = format_remote_build_failures(
            failed,
            remote_build_results,
        )
        if remote_failure_text:
            sections.append(remote_failure_text)

    return "\n".join(sections)
