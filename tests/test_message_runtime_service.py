from dataclasses import dataclass

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


def test_command_text_matches_ignores_spacing_and_case() -> None:
    assert command_text_matches(" X R Y M ", ["xrym"])
    assert not command_text_matches("xm2", ["xm"])


def test_find_command_action_skips_disabled_and_disallowed() -> None:
    disabled = FakeCommandAction(enabled=False, commands=["xm"])
    disallowed = FakeCommandAction(enabled=True, commands=["xm"], feature="blocked")
    allowed = FakeCommandAction(enabled=True, commands=["xm"], feature="text")

    assert find_command_action(
        "xm",
        [disabled, disallowed, allowed],
        is_allowed=lambda action: action.feature == "text",
    ) is allowed


def test_find_keyword_reply_action_uses_literal_contains_matching() -> None:
    disabled = FakeKeywordReplyAction(enabled=False, keywords=["出出"])
    disallowed = FakeKeywordReplyAction(
        enabled=True,
        keywords=["出出"],
        feature="blocked",
    )
    allowed = FakeKeywordReplyAction(enabled=True, keywords=["出出"])

    assert find_keyword_reply_action(
        "今天出出了",
        [disabled, disallowed, allowed],
        is_allowed=lambda action: action.feature == "text",
    ) is allowed
    assert (
        find_keyword_reply_action(
            "今天出去玩",
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
