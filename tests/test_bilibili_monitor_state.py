import importlib
from pathlib import Path
from typing import Any

import nonebot
import pytest

from ironsbot.config.models.bilibili import (
    DEFAULT_BILI_ACCOUNT_UID,
    DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
    DEFAULT_BILI_PUSH_MODES,
    BiliConfig,
    BiliStorageConfig,
)
from ironsbot.services.bilibili.preferences import bili_push_subscription_key
from ironsbot.services.bilibili.state import BiliTargetRule
from ironsbot.shared.messaging.push_subscription_store import PushUnsubscribeStore

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

state = importlib.import_module("ironsbot.services.bilibili.state")
FIRE_BILI_UID = 375750254


def _rule(
    accounts: dict[str, int],
    *,
    mode: str = "full",
    modes: dict[str, str] | None = None,
) -> BiliTargetRule:
    modes = modes or {}
    return state.BiliTargetRule(
        accounts=frozenset(accounts),
        uids=frozenset(accounts.values()),
        uid_accounts={uid: account for account, uid in accounts.items()},
        mode=mode,
        modes=modes,
    )


def _bili_config(**data: Any) -> BiliConfig:
    return BiliConfig.model_validate(data)


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
    config = _bili_config(
        accounts={"fire": {"uid": FIRE_BILI_UID, "nickname": "火火"}}
    )

    assert (
        state.account_display_label("fire", config)
        == f"火火（{FIRE_BILI_UID}）"
    )
    assert (
        state.account_label(FIRE_BILI_UID, config)
        == f"火火（{FIRE_BILI_UID}）"
    )


def test_bili_account_reference_accepts_alias_or_nickname() -> None:
    config = _bili_config(
        accounts={"fire": {"uid": FIRE_BILI_UID, "nickname": "火火"}}
    )

    assert state.resolve_account_reference("fire", config) == "fire"
    assert state.resolve_account_reference("火火", config) == "fire"


def test_group_query_falls_back_to_global_uids_when_feature_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state, "CONFIGURED_GROUP_RULES", {})
    monkeypatch.setattr(
        state,
        "get_bili_config",
        BiliConfig,
    )
    monkeypatch.setattr(state, "is_group_feature_allowed", lambda *_args: True)

    assert state.query_uids_for_group(user_id=1, group_id=987654321) == [
        1310714247
    ]


def test_group_query_still_requires_bili_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state, "CONFIGURED_GROUP_RULES", {})
    monkeypatch.setattr(
        state,
        "get_bili_config",
        BiliConfig,
    )
    monkeypatch.setattr(state, "is_group_feature_allowed", lambda *_args: False)

    assert state.query_uids_for_group(user_id=1, group_id=987654321) == []


def test_group_query_uses_group_subscription_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        state,
        "CONFIGURED_GROUP_RULES",
        {
            987654321: _rule(
                {"seer": 1310714247, "fire": 375750254},
                modes={"fire": "link"},
            )
        },
    )
    monkeypatch.setattr(state, "is_group_feature_allowed", lambda *_args: True)

    assert state.query_uids_for_group(user_id=1, group_id=987654321) == [
        375750254,
        1310714247,
    ]


def test_private_superuser_can_query_global_monitored_uids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state, "CONFIGURED_USER_RULES", {})
    monkeypatch.setattr(state, "MONITORED_UIDS", [1310714247, 375750254])
    monkeypatch.setattr(state, "is_superuser", lambda _user_id: True)

    assert state.query_uids_for_private(user_id=1234567890) == [
        1310714247,
        375750254,
    ]


def test_push_group_rules_use_global_accounts_for_feature_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        state,
        "get_bili_config",
        lambda: BiliConfig(accounts={"fire": 375750254}),
    )
    monkeypatch.setattr(state, "groups_for_feature", lambda _feature: [111, 222])
    monkeypatch.setattr(
        state,
        "CONFIGURED_GROUP_RULES",
        {
            222: _rule(
                {"seer": 1310714247, "fire": 375750254},
                modes={"seer": "full"},
            )
        },
    )
    monkeypatch.setattr(state, "PUSH_GROUP_RULES", None)

    rules = state.push_group_rules()

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
            "groups": {"main": {"accounts": ["fire"]}},
        },
    )

    rule = state._resolve_rule(config.push.groups["main"], config)

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
                "main": {
                    "accounts": ["fire"],
                    "modes": {"fire": "link"},
                }
            },
        },
    )

    rule = state._resolve_rule(config.push.groups["main"], config)

    assert rule.mode_for_uid(1310714247) == "full"
    assert rule.mode_for_uid(FIRE_BILI_UID) == "link"


def test_push_targets_for_uid_respects_runtime_mode_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        state,
        "get_bili_config",
        lambda: BiliConfig(storage=BiliStorageConfig(data_dir=tmp_path)),
    )
    monkeypatch.setattr(
        state,
        "PUSH_GROUP_RULES",
        {
            987654321: _rule({"fire": 375750254})
        },
    )
    monkeypatch.setattr(state, "PUSH_USER_RULES", {})

    state.push_preference_store().set_mode(
        "group",
        987654321,
        375750254,
        "link",
    )

    targets = state.push_targets_for_uid(375750254)

    assert targets.full_group_ids == []
    assert targets.link_group_ids == [987654321]


def test_bili_push_subscription_options_are_per_uid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        state,
        "PUSH_GROUP_RULES",
        {
            987654321: _rule({"seer": 1310714247, "fire": 375750254})
        },
    )
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")

    options = state.bili_push_subscription_options(
        target_type="group",
        target_id=987654321,
        store=store,
    )

    assert [option.key for option in options] == [
        bili_push_subscription_key(375750254),
        bili_push_subscription_key(1310714247),
    ]
    assert [option.label for option in options] == [
        "B站动态：fire（375750254）",
        "B站动态：seer（1310714247）",
    ]

    store.unsubscribe_target(
        "group",
        987654321,
        bili_push_subscription_key(375750254),
        "bili_push",
    )

    options = state.bili_push_subscription_options(
        target_type="group",
        target_id=987654321,
        store=store,
    )

    assert [option.key for option in options] == [
        bili_push_subscription_key(375750254),
        bili_push_subscription_key(1310714247),
    ]
    assert [option.unsubscribed for option in options] == [True, False]


def test_bili_push_subscription_options_use_rule_nicknames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _bili_config(
        accounts={"fire": {"uid": FIRE_BILI_UID, "nickname": "火火"}},
        push={"groups": {"main": {"accounts": ["fire"]}}},
    )
    monkeypatch.setattr(
        state,
        "PUSH_GROUP_RULES",
        {987654321: state._resolve_rule(config.push.groups["main"], config)},
    )
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")

    options = state.bili_push_subscription_options(
        target_type="group",
        target_id=987654321,
        store=store,
    )

    assert [option.label for option in options] == [
        "B站动态：火火（375750254）",
        "B站动态：赛尔号官方（1310714247）",
    ]
