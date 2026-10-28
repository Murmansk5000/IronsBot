from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ironsbot.config.loader import load_settings
from ironsbot.config.models.messaging import MessageAction, MessageConfig
from ironsbot.services.messaging.command_contracts import messaging_command_contracts
from ironsbot.services.messaging.subscription_options import schedule_key

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "triggers",
    [
        {"commands": ["活动", "签到"]},
        {"keywords": ["活动"], "match_mode": "contains"},
        {"time": "23:00"},
        {"commands": ["活动", "签到"], "keywords": ["提醒"], "time": "23:00"},
    ],
)
def test_message_trigger_projections_share_one_definition(triggers: dict) -> None:
    config = MessageConfig.model_validate(
        {"messages": [{"id": "activity", "messages": ["正文"], **triggers}]}
    )
    message = config.messages[0]
    for projection in (
        config.command_actions,
        config.keyword_actions,
        config.scheduled_actions,
    ):
        if projection:
            assert projection[0] is message
    assert bool(config.command_actions) == bool(triggers.get("commands"))
    assert bool(config.keyword_actions) == bool(triggers.get("keywords"))
    assert bool(config.scheduled_actions) == bool(triggers.get("time"))


def test_recursive_variables_preserve_message_boundaries_and_private_placeholders() -> (
    None
):
    config = MessageConfig.model_validate(
        {
            "variables": {
                "domain": "https://example.invalid",
                "page": "${domain}/peak/pvprank/master/monster",
            },
            "messages": [
                {
                    "id": "activity",
                    "feature": "web_activity",
                    "commands": ["活动", "签到"],
                    "time": "23:00",
                    "subscription_id": "web_activity_push",
                    "messages": ["活动\n${page}", "还有 {days} 天"],
                }
            ],
        }
    )
    action = config.messages[0]
    assert action.messages == [
        "活动\nhttps://example.invalid/peak/pvprank/master/monster",
        "还有 {days} 天",
    ]
    assert schedule_key(1, action) == "web_activity_push"
    assert {
        contract.features_any for contract in messaging_command_contracts(config)
    } >= {("web_activity",)}
    assert (
        config.command_feature_keys == config.schedule_feature_keys == {"web_activity"}
    )


@pytest.mark.parametrize(
    ("variables", "message", "reason"),
    [
        ({}, "${missing}", "unknown messaging variable"),
        ({}, "${}", "unknown messaging variable"),
        ({"first": "${second}", "second": "${first}"}, "ok", "cyclic"),
        ({"first": "${first}"}, "ok", "cyclic"),
        ({"unused": "${missing}"}, "ok", "unknown messaging variable"),
        ({"empty": " "}, "${empty}", "must not be empty"),
        ({"invalid-name": "text"}, "ok", "invalid messaging variable name"),
        ({"number": 123}, "ok", "valid string"),
    ],
)
def test_invalid_variables_fail_validation(
    variables: dict, message: str, reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        MessageConfig.model_validate(
            {
                "variables": variables,
                "messages": [
                    {"id": "test", "commands": ["test"], "messages": [message]}
                ],
            }
        )


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"commands": ["test"], "target_groups": []},
        {"commands": ["test"], "day_of_week": "fri"},
        {"commands": ["test"], "subscription_id": "old"},
        {"commands": ["test"], "renderer": "private.exam"},
        {"commands": ["test"], "renderer_parameters": {}},
        {"commands": ["test"], "unresolved_mentions": "skip"},
        {"commands": ["test"], "mention_fallback_name": "Example"},
        {"commands": ["test"], "match_mode": "contains"},
        {"time": "25:00"},
        {"time": ""},
        {"time": "23:00", "subscription_id": "not stable"},
        {"commands": ["test"], "feature": "web_activity_link"},
        {"commands": ["test"], "feature": "web_activity_push"},
    ],
)
def test_invalid_message_combinations_are_rejected(fields: dict) -> None:
    with pytest.raises(ValidationError):
        MessageAction.model_validate({"id": "test", "messages": ["reply"], **fields})


@pytest.mark.parametrize("duplicate_subscription", [False, True])
def test_ids_and_subscription_keys_are_unique(*, duplicate_subscription: bool) -> None:
    first = {"id": "one", "messages": ["one"], "time": "12:00"}
    second = {
        "id": "two" if duplicate_subscription else "one",
        "messages": ["two"],
        "time": "13:00",
    }
    if duplicate_subscription:
        second["subscription_id"] = "one"
    with pytest.raises(ValidationError):
        MessageConfig.model_validate({"messages": [first, second]})


def test_retired_config_warns_without_registering_old_triggers(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[[messaging.commands]]
id = "old_command"
commands = ["old"]
messages = ["old reply"]
[[messaging.keyword_replies]]
id = "old_keyword"
keywords = ["old"]
messages = ["old reply"]
[[messaging.schedules]]
id = "old_schedule"
time = "23:00"
messages = ["old push"]
[[messaging.messages]]
id = "new"
commands = ["new"]
messages = ["new reply"]
""",
        encoding="utf-8",
    )
    config = load_settings(path, env={}).messaging
    assert [action.id for action in config.messages] == ["new"]
    assert config.scheduled_actions == ()
    for field in ("commands", "keyword_replies", "schedules"):
        assert f"messaging.{field}" in caplog.text
        assert not hasattr(config, field)


def test_new_configuration_errors_are_not_silenced_by_unknown_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[messaging]
unknown_field = true
[[messaging.messages]]
id = "new"
commands = ["new"]
messages = ["${missing}"]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="unknown messaging variable"):
        load_settings(path, env={})
