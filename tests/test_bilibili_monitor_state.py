from pathlib import Path
from typing import Any, cast

import nonebot

from ironsbot.core.bilibili import (
    DEFAULT_BILI_ACCOUNT_UID,
    DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
    DEFAULT_BILI_PUSH_MODES,
    BiliConfig,
    BiliStorageConfig,
)
from ironsbot.core.features import FeatureConfig, FeatureService
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.bilibili import accounts
from ironsbot.services.bilibili.preferences import (
    bili_push_subscription_key,
)
from ironsbot.services.bilibili.targets import BiliTargetService

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

FIRE_BILI_UID = 375750254


def _features(
    group_policy: dict[str, list[str]] | None = None,
    *,
    superusers: tuple[int, ...] = (),
) -> FeatureService:
    return FeatureService(
        FeatureConfig(
            group_policy=group_policy or {},
            superuser_bypass=False,
        ),
        frozenset(superusers),
    )


def _bili_config(**data: Any) -> BiliConfig:
    return BiliConfig.model_validate(data)


def _target_service(
    config: BiliConfig,
    features: FeatureService,
    data_dir: Path = Path("__unused_bili_test_store__"),
) -> BiliTargetService:
    return BiliTargetService(
        config,
        features,
        SqliteBiliPushPreferenceStore(data_dir / "preferences.sqlite"),
        PushUnsubscribeStore(data_dir / "unsubscribe.sqlite"),
    )


def test_bili_login_notice_cooldown_lives_in_bili_config() -> None:
    assert (
        BiliConfig().login_notice_cooldown_seconds
        == DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS
    )


def test_bili_config_defaults_to_official_account() -> None:
    config = BiliConfig()

    assert config.accounts["seer"] == DEFAULT_BILI_ACCOUNT_UID
    assert config.account_nicknames["seer"] == "赛尔号官方"
    assert config.push.mode == "link"
    assert config.push.accounts == ["seer"]
    assert config.push.modes == DEFAULT_BILI_PUSH_MODES


def test_bili_config_accepts_named_group_accounts() -> None:
    config = _bili_config(
        accounts={"fire": {"uid": FIRE_BILI_UID, "nickname": "火火"}},
        push={
            "groups": {
                "main": {
                    "accounts": ["fire"],
                    "modes": {"fire": "link"},
                }
            }
        },
    )

    assert config.accounts["seer"] == DEFAULT_BILI_ACCOUNT_UID
    assert config.accounts["fire"] == FIRE_BILI_UID
    assert config.account_nicknames["fire"] == "火火"
    assert config.push.groups["main"].accounts == ["fire"]
    assert config.push.groups["main"].modes == {"fire": "link"}


def test_bili_account_display_label_uses_nickname() -> None:
    config = _bili_config(accounts={"fire": {"uid": FIRE_BILI_UID, "nickname": "火火"}})

    assert accounts.account_display_label("fire", config) == f"火火（{FIRE_BILI_UID}）"


def test_bili_account_reference_accepts_alias_or_nickname() -> None:
    config = _bili_config(accounts={"fire": {"uid": FIRE_BILI_UID, "nickname": "火火"}})

    assert accounts.resolve_account_reference("fire", config) == "fire"
    assert accounts.resolve_account_reference("火火", config) == "fire"


def test_group_query_falls_back_to_global_uids_when_feature_enabled() -> None:
    features = _features({"987654321": ["bili_query"]})

    assert _target_service(BiliConfig(), features).query_uids_for_group(
        user_id=1,
        group_id=987654321,
    ) == [1310714247]


def test_group_query_still_requires_bili_feature() -> None:
    assert _target_service(BiliConfig(), _features()).query_uids_for_group(
        user_id=1,
        group_id=987654321,
    ) == []


def test_group_query_uses_group_subscription_rule() -> None:
    config = _bili_config(
        accounts={"fire": FIRE_BILI_UID},
        push={
            "groups": {
                "987654321": {
                    "accounts": ["fire"],
                    "modes": {"fire": "link"},
                }
            }
        },
    )
    service = _target_service(
        config,
        _features({"987654321": ["bili_query"]}),
    )
    assert service.query_uids_for_group(
        user_id=1,
        group_id=987654321,
    ) == [
        375750254,
        1310714247,
    ]


def test_private_superuser_can_query_global_monitored_uids() -> None:
    service = _target_service(
        _bili_config(
            accounts={"fire": FIRE_BILI_UID},
            push={"accounts": ["seer", "fire"]},
        ),
        _features(superusers=(1234567890,)),
    )
    assert service.query_uids_for_private(
        user_id=1234567890,
    ) == [
        375750254,
        1310714247,
    ]


def test_push_group_rules_use_global_accounts_for_feature_groups() -> None:
    config = _bili_config(
        accounts={"fire": FIRE_BILI_UID},
        push={
            "groups": {
                "222": {
                    "accounts": ["fire"],
                    "modes": {"seer": "full"},
                }
            }
        },
    )

    rules = _target_service(
        config,
        _features({"111": ["bili_push"], "222": ["bili_push"]}),
    ).push_group_rules()

    assert rules[111].accounts == frozenset({"seer"})
    assert rules[111].uids == frozenset({1310714247})
    assert rules[111].mode == "link"
    assert rules[111].modes == {"seer": "full"}
    assert rules[222].accounts == frozenset({"seer", "fire"})
    assert rules[222].uids == frozenset({1310714247, 375750254})
    assert rules[222].modes == {"seer": "full"}


def test_global_modes_apply_to_extra_group_accounts() -> None:
    config = _bili_config(
        accounts={"fire": FIRE_BILI_UID},
        push={
            "mode": "link",
            "accounts": ["seer"],
            "modes": {"seer": "full", "fire": "full"},
            "groups": {"1": {"accounts": ["fire"]}},
        },
    )

    rule = _target_service(
        config,
        _features({"1": ["bili_push"]}),
    ).push_group_rules()[1]

    assert rule.mode_for_uid(1310714247) == "full"
    assert rule.mode_for_uid(FIRE_BILI_UID) == "full"


def test_group_modes_override_global_modes() -> None:
    config = _bili_config(
        accounts={"fire": FIRE_BILI_UID},
        push={
            "mode": "link",
            "accounts": ["seer"],
            "modes": {"seer": "full", "fire": "full"},
            "groups": {
                "1": {
                    "accounts": ["fire"],
                    "modes": {"fire": "link"},
                }
            },
        },
    )

    rule = _target_service(
        config,
        _features({"1": ["bili_push"]}),
    ).push_group_rules()[1]

    assert rule.mode_for_uid(1310714247) == "full"
    assert rule.mode_for_uid(FIRE_BILI_UID) == "link"


def test_push_targets_for_uid_respects_runtime_mode_override(
    tmp_path: Path,
) -> None:
    service = _target_service(
        _bili_config(
            accounts={"fire": FIRE_BILI_UID},
            push={"groups": {"987654321": {"accounts": ["fire"]}}},
            storage=BiliStorageConfig(data_dir=tmp_path),
        ),
        _features({"987654321": ["bili_push"]}),
        tmp_path,
    )

    service.preferences.set_mode(
        "group",
        987654321,
        375750254,
        "link",
    )

    push_targets = service.push_targets_for_uid(375750254)

    assert push_targets.full_group_ids == []
    assert push_targets.link_group_ids == [987654321]


def test_bili_push_subscription_options_are_per_uid(
    tmp_path: Path,
) -> None:
    service = _target_service(
        _bili_config(
            accounts={"fire": FIRE_BILI_UID},
            push={"groups": {"987654321": {"accounts": ["fire"]}}},
        ),
        _features({"987654321": ["bili_push"]}),
        tmp_path,
    )

    options = service.subscription_options("group", 987654321)

    assert [option.key for option in options] == [
        bili_push_subscription_key(375750254),
        bili_push_subscription_key(1310714247),
    ]
    assert [option.label for option in options] == [
        "B站动态：fire（375750254）",
        "B站动态：赛尔号官方（1310714247）",
    ]

    cast("PushUnsubscribeStore", service.unsubscribe_store).unsubscribe_target(
        "group",
        987654321,
        bili_push_subscription_key(375750254),
        "bili_push",
    )

    options = service.subscription_options("group", 987654321)

    assert [option.key for option in options] == [
        bili_push_subscription_key(375750254),
        bili_push_subscription_key(1310714247),
    ]
    assert [option.unsubscribed for option in options] == [True, False]


def test_bili_push_subscription_options_use_rule_nicknames(
    tmp_path: Path,
) -> None:
    config = _bili_config(
        accounts={"fire": {"uid": FIRE_BILI_UID, "nickname": "火火"}},
        push={"groups": {"987654321": {"accounts": ["fire"]}}},
    )
    service = _target_service(
        config,
        _features({"987654321": ["bili_push"]}),
        tmp_path,
    )

    options = service.subscription_options("group", 987654321)

    assert [option.label for option in options] == [
        "B站动态：火火（375750254）",
        "B站动态：赛尔号官方（1310714247）",
    ]


def test_bili_account_summary_and_push_mode_update_use_target_service(
    tmp_path: Path,
) -> None:
    config = _bili_config(
        accounts={"fire": {"uid": FIRE_BILI_UID, "nickname": "火火"}},
        push={"groups": {"987654321": {"accounts": ["fire"]}}},
    )
    service = _target_service(
        config,
        _features({"987654321": ["bili_push"]}),
        tmp_path,
    )

    summary = service.account_summary("group", 987654321)
    assert f"火火（{FIRE_BILI_UID}）" in summary
    assert "当前订阅：" in summary

    result = service.update_push_mode(
        "group",
        987654321,
        "火火",
        "链接",
    )
    assert "推送模式：链接" in result
    assert service.mode_for_uid("group", 987654321, FIRE_BILI_UID) == "link"
