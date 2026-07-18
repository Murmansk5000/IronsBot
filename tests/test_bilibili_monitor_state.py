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
from ironsbot.config.models.feature import FeatureConfig
from ironsbot.services.bilibili.preferences import bili_push_subscription_key
from ironsbot.shared.features import FeatureService
from ironsbot.shared.messaging.push_subscription_store import PushUnsubscribeStore

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

accounts = importlib.import_module("ironsbot.services.bilibili.accounts")
targets = importlib.import_module("ironsbot.services.bilibili.targets")
storage = importlib.import_module("ironsbot.services.bilibili.storage")
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


def test_group_query_falls_back_to_global_uids_when_feature_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        targets,
        "get_bili_config",
        BiliConfig,
    )
    features = _features({"987654321": ["bili_query"]})

    assert targets.query_uids_for_group(
        features,
        user_id=1,
        group_id=987654321,
    ) == [1310714247]


def test_group_query_still_requires_bili_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        targets,
        "get_bili_config",
        BiliConfig,
    )
    assert targets.query_uids_for_group(
        _features(),
        user_id=1,
        group_id=987654321,
    ) == []


def test_group_query_uses_group_subscription_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        targets,
        "get_bili_config",
        lambda: _bili_config(
            accounts={"fire": FIRE_BILI_UID},
            push={
                "groups": {
                    "987654321": {
                        "accounts": ["fire"],
                        "modes": {"fire": "link"},
                    }
                }
            },
        ),
    )
    assert targets.query_uids_for_group(
        _features({"987654321": ["bili_query"]}),
        user_id=1,
        group_id=987654321,
    ) == [
        375750254,
        1310714247,
    ]


def test_private_superuser_can_query_global_monitored_uids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        targets,
        "get_bili_config",
        lambda: _bili_config(
            accounts={"fire": FIRE_BILI_UID},
            push={"accounts": ["seer", "fire"]},
        ),
    )
    assert targets.query_uids_for_private(
        _features(superusers=(1234567890,)),
        user_id=1234567890,
    ) == [
        375750254,
        1310714247,
    ]


def test_push_group_rules_use_global_accounts_for_feature_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        targets,
        "get_bili_config",
        lambda: _bili_config(
            accounts={"fire": FIRE_BILI_UID},
            push={
                "groups": {
                    "222": {
                        "accounts": ["fire"],
                        "modes": {"seer": "full"},
                    }
                }
            },
        ),
    )

    rules = targets.push_group_rules(
        _features({"111": ["bili_push"], "222": ["bili_push"]})
    )

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

    rule = targets._resolve_rule(config.push.groups["main"], config)

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

    rule = targets._resolve_rule(config.push.groups["main"], config)

    assert rule.mode_for_uid(1310714247) == "full"
    assert rule.mode_for_uid(FIRE_BILI_UID) == "link"


def test_push_targets_for_uid_respects_runtime_mode_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        storage,
        "get_bili_config",
        lambda: _bili_config(
            accounts={"fire": FIRE_BILI_UID},
            push={"groups": {"987654321": {"accounts": ["fire"]}}},
            storage=BiliStorageConfig(data_dir=tmp_path),
        ),
    )
    monkeypatch.setattr(
        targets,
        "get_bili_config",
        lambda: _bili_config(
            accounts={"fire": FIRE_BILI_UID},
            push={"groups": {"987654321": {"accounts": ["fire"]}}},
        ),
    )

    storage.push_preference_store().set_mode(
        "group",
        987654321,
        375750254,
        "link",
    )

    push_targets = targets.push_targets_for_uid(
        _features({"987654321": ["bili_push"]}),
        375750254,
    )

    assert push_targets.full_group_ids == []
    assert push_targets.link_group_ids == [987654321]


def test_bili_push_subscription_options_are_per_uid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        targets,
        "get_bili_config",
        lambda: _bili_config(
            accounts={"fire": FIRE_BILI_UID},
            push={"groups": {"987654321": {"accounts": ["fire"]}}},
        ),
    )
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")

    options = targets.bili_push_subscription_options(
        target_type="group",
        target_id=987654321,
        store=store,
        features=_features({"987654321": ["bili_push"]}),
    )

    assert [option.key for option in options] == [
        bili_push_subscription_key(375750254),
        bili_push_subscription_key(1310714247),
    ]
    assert [option.label for option in options] == [
        "B站动态：fire（375750254）",
        "B站动态：赛尔号官方（1310714247）",
    ]

    store.unsubscribe_target(
        "group",
        987654321,
        bili_push_subscription_key(375750254),
        "bili_push",
    )

    options = targets.bili_push_subscription_options(
        target_type="group",
        target_id=987654321,
        store=store,
        features=_features({"987654321": ["bili_push"]}),
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
        push={"groups": {"987654321": {"accounts": ["fire"]}}},
    )
    monkeypatch.setattr(
        targets,
        "get_bili_config",
        lambda: config,
    )
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")

    options = targets.bili_push_subscription_options(
        target_type="group",
        target_id=987654321,
        store=store,
        features=_features({"987654321": ["bili_push"]}),
    )

    assert [option.label for option in options] == [
        "B站动态：火火（375750254）",
        "B站动态：赛尔号官方（1310714247）",
    ]
