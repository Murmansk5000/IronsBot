# SPDX-License-Identifier: MIT
from typing import NoReturn

from nonebot import logger
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.permission import SUPERUSER
from nonebot.plugin import on_command

from ironsbot.plugins.db_sync import get_registered_sync_names, sync_database
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply

_DB_DISPLAY_NAMES: dict[str, str] = {
    "seerapi": "游戏数据",
    "aliases": "别名数据",
}

# 命令参数中可接受的库名及友好别名，统一映射到内部数据库名
_DB_ARG_ALIASES: dict[str, str] = {
    "seerapi": "seerapi",
    "游戏数据": "seerapi",
    "精灵数据": "seerapi",
    "aliases": "aliases",
    "别名": "aliases",
    "别名数据": "aliases",
}

sync_matcher = on_command(
    "同步数据",
    rule=no_reply(),
    permission=SUPERUSER,
    priority=1,
    block=True,
)

USAGE = "用法：同步数据（同步全部）/ 同步数据 <库名>"


def _display_name(name: str) -> str:
    return _DB_DISPLAY_NAMES.get(name, name)


def build_usage() -> str:
    """动态生成 seer_data 插件的 usage。

    根据运行时配置自动适配：仅当存在远程同步数据库时,
    才展示"同步数据"维护命令（仅超级用户）的说明,
    并列出当前注册的数据库及对应的具体命令;
    全部为本地数据库时则不展示该命令。
    """
    lines = ["其他插件通过 require 后使用 db 与 image 模块中的依赖注入"]
    if sync_names := get_registered_sync_names():
        db_commands = "\n".join(
            f"  > 同步数据 {n}/{_display_name(n)}" for n in sync_names
        )
        lines.append(
            "🔧 维护命令（仅超级用户）：\n"
            "  同步数据 — 手动触发数据库更新（带参数调用同步指定库，默认同步全部）\n"
            f"{db_commands}"
        )
    return "\n\n".join(lines)


if get_registered_sync_names():

    @sync_matcher.handle()
    async def handle_sync(
        matcher: Matcher,
        arg: str = Depends(parse_string_arg),
    ) -> NoReturn:
        sync_names = get_registered_sync_names()

        if arg:
            target = _DB_ARG_ALIASES.get(arg.strip().lower())
            if target is None or target not in sync_names:
                valid = "、".join(_display_name(name) for name in sync_names)
                await matcher.finish(
                    f"❌未知的数据库：{arg}\n可用选项：{valid}\n{USAGE}"
                )
            targets = [target]
        else:
            targets = sync_names

        lines: list[str] = []
        for name in targets:
            display = _display_name(name)
            try:
                result = await sync_database(name)
            except Exception:  # noqa: BLE001
                logger.opt(exception=True).error(f"同步数据库 '{name}' 时发生异常")
                lines.append(f"❌{display}：同步失败（详见日志）")
                continue

            if result == "updated":
                lines.append(f"✅{display}：已更新")
            elif result == "skipped":
                lines.append(f"{display}：已是最新，无需更新")
            elif result == "failed":
                lines.append(f"❌{display}：同步失败（详见日志）")
            else:
                lines.append(f"❌{display}：未注册的同步数据库")

        await matcher.finish("数据库同步完成：\n" + "\n".join(lines))
