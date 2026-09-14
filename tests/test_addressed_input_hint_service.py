from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.messaging.addressed_input import AddressedInputHintService


def _context(user: str, group: str) -> MessageInputContext:
    actor = ActorRef(Platform.ONEBOT, user)
    conversation = ConversationRef(Platform.ONEBOT, "group", group)
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.ONEBOT,
            actor=actor,
            conversation=conversation,
            message_id="1",
            text="",
        ),
        mentions_bot=True,
    )


def test_addressed_input_hints_are_limited_per_actor_and_conversation() -> None:
    service = AddressedInputHintService(window_seconds=60, max_per_window=1)

    assert service.admit(_context("1", "10"), now=0)
    assert not service.admit(_context("1", "10"), now=1)
    assert service.admit(_context("2", "10"), now=1)
    assert service.admit(_context("1", "20"), now=1)
    assert service.admit(_context("1", "10"), now=61)
