from pathlib import Path
from typing import Any, cast

import nonebot
import pytest

from ironsbot.app.command_directory.plugins import bilibili_commands
from ironsbot.core.bilibili import (
    DEFAULT_BILI_ACCOUNT_ALIAS,
    DEFAULT_BILI_ACCOUNT_UID,
    DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
    DEFAULT_BILI_PUSH_CONTENT_MAX_CHARS,
    DEFAULT_BILI_PUSH_SUMMARY_MAX_CHARS,
    DEFAULT_SEER_MUTED_CATEGORIES,
    BiliConfig,
    BiliStorageConfig,
)
from ironsbot.core.features import FeatureConfig, FeatureService
from ironsbot.core.messaging import MessageTarget
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.plugins.bilibili.command_rules import (
    is_bili_account_command,
    is_bili_push_mode_command,
    parse_bili_push_mode_command,
)
from ironsbot.services.bilibili import accounts
from ironsbot.services.bilibili.categories import (
    SEER_CATEGORY_LABELS,
    seer_category_option_key,
    seer_category_submenu_key,
)
from ironsbot.services.bilibili.preferences import (
    bili_push_subscription_key,
)
from ironsbot.services.bilibili.targets import BiliTargetService
from tests.helpers.onebot_events import (
    group_admin_message_event,
    group_message_event,
    private_message_event,
)

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

FIRE_BILI_UID = 375750254
FIRE_BILI_ALIAS = "xiaoshandong"
DEFAULT_BILI_ACCOUNT_NAME = "赛尔号官号"
FIRE_BILI_ACCOUNT_NAME = "小山东"


def _features(
    group_policy: dict[str, list[str]] | None = None,
    *,
    user_policy: dict[str, list[str]] | None = None,
    superusers: tuple[int, ...] = (),
) -> FeatureService:
    return FeatureService(
        FeatureConfig(
            group_policy=group_policy or {},
            user_policy=user_policy or {},
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
    *,
    account_names: dict[int, str] | None = None,
) -> BiliTargetService:
    return BiliTargetService(
        config,
        features,
        SqliteBiliPushPreferenceStore(data_dir / "preferences.sqlite"),
        PushUnsubscribeStore(data_dir / "unsubscribe.sqlite"),
        accounts.BiliAccountNames(names=account_names or {}),
    )


def test_bili_login_notice_cooldown_lives_in_bili_config() -> None:
    assert (
        BiliConfig().login_notice_cooldown_seconds
        == DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS
    )


def test_bili_config_defaults_to_official_account() -> None:
    config = BiliConfig()

    assert config.accounts[DEFAULT_BILI_ACCOUNT_ALIAS].uid == (DEFAULT_BILI_ACCOUNT_UID)
    assert config.push.mode == "full"
    assert config.push.accounts == [DEFAULT_BILI_ACCOUNT_ALIAS]
    assert config.push.modes == {}
    assert config.push.content_max_chars == DEFAULT_BILI_PUSH_CONTENT_MAX_CHARS
    assert config.push.summary_max_chars == DEFAULT_BILI_PUSH_SUMMARY_MAX_CHARS
    assert config.push.summary_use_ai
    assert config.seer_categories.default_muted_categories == list(
        DEFAULT_SEER_MUTED_CATEGORIES
    )


def test_bili_config_rejects_removed_default_mode() -> None:
    with pytest.raises(ValueError, match="default_mode"):
        _bili_config(push={"default_mode": "full"})


def test_bili_config_accepts_alias_group_accounts() -> None:
    config = _bili_config(
        accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
        push={
            "groups": {
                "main": {
                    "accounts": [FIRE_BILI_ALIAS],
                    "modes": {FIRE_BILI_ALIAS: "link"},
                }
            }
        },
    )

    assert config.accounts[DEFAULT_BILI_ACCOUNT_ALIAS].uid == (DEFAULT_BILI_ACCOUNT_UID)
    assert config.accounts[FIRE_BILI_ALIAS].uid == FIRE_BILI_UID
    assert config.push.groups["main"].accounts == [FIRE_BILI_ALIAS]
    assert config.push.groups["main"].modes == {FIRE_BILI_ALIAS: "link"}


@pytest.mark.parametrize(
    ("seer_categories", "error_text"),
    [
        ({"account": "missing"}, "bilibili.seer_categories.account"),
        (
            {
                "preview_windows": [
                    {
                        "weekdays": ["weekday"],
                        "start": "17:00",
                        "end": "18:00",
                    }
                ]
            },
            "preview_windows weekdays",
        ),
        ({"lottery_patterns": ["["]}, "lottery_patterns has invalid regex"),
        (
            {"default_muted_categories": ["unknown"]},
            "default_muted_categories contains unknown categories",
        ),
    ],
)
def test_bili_config_validates_seer_category_configuration(
    seer_categories: dict[str, object],
    error_text: str,
) -> None:
    with pytest.raises(ValueError, match=error_text):
        _bili_config(seer_categories=seer_categories)


def test_bili_config_rejects_removed_account_nickname() -> None:
    with pytest.raises(ValueError, match="nickname"):
        _bili_config(
            accounts={
                FIRE_BILI_ALIAS: {
                    "uid": FIRE_BILI_UID,
                    "nickname": "旧自定义昵称",
                }
            }
        )


def test_bili_account_names_resolve_only_public_account_name() -> None:
    account_names = accounts.BiliAccountNames(
        names={FIRE_BILI_UID: FIRE_BILI_ACCOUNT_NAME}
    )

    assert account_names.name_for_uid(FIRE_BILI_UID) == FIRE_BILI_ACCOUNT_NAME
    assert (
        account_names.resolve(FIRE_BILI_ACCOUNT_NAME, [FIRE_BILI_UID]) == FIRE_BILI_UID
    )
    assert account_names.resolve(str(FIRE_BILI_UID), [FIRE_BILI_UID]) == FIRE_BILI_UID
    assert account_names.resolve("火火", [FIRE_BILI_UID]) is None


def test_bili_push_mode_command_accepts_spaces_in_public_account_name() -> None:
    assert parse_bili_push_mode_command("B站推送模式 赛尔号 官号 链接") == (
        "赛尔号 官号",
        "链接",
    )


def test_bili_push_mode_matcher_requires_the_push_feature() -> None:
    command = "B站推送模式 赛尔号官号 链接"

    assert not is_bili_push_mode_command(
        _features(),
        group_message_event(command, group_id=987654321),
        {},
    )
    state: dict[str, object] = {}
    assert is_bili_push_mode_command(
        _features(user_policy={"123": ["bili_push"]}),
        private_message_event(command, user_id=123),
        state,
    )
    assert state


def test_private_bili_push_mode_is_available_to_its_private_subscriber() -> None:
    command = next(
        item for item in bilibili_commands() if item.id == "bilibili.private_push_mode"
    )

    assert command.section == "私聊管理"
    assert command.access[0].scope == "private"
    assert command.access[0].audience == "regular"


def test_bili_account_matcher_keeps_push_subscriptions_group_manager_only() -> None:
    command = "B站账号"

    assert not is_bili_account_command(
        _features({"987654321": ["bili_push"]}),
        group_message_event(command, group_id=987654321),
    )
    assert is_bili_account_command(
        _features({"987654321": ["bili_push"]}),
        group_admin_message_event(command, group_id=987654321),
    )
    assert is_bili_account_command(
        _features({"987654321": ["bili_query"]}),
        group_message_event(command, group_id=987654321),
    )


def test_group_query_falls_back_to_global_uids_when_feature_enabled() -> None:
    features = _features({"987654321": ["bili_query"]})

    assert _target_service(BiliConfig(), features).query_uids_for_group(
        user_id=1,
        group_id=987654321,
    ) == [1310714247]


def test_group_query_still_requires_bili_feature() -> None:
    assert (
        _target_service(BiliConfig(), _features()).query_uids_for_group(
            user_id=1,
            group_id=987654321,
        )
        == []
    )


def test_history_hint_requires_target_query_feature() -> None:
    service = _target_service(
        BiliConfig(),
        _features({"987654321": ["bili_query"], "876543210": ["bili_push"]}),
    )

    assert service.can_target_query_history(MessageTarget("group", 987654321))
    assert not service.can_target_query_history(MessageTarget("group", 876543210))


def test_group_query_uses_group_subscription_rule() -> None:
    config = _bili_config(
        accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
        push={
            "groups": {
                "987654321": {
                    "accounts": [FIRE_BILI_ALIAS],
                    "modes": {FIRE_BILI_ALIAS: "link"},
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
            accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
            push={
                "accounts": [
                    DEFAULT_BILI_ACCOUNT_ALIAS,
                    FIRE_BILI_ALIAS,
                ]
            },
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
        accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
        push={
            "groups": {
                "222": {
                    "accounts": [FIRE_BILI_ALIAS],
                    "modes": {DEFAULT_BILI_ACCOUNT_ALIAS: "full"},
                }
            }
        },
    )

    rules = _target_service(
        config,
        _features({"111": ["bili_push"], "222": ["bili_push"]}),
    ).push_group_rules()

    assert rules[111].uids == frozenset({1310714247})
    assert rules[111].default_mode == "full"
    assert rules[111].modes == {}
    assert rules[222].uids == frozenset({1310714247, 375750254})
    assert rules[222].modes == {DEFAULT_BILI_ACCOUNT_UID: "full"}


def test_global_modes_apply_to_extra_group_accounts() -> None:
    config = _bili_config(
        accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
        push={
            "mode": "link",
            "accounts": [DEFAULT_BILI_ACCOUNT_ALIAS],
            "modes": {
                DEFAULT_BILI_ACCOUNT_ALIAS: "full",
                FIRE_BILI_ALIAS: "full",
            },
            "groups": {"1": {"accounts": [FIRE_BILI_ALIAS]}},
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
        accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
        push={
            "mode": "link",
            "accounts": [DEFAULT_BILI_ACCOUNT_ALIAS],
            "modes": {
                DEFAULT_BILI_ACCOUNT_ALIAS: "full",
                FIRE_BILI_ALIAS: "full",
            },
            "groups": {
                "1": {
                    "accounts": [FIRE_BILI_ALIAS],
                    "modes": {FIRE_BILI_ALIAS: "link"},
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
            accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
            push={
                "groups": {
                    "987654321": {
                        "accounts": [FIRE_BILI_ALIAS],
                    }
                }
            },
            storage=BiliStorageConfig(data_dir=tmp_path),
        ),
        _features({"987654321": ["bili_push"]}),
        tmp_path,
        account_names={
            DEFAULT_BILI_ACCOUNT_UID: DEFAULT_BILI_ACCOUNT_NAME,
            FIRE_BILI_UID: FIRE_BILI_ACCOUNT_NAME,
        },
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
            accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
            push={
                "groups": {
                    "987654321": {
                        "accounts": [FIRE_BILI_ALIAS],
                    }
                }
            },
        ),
        _features({"987654321": ["bili_push"]}),
        tmp_path,
        account_names={
            DEFAULT_BILI_ACCOUNT_UID: DEFAULT_BILI_ACCOUNT_NAME,
            FIRE_BILI_UID: FIRE_BILI_ACCOUNT_NAME,
        },
    )

    options = service.subscription_options("group", 987654321)

    assert [option.key for option in options] == [
        bili_push_subscription_key(375750254),
        bili_push_subscription_key(1310714247),
    ]
    assert [option.label for option in options] == [
        f"B站动态：{FIRE_BILI_ACCOUNT_NAME}",
        "赛尔号 B站动态设置",
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


def test_bili_push_subscription_options_use_public_account_names(
    tmp_path: Path,
) -> None:
    config = _bili_config(
        accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
        push={
            "groups": {
                "987654321": {
                    "accounts": [FIRE_BILI_ALIAS],
                }
            }
        },
    )
    service = _target_service(
        config,
        _features({"987654321": ["bili_push"]}),
        tmp_path,
        account_names={
            DEFAULT_BILI_ACCOUNT_UID: DEFAULT_BILI_ACCOUNT_NAME,
            FIRE_BILI_UID: FIRE_BILI_ACCOUNT_NAME,
        },
    )

    options = service.subscription_options("group", 987654321)

    assert [option.label for option in options] == [
        f"B站动态：{FIRE_BILI_ACCOUNT_NAME}",
        "赛尔号 B站动态设置",
    ]


def test_seer_category_subscription_submenu_and_target_filtering(
    tmp_path: Path,
) -> None:
    group_id = 987654321
    service = _target_service(
        BiliConfig(),
        _features({str(group_id): ["bili_push"]}),
        tmp_path,
        account_names={DEFAULT_BILI_ACCOUNT_UID: DEFAULT_BILI_ACCOUNT_NAME},
    )
    option = service.subscription_options("group", group_id)[0]

    assert option.label == "赛尔号 B站动态设置"
    assert option.submenu_key == seer_category_submenu_key(DEFAULT_BILI_ACCOUNT_UID)

    submenu = service.subscription_submenu("group", group_id, option)
    assert submenu is not None
    children, prompt = submenu
    assert children[0].label == "赛尔号动态总开关"
    assert "请选择要切换" in prompt
    assert "总开关为 ❌ 时" in prompt
    assert [child.label for child in children[1:]] == [
        SEER_CATEGORY_LABELS[category] for category in SEER_CATEGORY_LABELS
    ]
    assert children[1].unsubscribed

    lottery_targets = service.push_targets_for_uid(
        DEFAULT_BILI_ACCOUNT_UID,
        categories=("lottery",),
    )
    pet_targets = service.push_targets_for_uid(
        DEFAULT_BILI_ACCOUNT_UID,
        categories=("pet",),
    )
    mixed_targets = service.push_targets_for_uid(
        DEFAULT_BILI_ACCOUNT_UID,
        categories=("lottery", "pet"),
    )
    assert lottery_targets.full_group_ids == []
    assert pet_targets.full_group_ids == [group_id]
    assert mixed_targets.full_group_ids == [group_id]

    service.toggle_subscription_option(
        "group",
        group_id,
        children[1 + list(SEER_CATEGORY_LABELS).index("pet")],
    )
    assert (
        service.push_targets_for_uid(
            DEFAULT_BILI_ACCOUNT_UID,
            categories=("lottery", "pet"),
        ).full_group_ids
        == []
    )
    assert (
        seer_category_option_key(DEFAULT_BILI_ACCOUNT_UID, "pet")
        == children[1 + list(SEER_CATEGORY_LABELS).index("pet")].key
    )

    cast("PushUnsubscribeStore", service.unsubscribe_store).unsubscribe_target(
        "group",
        group_id,
        bili_push_subscription_key(DEFAULT_BILI_ACCOUNT_UID),
        "bili_push",
    )
    preserved_submenu = service.subscription_submenu("group", group_id, option)
    assert preserved_submenu is not None
    preserved_children, _preserved_prompt = preserved_submenu
    assert preserved_children[0].unsubscribed
    assert preserved_children[1 + list(SEER_CATEGORY_LABELS).index("pet")].unsubscribed

    readonly_submenu = service.subscription_submenu(
        "group",
        group_id,
        option,
        read_only=True,
    )
    assert readonly_submenu is not None
    assert "状态" in readonly_submenu[1]


@pytest.mark.asyncio
async def test_bili_account_summary_and_push_mode_update_use_target_service(
    tmp_path: Path,
) -> None:
    unused_uid = 999999999
    config = _bili_config(
        accounts={
            FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID},
            "unused": {"uid": unused_uid},
        },
        push={
            "groups": {
                "987654321": {
                    "accounts": [FIRE_BILI_ALIAS],
                }
            }
        },
    )
    service = _target_service(
        config,
        _features({"987654321": ["bili_push"]}),
        tmp_path,
        account_names={
            DEFAULT_BILI_ACCOUNT_UID: DEFAULT_BILI_ACCOUNT_NAME,
            FIRE_BILI_UID: FIRE_BILI_ACCOUNT_NAME,
        },
    )

    summary = await service.account_summary("group", 987654321)
    assert FIRE_BILI_ACCOUNT_NAME in summary
    assert DEFAULT_BILI_ACCOUNT_NAME in summary
    assert str(FIRE_BILI_UID) not in summary
    assert str(DEFAULT_BILI_ACCOUNT_UID) not in summary
    assert str(unused_uid) not in summary
    assert "当前群订阅：" in summary
    assert "默认（内容）" in summary
    assert "账号库：" not in summary

    result = await service.update_push_mode(
        "group",
        987654321,
        FIRE_BILI_ACCOUNT_NAME,
        "链接",
    )
    assert "推送模式：链接" in result
    assert "已自定义（链接）" in result
    assert service.mode_for_uid("group", 987654321, FIRE_BILI_UID) == "link"


@pytest.mark.asyncio
async def test_bili_mode_display_distinguishes_default_config_and_runtime(
    tmp_path: Path,
) -> None:
    config = _bili_config(
        push={
            "modes": {DEFAULT_BILI_ACCOUNT_ALIAS: "link"},
        }
    )
    service = _target_service(
        config,
        _features({"987654321": ["bili_push"]}),
        tmp_path,
        account_names={DEFAULT_BILI_ACCOUNT_UID: DEFAULT_BILI_ACCOUNT_NAME},
    )

    assert (
        service.mode_display_for_uid("group", 987654321, DEFAULT_BILI_ACCOUNT_UID)
        == "配置（链接）"
    )

    await service.update_push_mode(
        "group",
        987654321,
        DEFAULT_BILI_ACCOUNT_ALIAS,
        "内容",
    )
    assert (
        service.mode_display_for_uid("group", 987654321, DEFAULT_BILI_ACCOUNT_UID)
        == "已自定义（内容）"
    )

    result = await service.update_push_mode(
        "group",
        987654321,
        DEFAULT_BILI_ACCOUNT_ALIAS,
        "默认",
    )
    assert "已恢复当前群" in result
    assert "当前生效模式：配置（链接）" in result


@pytest.mark.asyncio
async def test_bili_push_mode_accepts_alias_and_uid_without_public_name(
    tmp_path: Path,
) -> None:
    service = _target_service(
        _bili_config(
            accounts={FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID}},
            push={
                "groups": {
                    "987654321": {
                        "accounts": [FIRE_BILI_ALIAS],
                    }
                }
            },
        ),
        _features({"987654321": ["bili_push"]}),
        tmp_path,
    )

    result = await service.update_push_mode(
        "group",
        987654321,
        FIRE_BILI_ALIAS,
        "链接",
    )

    assert "推送模式：链接" in result
    assert FIRE_BILI_ALIAS not in result
    assert service.mode_for_uid("group", 987654321, FIRE_BILI_UID) == "link"

    uid_result = await service.update_push_mode(
        "group",
        987654321,
        str(FIRE_BILI_UID),
        "内容",
    )

    assert "推送模式：内容" in uid_result
    assert service.mode_for_uid("group", 987654321, FIRE_BILI_UID) == "full"


@pytest.mark.asyncio
async def test_private_account_summary_and_push_mode_use_current_user_only(
    tmp_path: Path,
) -> None:
    user_id = 1234567890
    unused_uid = 999999999
    config = _bili_config(
        accounts={
            FIRE_BILI_ALIAS: {"uid": FIRE_BILI_UID},
            "unused": {"uid": unused_uid},
        },
        push={
            "users": {
                str(user_id): {
                    "accounts": [FIRE_BILI_ALIAS],
                }
            }
        },
    )
    service = _target_service(
        config,
        _features(user_policy={str(user_id): ["bili_push"]}),
        tmp_path,
        account_names={
            DEFAULT_BILI_ACCOUNT_UID: DEFAULT_BILI_ACCOUNT_NAME,
            FIRE_BILI_UID: FIRE_BILI_ACCOUNT_NAME,
        },
    )

    summary = await service.account_summary("private", user_id)

    assert "当前私聊订阅：" in summary
    assert DEFAULT_BILI_ACCOUNT_NAME in summary
    assert FIRE_BILI_ACCOUNT_NAME in summary
    assert str(DEFAULT_BILI_ACCOUNT_UID) not in summary
    assert str(FIRE_BILI_UID) not in summary
    assert str(unused_uid) not in summary
    assert "群主/管理员" not in summary

    result = await service.update_push_mode(
        "private",
        user_id,
        FIRE_BILI_ACCOUNT_NAME,
        "内容",
    )

    assert "已设置当前私聊" in result
    assert service.mode_for_uid("private", user_id, FIRE_BILI_UID) == "full"


@pytest.mark.asyncio
async def test_bili_account_summary_does_not_fall_back_to_numeric_uid(
    tmp_path: Path,
) -> None:
    service = _target_service(
        BiliConfig(),
        _features({"987654321": ["bili_push"]}),
        tmp_path,
    )

    summary = await service.account_summary("group", 987654321)

    assert "暂时无法获取" in summary
    assert str(DEFAULT_BILI_ACCOUNT_UID) not in summary
