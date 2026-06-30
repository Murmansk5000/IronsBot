from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from pytest import MonkeyPatch

from ironsbot.config.models.ai import AiIntentAction
from ironsbot.services.ai import intent


def test_intent_reply_yes_parser_accepts_short_yes_forms() -> None:
    assert intent.reply_is_yes(" yes.")
    assert intent.reply_is_yes("是")
    assert intent.reply_is_yes("符合\nreason")
    assert not intent.reply_is_yes("no")


def test_intent_template_preserves_unknown_fields() -> None:
    action = AiIntentAction(
        id="unit",
        keywords=["战队"],
        action="message",
        message="ok",
        intent="join",
    )

    assert (
        intent.format_action_template(
            action,
            "{action_id}:{feature}:{intent}:{keywords}:{message}:{missing}",
            "我要加战队",
        )
        == "unit:ai_intent:join:战队:我要加战队:{missing}"
    )


def test_intent_keyword_match_normalizes_text() -> None:
    assert intent.contains_any_keyword("我要 加 战队", ["加战队"])


def test_fire_manual_announcement_or_share_is_not_request() -> None:
    text = "火火手册正式版已发布：http删s:/掉/seerin这fo.几yuyuqaq.个cn/字firedict"
    action = AiIntentAction(
        id="manual",
        feature="fire_manual",
        keywords=["手册"],
        action="message",
        message="ok",
        intent="manual",
    )

    assert intent.contains_any_keyword(text, action.keywords)
    assert intent.excluded_by_context(text, action)


def test_fire_manual_request_is_not_context_excluded() -> None:
    action = AiIntentAction(
        id="manual",
        feature="fire_manual",
        keywords=["手册"],
        action="message",
        message="ok",
        intent="manual",
    )

    assert not intent.excluded_by_context("手册在哪", action)
    assert not intent.excluded_by_context("求火火手册链接", action)


def test_fire_manual_action_requires_group_feature(monkeypatch: MonkeyPatch) -> None:
    event = GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=2,
        message_type="group",
        message_id=3,
        message=Message("手册在哪"),
        original_message=Message("手册在哪"),
        raw_message="手册在哪",
        font=0,
        group_id=4,
        sender={},
    )
    action = AiIntentAction(
        id="manual",
        feature="fire_manual",
        keywords=["手册"],
        action="message",
        message="ok",
        intent="manual",
    )
    monkeypatch.setattr(intent, "group_has_feature", lambda _group_id, _feature: False)
    monkeypatch.setattr(
        intent,
        "is_group_feature_allowed",
        lambda _user_id, _group_id, _feature: True,
    )

    assert not intent.is_action_allowed(event, action)
