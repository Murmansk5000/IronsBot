from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from ironsbot.core.bilibili import BiliPushMode
    from ironsbot.services.messaging.subscriptions import PushTargetType

BILI_PUSH_SUBSCRIPTION_PREFIX = "bili_push:"
BiliRuntimePushMode = Literal["full", "link"]
INVALID_PUSH_MODE_ERROR = "push mode must be content/full, link, or default"


class BiliPushPreferenceStore(Protocol):
    def get_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
    ) -> BiliRuntimePushMode | None: ...

    def set_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
        mode: BiliRuntimePushMode,
    ) -> None: ...

    def clear_mode(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
    ) -> None: ...


def bili_push_subscription_key(uid: int) -> str:
    return f"{BILI_PUSH_SUBSCRIPTION_PREFIX}{int(uid)}"


def bili_push_subscription_label(uid: int, label: str | None = None) -> str:
    return f"B站动态：{label or int(uid)}"


def normalize_push_mode_text(raw_mode: str) -> BiliRuntimePushMode | None:
    mode = "".join(raw_mode.strip().lower().split())
    if mode in {"full", "content", "内容", "全文", "正文"}:
        return "full"
    if mode in {"link", "url", "链接", "只发链接"}:
        return "link"
    if mode in {"default", "reset", "默认", "重置"}:
        return None
    raise ValueError(INVALID_PUSH_MODE_ERROR)


def push_mode_label(mode: BiliPushMode | None) -> str:
    if mode == "full":
        return "内容"
    if mode == "link":
        return "链接"
    return "默认"
