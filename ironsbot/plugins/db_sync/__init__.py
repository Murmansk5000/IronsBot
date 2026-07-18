# SPDX-License-Identifier: MIT
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ironsbot.core.commands import normalize_command_text
from ironsbot.integrations.db_sync import registry as db_sync_registry
from ironsbot.integrations.db_sync import runner as db_sync_runner
from ironsbot.integrations.db_sync import state as db_sync_state
from ironsbot.integrations.db_sync.models import SyncStatus
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import finish_event_reply, send_event_reply
from ironsbot.utils.rule import no_reply

MANUAL_SYNC_COMMANDS = ("更新数据", "数据更新")
FORCE_MANUAL_SYNC_COMMANDS = ("强制更新数据", "强制数据更新")
ADMIN_COMMAND_PREFIX = "/"
NORMALIZED_MANUAL_SYNC_COMMANDS = {
    normalize_command_text(command) for command in MANUAL_SYNC_COMMANDS
}
NORMALIZED_FORCE_MANUAL_SYNC_COMMANDS = {
    normalize_command_text(command) for command in FORCE_MANUAL_SYNC_COMMANDS
}


async def _is_manual_sync_command(event: Event) -> bool:
    text = event.get_plaintext().strip()
    if not text.startswith(ADMIN_COMMAND_PREFIX):
        return False

    command = normalize_command_text(text[len(ADMIN_COMMAND_PREFIX) :])
    return (
        command in NORMALIZED_MANUAL_SYNC_COMMANDS
        or command in NORMALIZED_FORCE_MANUAL_SYNC_COMMANDS
    )


def _is_force_manual_sync_event(event: Event) -> bool:
    text = event.get_plaintext().strip()
    command = normalize_command_text(text[len(ADMIN_COMMAND_PREFIX) :])
    return command in NORMALIZED_FORCE_MANUAL_SYNC_COMMANDS


def install(registry: MatcherRegistry, github_token: str) -> None:
    async def handle_sync(matcher: Matcher, event: MessageEvent) -> None:
        if not db_sync_state.registered_syncs:
            await finish_event_reply(
                matcher,
                event,
                "当前没有已注册的远程同步数据库。",
            )
        if db_sync_registry.is_sync_running():
            await finish_event_reply(
                matcher,
                event,
                "⏳ 数据更新正在进行中，请稍后再试。",
            )

        names = list(db_sync_state.registered_syncs)
        remote_names = db_sync_runner.remote_build_names()
        force = _is_force_manual_sync_event(event)
        if remote_names:
            remote_action = "强制远程重建数据" if force else "检查远程数据更新"
            message = (
                f"开始{remote_action}：{', '.join(remote_names)}；"
                f"随后更新数据：{', '.join(names)}，请稍等。"
            )
        else:
            message = f"开始更新数据：{', '.join(names)}，请稍等。"
        await send_event_reply(matcher, event, message)

        did_run, results = await db_sync_runner.run_sync_all_databases(
            github_token=github_token,
            trigger_remote_build=True,
            force_remote_build=force,
        )
        if not did_run:
            await finish_event_reply(
                matcher,
                event,
                "⏳ 数据更新正在进行中，请稍后再试。",
            )

        failed = [name for name, ok in results.items() if not ok]
        succeeded = [name for name, ok in results.items() if ok]
        status_text = db_sync_runner.format_sync_statuses(results)
        status_extra = f"\n{status_text}" if status_text else ""
        if failed:
            remote_failure = db_sync_runner.format_remote_build_failures(failed)
            remote_extra = f"\n{remote_failure}" if remote_failure else ""
            await finish_event_reply(
                matcher,
                event,
                "数据更新完成，但有失败项。\n"
                f"成功：{', '.join(succeeded) if succeeded else '无'}\n"
                f"失败：{', '.join(failed)}"
                f"{status_extra}"
                f"{remote_extra}\n"
                "请查看容器日志确认网络或下载错误。",
            )

        skipped = [
            name
            for name, ok in results.items()
            if ok
            and db_sync_state.last_sync_statuses.get(
                name,
                SyncStatus(ok=True),
            ).skipped
        ]
        if skipped and len(skipped) == len(results):
            title = f"数据已是最新，无需更新：{', '.join(skipped)}"
        else:
            title = f"数据更新完成：{', '.join(succeeded)}"
        await finish_event_reply(matcher, event, f"{title}{status_extra}")

    matcher = registry.on_message(
        policy=CommandPolicy.command("data_sync"),
        rule=Rule(_is_manual_sync_command) & no_reply(),
        permission=SUPERUSER,
        priority=get_matcher_priority("db_sync", 5),
        block=True,
    )
    matcher.append_handler(handle_sync)
