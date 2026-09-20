from __future__ import annotations

from ironsbot.core.platform_selection import (
    OutboundPlatform,
    OutboundPlatformSelection,
)


def test_official_credentials_always_take_exclusive_outbound_ownership() -> None:
    selection = OutboundPlatformSelection.resolve(
        official_account_aliases=("local_bot",),
        onebot_enabled=True,
        onebot_send_messages=True,
    )

    assert selection.platform is OutboundPlatform.QQ_OFFICIAL
    assert selection.official_active
    assert not selection.onebot_outbound_enabled
    assert not selection.onebot_message_handling_enabled


def test_onebot_is_fallback_only_without_official_credentials() -> None:
    selection = OutboundPlatformSelection.resolve(
        official_account_aliases=(),
        onebot_enabled=True,
        onebot_send_messages=True,
    )

    assert selection.platform is OutboundPlatform.ONEBOT
    assert selection.onebot_outbound_enabled


def test_no_platform_is_selected_when_onebot_sending_is_disabled() -> None:
    selection = OutboundPlatformSelection.resolve(
        official_account_aliases=(),
        onebot_enabled=True,
        onebot_send_messages=False,
    )

    assert selection.platform is OutboundPlatform.NONE
