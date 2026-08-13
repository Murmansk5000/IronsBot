from pathlib import Path

from ironsbot.config.models.features import FeatureConfig, build_onebot_feature_service
from ironsbot.config.onebot_references import OneBotReferenceResolver
from ironsbot.core.bilibili import BiliConfig
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.bilibili_targets import (
    build_onebot_bili_configured_targets,
)
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.bilibili.categories import classify_dynamic
from ironsbot.services.bilibili.preferences import bili_category_submenu_key
from ironsbot.services.bilibili.targets import BiliTargetService


def _service(path: Path) -> tuple[BiliTargetService, ConversationRef]:
    config = BiliConfig.model_validate(
        {
            "accounts": {"example_account": {"uid": 912345678}},
            "push": {"groups": {"example_group": {"accounts": ["example_account"]}}},
            "category_subscriptions": {
                "accounts": {
                    "example_account": {
                        "label": "示例账号",
                        "categories": {
                            "lottery": {"label": "抽奖", "patterns": ["恭喜", "中奖"]},
                            "news": {"label": "公告", "patterns": ["公告"]},
                        },
                        "default_muted_categories": ["lottery"],
                    }
                }
            },
        }
    )
    conversation = ConversationRef(Platform.ONEBOT, "group", "123456")
    features = build_onebot_feature_service(
        FeatureConfig(
            group_aliases={"example_group": 123456},
            group_policy={"example_group": ["bili_push"]},
        ),
        frozenset(),
    )
    return (
        BiliTargetService(
            config,
            features,
            build_onebot_bili_configured_targets(
                config, OneBotReferenceResolver({"example_group": 123456}, {})
            ),
            SqliteBiliPushPreferenceStore(path / "qq_state.sqlite"),
            PushUnsubscribeStore(path / "qq_state.sqlite"),
        ),
        conversation,
    )


def test_category_subscriptions_filter_and_toggle_per_conversation(
    tmp_path: Path,
) -> None:
    service, conversation = _service(tmp_path)
    category_config = service.category_config_for_uid(912345678)
    dynamic = {
        "modules": {
            "module_dynamic": {
                "desc": {"text": "恭喜中奖，欢迎参加本次周年抽奖活动并及时查收通知。"}
            }
        }
    }
    assert classify_dynamic(dynamic, category_config) == ("lottery",)
    assert not service.push_targets_for_dynamic(
        912345678,
        categories=("lottery",),
    ).has_targets

    root = service.subscription_options(conversation)[0]
    assert root.submenu_key == bili_category_submenu_key(912345678)
    submenu = service.subscription_submenu(conversation, root, read_only=False)
    assert submenu is not None
    options, _ = submenu
    lottery = options[1]
    assert lottery.unsubscribed
    assert service.toggle_subscription(conversation, lottery) == "已恢复订阅：抽奖。"
    assert service.push_targets_for_dynamic(
        912345678,
        categories=("lottery",),
    ).has_targets
