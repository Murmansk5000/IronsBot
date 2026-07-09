from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from .push_subscription_handlers import handle_push_subscription_menu
from .push_time import PushTimeOption
from .push_time_handlers import configure_push_time_handlers, handle_push_time_menu

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

RefreshPushTimeJobs = Callable[[PushTimeOption], Awaitable[None]]


def register_push_management_handlers(
    *,
    push_subscription_matcher: type[Matcher],
    push_time_matcher: type[Matcher],
    refresh_push_time_jobs: RefreshPushTimeJobs,
) -> None:
    configure_push_time_handlers(refresh_push_time_jobs)
    push_subscription_matcher.handle()(handle_push_subscription_menu)
    push_time_matcher.handle()(handle_push_time_menu)


__all__ = ["register_push_management_handlers"]
