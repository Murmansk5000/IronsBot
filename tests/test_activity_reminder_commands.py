from ironsbot.config.models.activity import (
    DEFAULT_ACTIVITY_NOTICE_TIMEOUT_SECONDS,
    ActivityConfig,
)
from ironsbot.services.activity.commands import (
    is_current_activity_query_text,
    is_soon_ending_activity_query_text,
)


def test_activity_notice_timeout_lives_in_activity_config() -> None:
    assert (
        ActivityConfig().notice_timeout_seconds
        == DEFAULT_ACTIVITY_NOTICE_TIMEOUT_SECONDS
    )


def test_current_activity_query_requires_command_prefix() -> None:
    assert is_current_activity_query_text("/当前活动")
    assert is_current_activity_query_text("/ 活动列表")
    assert not is_current_activity_query_text("当前活动")


def test_current_activity_query_normalizes_spacing() -> None:
    assert is_current_activity_query_text("/ 活 动 时 间")


def test_soon_ending_activity_query_accepts_bare_text() -> None:
    assert is_soon_ending_activity_query_text("快结束活动")
    assert is_soon_ending_activity_query_text("/快结束活动")


def test_soon_ending_activity_query_normalizes_spacing() -> None:
    assert is_soon_ending_activity_query_text("本 周 活 动")


def test_unrelated_activity_query_text_is_ignored() -> None:
    assert not is_current_activity_query_text("/帮助")
    assert not is_soon_ending_activity_query_text("帮助")
