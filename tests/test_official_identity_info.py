from __future__ import annotations

import pytest

from ironsbot.config.models.features import (
    FeatureBundleConfigError,
    resolve_feature_bundles,
)
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.official_identity_info import (
    OfficialIdentityInfoError,
    official_identity_info,
    official_identity_info_command_contracts,
)


def _context(
    *,
    group: bool = False,
    platform: Platform = Platform.QQ_OFFICIAL,
) -> MessageInputContext:
    account_id = "example-app" if platform is Platform.QQ_OFFICIAL else None
    conversation = ConversationRef(
        platform,
        "group" if group else "private",
        "group-openid" if group else "user-openid",
        account_id,
    )
    actor = ActorRef(
        platform,
        "member-openid" if group else "user-openid",
        "member" if group else "user",
        "group-openid" if group else None,
        account_id,
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=platform,
            actor=actor,
            conversation=conversation,
            message_id="message-1",
            text="官方身份",
        ),
        mentions_bot=group,
    )


def test_identity_info_is_an_explicit_official_only_command() -> None:
    (command,) = official_identity_info_command_contracts()

    assert command.features_any == ("qq_official_identity_info",)
    assert command.platforms == frozenset({Platform.QQ_OFFICIAL})
    assert "qq_official_identity_info" not in resolve_feature_bundles({})["all"]
    with pytest.raises(FeatureBundleConfigError):
        resolve_feature_bundles({"all": ["qq_official_identity_info"]})


@pytest.mark.asyncio
async def test_private_identity_info_returns_only_the_callers_official_id() -> None:
    reply = await official_identity_info("官方身份", _context())

    assert reply.parts == (
        TextPart(
            "当前官方用户标识：\n"
            "user_openid = user-openid\n"
            "仅用于本机开发配置，请勿公开转发。"
        ),
    )


@pytest.mark.asyncio
async def test_group_identity_info_returns_group_and_scoped_member_ids() -> None:
    reply = await official_identity_info("官方身份", _context(group=True))

    assert reply.parts == (
        TextPart(
            "当前官方群聊标识：\n"
            "group_openid = group-openid\n"
            "member_openid = member-openid\n"
            "仅用于本机开发配置，请勿公开转发。"
        ),
    )


@pytest.mark.asyncio
async def test_identity_info_rejects_non_official_context() -> None:
    with pytest.raises(OfficialIdentityInfoError):
        await official_identity_info(
            "官方身份",
            _context(platform=Platform.ONEBOT),
        )
