import sys
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ironsbot"
    / "plugins"
    / "messaging"
    / "runtime_service.py"
)
_SPEC = spec_from_file_location("message_runtime_service_for_test", _SERVICE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SERVICE = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SERVICE
_SPEC.loader.exec_module(_SERVICE)
build_schedule_job_id = _SERVICE.build_schedule_job_id
build_schedule_trigger_kwargs = _SERVICE.build_schedule_trigger_kwargs
command_text_matches = _SERVICE.command_text_matches
find_command_action = _SERVICE.find_command_action


@dataclass(frozen=True, slots=True)
class FakeCommandAction:
    enabled: bool
    commands: list[str]
    feature: str = "text"


@dataclass(frozen=True, slots=True)
class FakeScheduleAction:
    hour: int
    minute: int
    day_of_week: str | None = None


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


def test_build_schedule_job_id_sanitizes_raw_id() -> None:
    assert build_schedule_job_id("group_schedule", 3, "活动 链接!") == (
        "message_action_group_schedule_3"
    )
    assert build_schedule_job_id("private_schedule", 2, "") == (
        "message_action_private_schedule_task_2"
    )


def test_build_schedule_trigger_kwargs_omits_empty_day_of_week() -> None:
    assert build_schedule_trigger_kwargs(FakeScheduleAction(hour=23, minute=5)) == {
        "hour": 23,
        "minute": 5,
        "second": 0,
    }


def test_build_schedule_trigger_kwargs_keeps_day_of_week() -> None:
    assert build_schedule_trigger_kwargs(
        FakeScheduleAction(hour=8, minute=30, day_of_week="fri")
    ) == {
        "hour": 8,
        "minute": 30,
        "second": 0,
        "day_of_week": "fri",
    }
