from dataclasses import dataclass
from typing import Literal

import pytest
from pydantic import ValidationError

from ironsbot.config.models.messaging import (
    MessageKeywordReplyAction,
    MessageScheduledAction,
)
from ironsbot.core.commands import command_text_matches
from ironsbot.services.messaging.service import (
    build_schedule_job_id,
    build_schedule_trigger_kwargs,
    find_command_action,
    find_keyword_reply_action,
)


@dataclass(slots=True)
class FakeCommandAction:
    enabled: bool
    commands: list[str]
    feature: str = "text"


@dataclass(slots=True)
class FakeScheduleAction:
    time: str
    day_of_week: str | None = None


@dataclass(slots=True)
class FakeKeywordReplyAction:
    enabled: bool
    keywords: list[str]
    feature: str = "text"
    match_mode: Literal["exact", "contains"] = "exact"


def test_command_text_matches_ignores_spacing_and_case() -> None:
    assert command_text_matches(" X R Y M ", ["xrym"])
    assert not command_text_matches("xm2", ["xm"])


def test_find_command_action_skips_disabled_and_disallowed() -> None:
    disabled = FakeCommandAction(enabled=False, commands=["xm"])
    disallowed = FakeCommandAction(enabled=True, commands=["xm"], feature="blocked")
    allowed = FakeCommandAction(enabled=True, commands=["xm"], feature="text")

    assert (
        find_command_action(
            "xm",
            [disabled, disallowed, allowed],
            is_allowed=lambda action: action.feature == "text",
        )
        is allowed
    )


def test_find_keyword_reply_action_uses_complete_normalized_text() -> None:
    disabled = FakeKeywordReplyAction(enabled=False, keywords=["出出"])
    disallowed = FakeKeywordReplyAction(
        enabled=True,
        keywords=["出出"],
        feature="blocked",
    )
    allowed = FakeKeywordReplyAction(enabled=True, keywords=["出出"])

    assert (
        find_keyword_reply_action(
            "出 出",
            [disabled, disallowed, allowed],
            is_allowed=lambda action: action.feature == "text",
        )
        is allowed
    )
    assert (
        find_keyword_reply_action(
            "今天出出了",
            [allowed],
            is_allowed=lambda _action: True,
        )
        is None
    )


def test_build_schedule_job_id_sanitizes_raw_id() -> None:
    assert build_schedule_job_id("group_schedule", 3, "活动 链接!") == (
        "group_schedule_3"
    )
    assert build_schedule_job_id("private_schedule", 2, "") == (
        "private_schedule_task_2"
    )


@pytest.mark.parametrize("text", ["看看 X M 胜率榜", "xm胜率榜", "前缀XM胜率榜后缀"])
def test_contains_keyword_uses_normalized_whole_message(text: str) -> None:
    action = FakeKeywordReplyAction(
        enabled=True, keywords=["XM胜率榜"], match_mode="contains"
    )
    assert (
        find_keyword_reply_action(text, [action], is_allowed=lambda _: True) is action
    )


@pytest.mark.parametrize("text", ["", "   ", "ordinary message"])
def test_empty_contains_keywords_never_match(text: str) -> None:
    action = FakeKeywordReplyAction(
        enabled=True, keywords=["", " \t"], match_mode="contains"
    )
    assert find_keyword_reply_action(text, [action], is_allowed=lambda _: True) is None


def test_contains_preserves_order_and_skips_disabled_or_denied() -> None:
    disabled = FakeKeywordReplyAction(
        enabled=False, keywords=["榜"], match_mode="contains"
    )
    denied = FakeKeywordReplyAction(
        enabled=True, keywords=["榜"], feature="blocked", match_mode="contains"
    )
    first = FakeKeywordReplyAction(
        enabled=True, keywords=["胜率榜"], match_mode="contains"
    )
    second = FakeKeywordReplyAction(
        enabled=True, keywords=["竞技"], match_mode="contains"
    )
    assert (
        find_keyword_reply_action(
            "看看竞技胜率榜",
            [disabled, denied, first, second],
            is_allowed=lambda action: action.feature != "blocked",
        )
        is first
    )


def test_keyword_match_mode_defaults_and_validation() -> None:
    fields = {"id": "example", "keywords": ["test"], "messages": ["reply"]}
    assert MessageKeywordReplyAction.model_validate(fields).match_mode == "exact"
    assert (
        MessageKeywordReplyAction.model_validate(
            {**fields, "match_mode": "contains"}
        ).match_mode
        == "contains"
    )
    for invalid in ("partial", "CONTAINS", "", True, 1, None):
        with pytest.raises(ValidationError):
            MessageKeywordReplyAction.model_validate({**fields, "match_mode": invalid})


def test_build_schedule_trigger_kwargs_omits_empty_day_of_week() -> None:
    assert build_schedule_trigger_kwargs(FakeScheduleAction(time="23:05")) == {
        "hour": 23,
        "minute": 5,
        "second": 0,
    }


def test_build_schedule_trigger_kwargs_keeps_day_of_week() -> None:
    assert build_schedule_trigger_kwargs(
        FakeScheduleAction(time="08:30", day_of_week="fri")
    ) == {
        "hour": 8,
        "minute": 30,
        "second": 0,
        "day_of_week": "fri",
    }


def test_build_schedule_trigger_kwargs_preserves_seconds() -> None:
    assert build_schedule_trigger_kwargs(FakeScheduleAction(time="08:30:45")) == {
        "hour": 8,
        "minute": 30,
        "second": 45,
    }


def test_scheduled_action_normalizes_minute_input_with_seconds() -> None:
    assert (
        MessageScheduledAction(id="daily", messages=["text"], time="08:30").time
        == "08:30:00"
    )
    assert (
        MessageScheduledAction(id="precise", messages=["text"], time="08:30:45").time
        == "08:30:45"
    )
