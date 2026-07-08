import importlib
from pathlib import Path

import nonebot
import pytest
from pydantic import ValidationError

from ironsbot.config.models.bilibili import (
    DEFAULT_BILI_ACCOUNT_UID,
    DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
    BiliConfig,
    BiliStorageConfig,
)
from ironsbot.services.bilibili.preferences import bili_push_subscription_key
from ironsbot.shared.messaging.push_subscriptions import PushUnsubscribeStore

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
    account_modes: dict[str, str] | None = None,
) -> state.BiliTargetRule:
    account_modes = account_modes or {}
    return state.BiliTargetRule(
        accounts=frozenset(accounts),
        uids=frozenset(accounts.values()),
        uid_accounts={uid: account for account, uid in accounts.items()},
        mode=mode,
        account_modes=account_modes,
        uid_modes={
            accounts[account]: account_mode
            for account, account_mode in account_modes.items()
        },
    )


def test_bili_login_notice_cooldown_lives_in_bili_config() -> None:
    assert (
        BiliConfig().login_notice_cooldown_seconds
        == DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS
    )


def test_bili_config_defaults_to_official_account() -> None:
    config = BiliConfig()

    assert config.account_aliases["seer"] == DEFAULT_BILI_ACCOUNT_UID
    assert config.push.default_accounts == ["seer"]


def test_bili_config_accepts_alias_based_extra_accounts() -> None:
    config = BiliConfig(
        account_aliases={"fire": FIRE_BILI_UID},
        push={
            "groups": {
                "main": {
                    "extra_accounts": ["fire"],
                    "account_modes": {"fire": "link"},
                }
            }
        },
    )

    assert config.account_aliases["seer"] == DEFAULT_BILI_ACCOUNT_UID
    assert config.account_aliases["fire"] == FIRE_BILI_UID
    assert config.push.groups["main"].extra_accounts == ["fire"]
    assert config.push.groups["main"].account_modes == {"fire": "link"}


def test_bili_config_rejects_removed_uid_fields() -> None:
    with pytest.raises(ValidationError):
        BiliConfig(uids=[1310714247])

    with pytest.raises(ValidationError):
        BiliConfig(push={"default_uids": [1310714247]})

    with pytest.raises(ValidationError):
        BiliConfig(push={"groups": {"main": {"uids": [1310714247]}}})


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
                account_modes={"fire": "link"},
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


def test_push_group_rules_use_default_accounts_for_feature_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        state,
        "get_bili_config",
        lambda: BiliConfig(account_aliases={"fire": 375750254}),
    )
    monkeypatch.setattr(state, "groups_for_feature", lambda _feature: [111, 222])
    monkeypatch.setattr(
        state,
        "CONFIGURED_GROUP_RULES",
        {222: _rule({"seer": 1310714247, "fire": 375750254})},
    )
    monkeypatch.setattr(state, "PUSH_GROUP_RULES", None)

    rules = state.push_group_rules()

    assert rules[111].accounts == frozenset({"seer"})
    assert rules[111].uids == frozenset({1310714247})
    assert rules[222].accounts == frozenset({"seer", "fire"})
    assert rules[222].uids == frozenset({1310714247, 375750254})


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
        include_unsubscribed=False,
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

    active_options = state.bili_push_subscription_options(
        target_type="group",
        target_id=987654321,
        store=store,
        include_unsubscribed=False,
    )
    restore_options = state.bili_push_subscription_options(
        target_type="group",
        target_id=987654321,
        store=store,
        include_unsubscribed=True,
    )

    assert [option.key for option in active_options] == [
        bili_push_subscription_key(1310714247)
    ]
    assert [option.key for option in restore_options] == [
        bili_push_subscription_key(375750254)
    ]
