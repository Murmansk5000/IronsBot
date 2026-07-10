# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ironsbot.shared.messaging import finish_event_reply, send_event_reply

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher


class SyncStatus(Protocol):
    @property
    def skipped(self) -> bool: ...


RunSyncAllDatabases = Callable[..., Awaitable[tuple[bool, dict[str, bool]]]]
IsSyncRunning = Callable[[], bool]
RemoteBuildNames = Callable[[], list[str]]
FormatSyncStatuses = Callable[[dict[str, bool]], str]
FormatRemoteBuildFailures = Callable[[list[str]], str]


@dataclass(frozen=True, slots=True)
class ManualSyncContext:
    registered_syncs: Mapping[str, object]
    last_sync_statuses: Mapping[str, SyncStatus]
    default_sync_status: SyncStatus
    is_sync_running: IsSyncRunning
    remote_build_names: RemoteBuildNames
    run_sync_all_databases: RunSyncAllDatabases
    format_sync_statuses: FormatSyncStatuses
    format_remote_build_failures: FormatRemoteBuildFailures


async def handle_manual_sync(
    matcher: Matcher,
    event: MessageEvent,
    *,
    context: ManualSyncContext,
    force_remote_build: bool = False,
) -> None:
    if not context.registered_syncs:
        await finish_event_reply(matcher, event, "当前没有已注册的远程同步数据库。")

    if context.is_sync_running():
        await finish_event_reply(matcher, event, "⏳ 数据更新正在进行中，请稍后再试。")

    names = list(context.registered_syncs)
    remote_names = context.remote_build_names()
    if remote_names:
        remote_action = "强制远程重建数据" if force_remote_build else "检查远程数据更新"
        start_message = (
            f"开始{remote_action}：{', '.join(remote_names)}；"
            f"随后更新数据：{', '.join(names)}，请稍等。"
        )
    else:
        start_message = f"开始更新数据：{', '.join(names)}，请稍等。"
    await send_event_reply(
        matcher,
        event,
        start_message,
    )

    did_run, results = await context.run_sync_all_databases(
        trigger_remote_build=True,
        force_remote_build=force_remote_build,
    )

    if not did_run:
        await finish_event_reply(matcher, event, "⏳ 数据更新正在进行中，请稍后再试。")

    failed = [name for name, ok in results.items() if not ok]
    succeeded = [name for name, ok in results.items() if ok]
    status_text = context.format_sync_statuses(results)

    if failed:
        remote_failure_text = context.format_remote_build_failures(failed)
        extra_text = f"\n{remote_failure_text}" if remote_failure_text else ""
        status_extra = f"\n{status_text}" if status_text else ""
        await finish_event_reply(
            matcher,
            event,
            "数据更新完成，但有失败项。\n"
            f"成功：{', '.join(succeeded) if succeeded else '无'}\n"
            f"失败：{', '.join(failed)}"
            f"{status_extra}"
            f"{extra_text}\n"
            "请查看容器日志确认网络或下载错误。",
        )

    skipped = [
        name
        for name, ok in results.items()
        if ok
        and context.last_sync_statuses.get(
            name,
            context.default_sync_status,
        ).skipped
    ]
    if skipped and len(skipped) == len(results):
        title = f"数据已是最新，无需更新：{', '.join(skipped)}"
    else:
        title = f"数据更新完成：{', '.join(succeeded)}"
    status_extra = f"\n{status_text}" if status_text else ""
    await finish_event_reply(matcher, event, f"{title}{status_extra}")


__all__ = ["ManualSyncContext", "handle_manual_sync"]
