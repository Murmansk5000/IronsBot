from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.runtime.onebot_identity import onebot_actor_ref, onebot_conversation_ref


def test_onebot_identity_helpers_build_typed_references() -> None:
    actor = onebot_actor_ref(123)

    assert actor == ActorRef(Platform.ONEBOT, "123")
    assert onebot_conversation_ref(123) == ConversationRef(
        Platform.ONEBOT,
        "private",
        "123",
    )
    assert onebot_conversation_ref(123, group_id=456) == ConversationRef(
        Platform.ONEBOT,
        "group",
        "456",
    )
