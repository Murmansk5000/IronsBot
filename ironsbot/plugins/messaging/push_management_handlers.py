from __future__ import annotations

from typing import TYPE_CHECKING

from .push_subscription_handlers import handle_push_subscription_menu
from .push_time_handlers import build_push_time_menu_handler

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.matcher import Matcher

    from .push_time import PushTimeOption

    RefreshPushTimeJobs = Callable[[PushTimeOption], Awaitable[None]]


def register_push_management_handlers(
    *,
    push_subscription_matcher: type[Matcher],
    push_time_matcher: type[Matcher],
    refresh_push_time_jobs: RefreshPushTimeJobs,
) -> None:
    push_subscription_matcher.handle()(handle_push_subscription_menu)
    push_time_matcher.handle()(
        build_push_time_menu_handler(refresh_push_time_jobs)
    )


__all__ = ["register_push_management_handlers"]
