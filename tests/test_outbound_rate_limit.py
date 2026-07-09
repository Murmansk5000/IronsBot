from pytest import MonkeyPatch

from ironsbot.config.models.message import OutboundRateLimitConfig
from ironsbot.shared.messaging import outbound_rate_limit
from ironsbot.shared.messaging.outbound_rate_limit import (
    check_group_outbound_rate_limit,
    reset_outbound_rate_limit_state,
)
from tests.helpers.config import stub_app_config

GROUP_ID = 100
ADMIN_GROUP_ID = 200


def _set_config(
    monkeypatch: MonkeyPatch,
    *,
    max_messages: int = 3,
    window_seconds: float = 60.0,
) -> None:
    monkeypatch.setattr(
        outbound_rate_limit,
        "get_app_config",
        lambda: stub_app_config(
            outbound_rate_limit_config=OutboundRateLimitConfig(
                enabled=True,
                window_seconds=window_seconds,
                max_messages=max_messages,
                cooldown_message="进入冷却",
            )
        ),
    )
    monkeypatch.setattr(
        outbound_rate_limit,
        "_is_limited_group",
        lambda group_id: group_id != ADMIN_GROUP_ID,
    )


def test_outbound_rate_limit_allows_last_message_with_cooldown_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    reset_outbound_rate_limit_state()
    _set_config(monkeypatch)

    first = check_group_outbound_rate_limit(GROUP_ID, now=0)
    second = check_group_outbound_rate_limit(GROUP_ID, now=1)
    third = check_group_outbound_rate_limit(GROUP_ID, now=2)
    fourth = check_group_outbound_rate_limit(GROUP_ID, now=3)

    assert first.allowed and first.cooldown_message is None
    assert second.allowed and second.cooldown_message is None
    assert third.allowed and third.cooldown_message == "进入冷却"
    assert not fourth.allowed


def test_outbound_rate_limit_ignores_admin_groups_and_private_targets(
    monkeypatch: MonkeyPatch,
) -> None:
    reset_outbound_rate_limit_state()
    _set_config(monkeypatch, max_messages=1)

    assert check_group_outbound_rate_limit(None, now=0).allowed
    assert check_group_outbound_rate_limit(None, now=1).allowed
    assert check_group_outbound_rate_limit(ADMIN_GROUP_ID, now=0).allowed
    assert check_group_outbound_rate_limit(ADMIN_GROUP_ID, now=1).allowed


def test_outbound_rate_limit_sliding_window(monkeypatch: MonkeyPatch) -> None:
    reset_outbound_rate_limit_state()
    _set_config(monkeypatch, max_messages=2, window_seconds=10.0)

    assert check_group_outbound_rate_limit(GROUP_ID, now=0).allowed
    assert check_group_outbound_rate_limit(GROUP_ID, now=1).cooldown_message == (
        "进入冷却"
    )
    assert not check_group_outbound_rate_limit(GROUP_ID, now=2).allowed
    assert check_group_outbound_rate_limit(GROUP_ID, now=11).allowed
