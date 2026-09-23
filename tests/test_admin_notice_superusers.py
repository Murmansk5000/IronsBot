"""Administrator permissions are independent from explicit notice opt-ins."""

from ironsbot.config.models.features import FeatureConfig, build_feature_service
from ironsbot.core.platform import ActorRef, ConversationRef, Platform


def test_multiple_superusers_with_single_explicit_notice_recipient() -> None:
    features = build_feature_service(
        FeatureConfig(user_policy={"111": ["all", "admin_notice"]}), [111, 222]
    )
    owner = ActorRef(Platform.ONEBOT, "111")
    second = ActorRef(Platform.ONEBOT, "222")
    assert features.is_actor_superuser(owner)
    assert features.is_actor_superuser(second)
    assert features.private_admin_notice_actors() == [owner]
    assert features.is_feature_allowed(
        second, ConversationRef(Platform.ONEBOT, "private", "222"), "ai_chat"
    )
    assert second not in features.private_actors_for_feature("bili_push")


def test_all_and_superuser_do_not_opt_in_to_notices() -> None:
    features = build_feature_service(
        FeatureConfig(user_policy={"111": ["all"]}), [111, 222]
    )
    assert features.private_admin_notice_actors() == []
    assert features.is_actor_superuser(ActorRef(Platform.ONEBOT, "222"))


def test_explicit_non_superuser_can_receive_notices_without_operator_access() -> None:
    features = build_feature_service(
        FeatureConfig(user_policy={"333": ["admin_notice"]}), [111]
    )
    recipient = ActorRef(Platform.ONEBOT, "333")
    assert features.private_admin_notice_actors() == [recipient]
    assert not features.is_actor_superuser(recipient)
