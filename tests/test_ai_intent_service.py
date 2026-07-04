from types import SimpleNamespace

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from pytest import MonkeyPatch

from ironsbot.config.models.ai import AiIntentAction
from ironsbot.services.ai import intent

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

try:
    nonebot.load_plugin("ironsbot.plugins.ai_intent")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.plugins import ai_intent as ai_intent_plugin


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


def test_fire_manual_strong_request_prefilter_accepts_explicit_requests() -> None:
    accepted = [
        "火火手册链接",
        "手册在哪",
        "求火火手册",
        "发我手册链接",
        "火火手册怎么下载",
        "我要这个地球上最牛逼的赛尔号手册-火火手册",
    ]

    for text in accepted:
        assert intent.has_fire_manual_strong_request(text), text


def test_fire_manual_strong_request_prefilter_rejects_weak_mentions() -> None:
    rejected = [
        "火火手册",
        "手册",
        "我是抄火火手册里面说的。",
        "我这周火火手册怎么更新不了",
        "火火手册正式版已发布：http删s:/掉/seerin这fo.几yuyuqaq.个cn/字firedict",
    ]

    for text in rejected:
        assert not intent.has_fire_manual_strong_request(text), text


def test_fire_manual_action_prefilter_is_feature_specific() -> None:
    manual_action = AiIntentAction(
        id="manual",
        feature="fire_manual",
        keywords=["手册"],
        action="message",
        message="ok",
        intent="manual",
    )
    team_action = AiIntentAction(
        id="team",
        feature="ai_intent",
        keywords=["战队"],
        action="message",
        message="ok",
        intent="team",
    )

    assert not intent.passes_action_prefilter("火火手册", manual_action)
    assert intent.passes_action_prefilter("求火火手册", manual_action)
    assert intent.passes_action_prefilter("战队", team_action)


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


def _group_event(text: str) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=2,
        message_type="group",
        message_id=3,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        group_id=4,
        sender={},
    )


def _ai_intent_enabled_config() -> SimpleNamespace:
    return SimpleNamespace(intent_actions_enabled=True)


@pytest.mark.asyncio
async def test_fire_manual_weak_intent_does_not_call_ai(
    monkeypatch: MonkeyPatch,
) -> None:
    called = False
    action = AiIntentAction(
        id="fire_manual",
        feature="fire_manual",
        keywords=["手册"],
        action="message",
        message="ok",
        intent="manual",
    )

    async def fake_call_ai_chat(_prompt: str, _history: list[object]) -> str:
        nonlocal called
        called = True
        return "yes"

    monkeypatch.setattr(
        ai_intent_plugin,
        "get_configured_actions",
        lambda: [action],
    )
    monkeypatch.setattr(
        ai_intent_plugin,
        "get_ai_intent_config",
        _ai_intent_enabled_config,
    )
    monkeypatch.setattr(ai_intent_plugin, "get_ai_key", lambda: "key")
    monkeypatch.setattr(ai_intent_plugin, "is_action_allowed", lambda *_args: True)
    monkeypatch.setattr(ai_intent_plugin, "call_ai_chat", fake_call_ai_chat)

    matched = await ai_intent_plugin._match_ai_intent_action(
        _group_event("我是抄火火手册里面说的。"),
        {},
    )

    assert not matched
    assert not called


@pytest.mark.asyncio
async def test_fire_manual_strong_intent_calls_ai_and_matches(
    monkeypatch: MonkeyPatch,
) -> None:
    prompts: list[str] = []
    state: dict[str, object] = {}
    action = AiIntentAction(
        id="fire_manual",
        feature="fire_manual",
        keywords=["手册"],
        action="message",
        message="ok",
        intent="manual",
    )

    async def fake_call_ai_chat(prompt: str, _history: list[object]) -> str:
        prompts.append(prompt)
        return "yes"

    monkeypatch.setattr(
        ai_intent_plugin,
        "get_configured_actions",
        lambda: [action],
    )
    monkeypatch.setattr(
        ai_intent_plugin,
        "get_ai_intent_config",
        _ai_intent_enabled_config,
    )
    monkeypatch.setattr(ai_intent_plugin, "get_ai_key", lambda: "key")
    monkeypatch.setattr(ai_intent_plugin, "is_action_allowed", lambda *_args: True)
    monkeypatch.setattr(ai_intent_plugin, "call_ai_chat", fake_call_ai_chat)

    matched = await ai_intent_plugin._match_ai_intent_action(
        _group_event("求火火手册链接"),
        state,
    )

    assert matched
    assert prompts
    assert state[ai_intent_plugin.ACTION_KEY] is action


@pytest.mark.asyncio
async def test_fire_manual_strong_intent_respects_ai_no(
    monkeypatch: MonkeyPatch,
) -> None:
    state: dict[str, object] = {}
    action = AiIntentAction(
        id="fire_manual",
        feature="fire_manual",
        keywords=["手册"],
        action="message",
        message="ok",
        intent="manual",
    )

    async def fake_call_ai_chat(_prompt: str, _history: list[object]) -> str:
        return "no"

    monkeypatch.setattr(
        ai_intent_plugin,
        "get_configured_actions",
        lambda: [action],
    )
    monkeypatch.setattr(
        ai_intent_plugin,
        "get_ai_intent_config",
        _ai_intent_enabled_config,
    )
    monkeypatch.setattr(ai_intent_plugin, "get_ai_key", lambda: "key")
    monkeypatch.setattr(ai_intent_plugin, "is_action_allowed", lambda *_args: True)
    monkeypatch.setattr(ai_intent_plugin, "call_ai_chat", fake_call_ai_chat)

    matched = await ai_intent_plugin._match_ai_intent_action(
        _group_event("求火火手册链接"),
        state,
    )

    assert not matched
    assert ai_intent_plugin.ACTION_KEY not in state
