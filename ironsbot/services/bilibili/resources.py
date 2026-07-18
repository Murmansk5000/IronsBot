from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.services.bilibili.auth import BiliLoginRuntimeState
from ironsbot.services.bilibili.cookie_cache import BiliCookieStore
from ironsbot.services.bilibili.dynamic_history import BiliDynamicHistoryStore
from ironsbot.services.bilibili.preferences import BiliPushPreferenceStore
from ironsbot.services.bilibili.schedule import AutoCheckState
from ironsbot.services.bilibili.targets import BiliTargetService

if TYPE_CHECKING:
    from ironsbot.config.models.bilibili import BiliConfig
    from ironsbot.shared.messaging.admin_notice import AdminNoticeService
    from ironsbot.shared.messaging.push_subscription_store import (
        PushUnsubscribeStore,
    )


@dataclass(slots=True)
class BilibiliResources:
    config: BiliConfig
    admin_notices: AdminNoticeService
    targets: BiliTargetService
    cookie_store: BiliCookieStore
    history: BiliDynamicHistoryStore
    check_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    auto_check_state: AutoCheckState = field(default_factory=AutoCheckState)
    login_state: BiliLoginRuntimeState = field(default_factory=BiliLoginRuntimeState)
    login_poll_task: asyncio.Task[None] | None = None

    @classmethod
    def build(
        cls,
        config: BiliConfig,
        unsubscribe_store: PushUnsubscribeStore,
        admin_notices: AdminNoticeService,
    ) -> BilibiliResources:
        data_dir = config.storage.data_dir
        return cls(
            config=config,
            admin_notices=admin_notices,
            targets=BiliTargetService(
                config,
                admin_notices.features,
                BiliPushPreferenceStore(data_dir / "push_preferences.sqlite"),
                unsubscribe_store,
            ),
            cookie_store=BiliCookieStore(data_dir / "bili_cookie_cache.txt"),
            history=BiliDynamicHistoryStore(
                data_dir / "dynamic_history.sqlite",
                config.storage.history_max_items,
            ),
        )
