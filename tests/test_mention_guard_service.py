from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.services.messaging.bot_mention_block import BotMentionBlockService


def _service() -> BotMentionBlockService:
    return BotMentionBlockService(
        CommandCooldownConfig(duplicate_message="重复请求")
    )


def test_bot_mention_block_replies_once_then_warns_once_then_stays_silent() -> None:
    service = _service()

    assert service.admit(123, now=0).allowed
    assert service.admit(123, now=1).feedback == "重复请求"
    assert service.admit(123, now=2).feedback is None
    assert service.admit(456, now=2).allowed


def test_bot_mention_block_counts_only_initial_replies_in_ten_minute_window() -> None:
    service = _service()

    assert service.admit(123, now=0).allowed
    assert service.admit(123, now=1).feedback == "重复请求"
    assert service.admit(123, now=60).allowed
    assert service.admit(123, now=120).allowed

    assert service.admit(123, now=180).feedback is None
    assert service.admit(123, now=600).allowed
