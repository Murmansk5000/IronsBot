from ironsbot.config.models.activity import (
    DEFAULT_ACTIVITY_NOTICE_TIMEOUT_SECONDS,
    ActivityConfig,
)
from ironsbot.services.activity.commands import (
    is_current_seer_activity_text,
    is_new_seer_activity_text,
    is_soon_ending_seer_activity_text,
)


def test_activity_notice_timeout_lives_in_activity_config() -> None:
    assert (
        ActivityConfig().notice_timeout_seconds
        == DEFAULT_ACTIVITY_NOTICE_TIMEOUT_SECONDS
    )


def test_current_seer_activity_requires_command_prefix() -> None:
    assert is_current_seer_activity_text("/当前活动")
    assert is_current_seer_activity_text("/ 活动列表")
    assert not is_current_seer_activity_text("当前活动")


def test_current_seer_activity_normalizes_spacing() -> None:
    assert is_current_seer_activity_text("/ 活 动 时 间")


def test_soon_ending_seer_activity_accepts_bare_text() -> None:
    assert is_soon_ending_seer_activity_text("快结束活动")
    assert is_soon_ending_seer_activity_text("/快结束活动")


def test_soon_ending_seer_activity_normalizes_spacing() -> None:
    assert is_soon_ending_seer_activity_text("本 周 活 动")


def test_new_seer_activity_uses_its_own_command() -> None:
    assert is_new_seer_activity_text("新增活动")
    assert is_new_seer_activity_text("/新增活动")
    assert not is_soon_ending_seer_activity_text("新增活动")


def test_unrelated_seer_activity_text_is_ignored() -> None:
    assert not is_current_seer_activity_text("/帮助")
    assert not is_soon_ending_seer_activity_text("帮助")
