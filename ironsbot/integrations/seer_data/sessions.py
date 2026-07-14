# SPDX-License-Identifier: MIT
from collections.abc import AsyncGenerator, Callable
from typing import Annotated

from nonebot.matcher import Matcher
from nonebot.params import Depends
from sqlmodel import Session as SQLModelSession

from ironsbot.integrations.db_registry import db_manager

_SEERAPI_DB = "seerapi"


def _session_factory(
    db_name: str,
) -> Callable[..., AsyncGenerator[SQLModelSession, None]]:
    async def _session_generator(
        matcher: Matcher,
    ) -> AsyncGenerator[SQLModelSession, None]:
        gen = db_manager.get_session(db_name)
        if gen is None:
            await matcher.finish(
                f"❌数据库 '{db_name}' 未注册，无法使用此命令\n"
                "🔡请将命令和这条消息反馈给机器人维护者吧~"
            )
        try:
            yield next(gen)
        finally:
            gen.close()

    return _session_generator


SeerAPISession = Annotated[SQLModelSession, Depends(_session_factory(_SEERAPI_DB))]
AllSessions = Annotated[
    dict[str, SQLModelSession], Depends(db_manager.get_all_sessions)
]
