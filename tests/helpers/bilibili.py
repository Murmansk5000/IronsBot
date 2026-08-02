from pathlib import Path

from ironsbot.config.models.messaging import PushUnsubscribeConfig
from ironsbot.core.bilibili import BiliConfig
from ironsbot.core.features import FeatureConfig
from ironsbot.integrations.storage.bilibili_cookie import FileBiliCookieStore
from ironsbot.integrations.storage.bilibili_history import (
    SqliteBiliDynamicHistoryStore,
)
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.integrations.storage.push_subscriptions import (
    PushUnsubscribeStore,
)
from ironsbot.services.bilibili.service import (
    BilibiliService,
    BiliFeedResponse,
)
from ironsbot.services.bilibili.targets import BiliTargetService
from tests.helpers.runtime import build_test_runtime


async def _unused_feed(_cookie: str) -> BiliFeedResponse:
    raise AssertionError


def build_test_bilibili_service(
    data_dir: Path,
    *,
    config: BiliConfig | None = None,
    feature_config: FeatureConfig | None = None,
    superuser_ids: tuple[int, ...] = (),
) -> BilibiliService:
    resolved = config or BiliConfig()
    resolved = resolved.model_copy(
        update={
            "storage": resolved.storage.model_copy(
                update={"data_dir": data_dir}
            )
        }
    )
    push_config = PushUnsubscribeConfig()
    state_path = data_dir / "qq_state.sqlite"
    runtime = build_test_runtime(
        feature_config=feature_config,
        superuser_ids=superuser_ids,
        push_unsubscribe=push_config,
        state_path=state_path,
    )
    return BilibiliService(
        config=resolved,
        targets=BiliTargetService(
            resolved,
            runtime.features,
            SqliteBiliPushPreferenceStore(
                state_path
            ),
            PushUnsubscribeStore(state_path),
        ),
        cookie_store=FileBiliCookieStore(data_dir / "bili_cookie_cache.txt"),
        history=SqliteBiliDynamicHistoryStore(
            data_dir / "dynamic_history.sqlite",
            resolved.storage.history_max_items,
        ),
        fetch_feed=_unused_feed,
    )
