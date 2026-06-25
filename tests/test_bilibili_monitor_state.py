import importlib

import nonebot
import pytest

from ironsbot.config.models.bilibili import (
    DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
    BiliConfig,
)

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

state = importlib.import_module("ironsbot.services.bilibili.state")


def test_bili_login_notice_cooldown_lives_in_bili_config() -> None:
    assert (
        BiliConfig().login_notice_cooldown_seconds
        == DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS
    )


def test_group_query_falls_back_to_global_uids_when_feature_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state, "CONFIGURED_GROUP_RULES", {})
    monkeypatch.setattr(
        state,
        "get_bili_config",
        lambda: BiliConfig(uids=[1310714247]),
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
        lambda: BiliConfig(uids=[1310714247]),
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
            987654321: state.BiliTargetRule(
                uids=frozenset({1310714247, 375750254}),
                mode="full",
                uid_modes={375750254: "link"},
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
