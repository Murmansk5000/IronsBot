from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ironsbot.config.loader import load_settings
from ironsbot.config.models.features import (
    FeatureConfig,
    build_feature_service,
    resolve_feature_bundles,
)
from ironsbot.config.models.settings import Settings
from ironsbot.config.platform_references import PlatformReferenceResolver
from ironsbot.config.qq_references import QQReferenceResolver
from ironsbot.core.platform import ActorRef, ConversationRef, Platform

ROOT = Path(__file__).resolve().parents[1]
GROUP_ID = "200000201"
USER_ID = "100000101"
OFFICIAL_GROUP = ConversationRef(
    Platform.QQ_OFFICIAL, "group", "fictional-group", account_id="10001"
)
OFFICIAL_USER = ActorRef(Platform.QQ_OFFICIAL, "fictional-user", account_id="10001")
GROUPS = (ConversationRef(Platform.ONEBOT, "group", GROUP_ID), OFFICIAL_GROUP)
USERS = (ActorRef(Platform.ONEBOT, USER_ID), OFFICIAL_USER)


def references() -> PlatformReferenceResolver:
    return PlatformReferenceResolver(
        QQReferenceResolver({"room": int(GROUP_ID)}, {"alice": int(USER_ID)}),
        {"room": (OFFICIAL_GROUP,)},
        {"alice": (OFFICIAL_USER,)},
        {"example": "10001"},
    )


@pytest.mark.parametrize(
    "missing", ["retired_link_example", "retired_push_example", "uninstalled_feature"]
)
def test_bundle_skips_only_unregistered_entries_on_both_platforms(
    missing: str, caplog: pytest.LogCaptureFixture
) -> None:
    config = FeatureConfig(
        bundles={"standard": ["help", missing, "seer_player"]},
        group_policy={"room": ["standard"]},
        user_policy={"alice": ["standard"]},
        superuser_bypass=False,
    )
    features = build_feature_service(
        config, (), references=references(), command_features=("web_activity",)
    )

    assert features.configured_feature_keys == frozenset({"help", "seer_player"})
    for group in GROUPS:
        assert features.conversation_has_feature(group, "seer_player")
        assert not features.conversation_has_feature(group, missing)
        assert not features.conversation_has_feature(group, "web_activity")
    for actor in USERS:
        assert features.actor_has_feature(actor, "help")
        assert not features.actor_has_feature(actor, missing)
        assert not features.actor_has_feature(actor, "admin_notice")
    assert "features.bundles.standard[1]" in caplog.text
    assert missing not in caplog.text
    assert config.bundles["standard"] == ["help", missing, "seer_player"]


def test_unregistered_target_permissions_never_enter_policy_facts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = FeatureConfig(
        group_policy={"room": ["missing_group_permission", "seer_player"]},
        user_policy={"alice": ["missing_user_permission", "ai_chat"]},
        superuser_bypass=False,
    )
    features = build_feature_service(config, (), references=references())

    assert features.configured_feature_keys == frozenset({"seer_player", "ai_chat"})
    for group in GROUPS:
        assert features.conversation_has_feature(group, "seer_player")
        assert not features.conversation_has_feature(group, "missing_group_permission")
    for actor in USERS:
        assert features.actor_has_feature(actor, "ai_chat")
        assert not features.actor_has_feature(actor, "missing_user_permission")
    assert "features.group_policy.room[0]" in caplog.text
    assert "features.user_policy.alice[0]" in caplog.text


def test_all_invalid_and_nested_bundles_remain_empty() -> None:
    config = FeatureConfig(
        bundles={"unavailable": ["missing"], "nested": ["unavailable"]},
        group_policy={"room": ["nested", "missing_direct"]},
        user_policy={"alice": ["unavailable"]},
        superuser_bypass=False,
    )
    resolved = resolve_feature_bundles(config.bundles)
    assert resolved["unavailable"] == resolved["nested"] == frozenset()
    features = build_feature_service(config, (), references=references())
    assert features.configured_feature_keys == frozenset()
    assert not features.conversations_for_feature("all")
    for actor in USERS:
        assert not features.actor_has_feature(actor, "admin_notice")


def test_dynamic_features_are_rechecked_without_sticky_ignored_registry() -> None:
    config = FeatureConfig(
        bundles={"optional": ["optional_action"]},
        group_policy={"room": ["optional"]},
    )
    unavailable = build_feature_service(config, (), references=references())
    available = build_feature_service(
        config, (), references=references(), command_features=("optional_action",)
    )
    for group in GROUPS:
        assert not unavailable.conversation_has_feature(group, "optional_action")
        assert available.conversation_has_feature(group, "optional_action")


def test_ignored_permissions_do_not_disable_explicit_blacklist() -> None:
    features = build_feature_service(
        FeatureConfig(
            group_policy={"room": ["help", "missing", "blacklist"]},
            user_policy={"alice": ["admin_notice", "missing"]},
        ),
        (),
        references=references(),
    )
    for group, actor in zip(GROUPS, USERS, strict=True):
        assert features.conversation_has_feature(group, "blacklist")
        assert features.actor_has_feature(actor, "admin_notice")


@pytest.mark.parametrize(
    "bundles,error",
    [
        ({"first": ["missing", "second"], "second": ["first"]}, "cycle"),
        ({"management": ["missing", "admin_notice"]}, "admin_notice"),
        ({"seer": ["missing"]}, "cannot replace"),
        ({"empty": []}, "must not be empty"),
    ],
)
def test_warning_does_not_hide_unsafe_bundle_definitions(
    bundles: dict[str, list[str]], error: str
) -> None:
    with pytest.raises(ValidationError, match=error):
        Settings(features=FeatureConfig(bundles=bundles))


def test_config_cli_accepts_retired_features_without_restoring_old_permissions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ironsbot.toml"
    path.write_text(
        f"""[bot]
driver = "retired"
[features.bundles]
standard = ["seer_player", "retired_link_example", "retired_push_example"]
[features.group_policy]
"{GROUP_ID}" = ["standard", "not_available"]
""",
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("APP_SECRET_", "AI_KEY", "ONEBOT_", "SEER_PASSWORD_"))
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ironsbot.config_check",
            "--no-dotenv",
            "--config",
            str(path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "configuration valid" in result.stdout
    assert "features.bundles.standard[1]" in result.stderr
    assert "features.group_policy" in result.stderr
    assert "Traceback" not in result.stderr
    settings = load_settings(path, env={})
    features = build_feature_service(settings.features, ())
    assert features.configured_feature_keys == frozenset({"seer_player"})
