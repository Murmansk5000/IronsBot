from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.services.messaging.bot_mention_block import BotMentionBlockService


def _service() -> BotMentionBlockService:
    return BotMentionBlockService(CommandCooldownConfig(duplicate_message="重复请求"))


def _actor(value: int) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(value))


def test_bot_mention_block_replies_once_then_warns_once_then_stays_silent() -> None:
    service = _service()

    assert service.admit(_actor(123), now=0).allowed
    assert service.admit(_actor(123), now=1).feedback == "重复请求"
    assert service.admit(_actor(123), now=2).feedback is None
    assert service.admit(_actor(456), now=2).allowed


def test_bot_mention_block_counts_only_initial_replies_in_ten_minute_window() -> None:
    service = _service()

    assert service.admit(_actor(123), now=0).allowed
    assert service.admit(_actor(123), now=1).feedback == "重复请求"
    assert service.admit(_actor(123), now=60).allowed
    assert service.admit(_actor(123), now=120).allowed

    assert service.admit(_actor(123), now=180).feedback is None
    assert service.admit(_actor(123), now=600).allowed


def test_bot_mention_block_keeps_same_id_on_different_platforms_separate() -> None:
    service = _service()
    onebot_actor = ActorRef(Platform.ONEBOT, "123")
    official_actor = ActorRef(Platform.QQ_OFFICIAL, "123")

    assert service.admit(onebot_actor, now=0).allowed
    assert service.admit(official_actor, now=1).allowed
