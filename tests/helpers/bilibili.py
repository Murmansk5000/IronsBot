from pathlib import Path

from ironsbot.config.models.bilibili import BiliConfig
from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.message import PushUnsubscribeConfig
from ironsbot.services.bilibili.resources import BilibiliResources
from ironsbot.shared.messaging.push_subscription_store import PushUnsubscribeStore
from tests.helpers.runtime import build_test_runtime


def build_test_bilibili_resources(
    data_dir: Path,
    *,
    config: BiliConfig | None = None,
    feature_config: FeatureConfig | None = None,
    superuser_ids: tuple[int, ...] = (),
) -> BilibiliResources:
    resolved = config or BiliConfig()
    resolved = resolved.model_copy(
        update={
            "storage": resolved.storage.model_copy(
                update={"data_dir": data_dir}
            )
        }
    )
    push_config = PushUnsubscribeConfig(
        data_path=str(data_dir / "push_unsubscriptions.sqlite")
    )
    runtime = build_test_runtime(
        feature_config=feature_config,
        superuser_ids=superuser_ids,
        push_unsubscribe=push_config,
    )
    return BilibiliResources.build(
        resolved,
        PushUnsubscribeStore(push_config.data_path),
        runtime.admin_notices,
    )
