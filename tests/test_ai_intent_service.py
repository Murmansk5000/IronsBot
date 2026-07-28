from collections.abc import Awaitable, Callable

import pytest

from ironsbot.config.models.ai import AiConfig
from ironsbot.core.features import FeatureConfig
from ironsbot.core.messaging import AiIntentAction
from ironsbot.services.ai import intent
from ironsbot.services.ai.history import HistoryMessage
from ironsbot.services.ai.responses import AiResponseResult
from ironsbot.services.ai.service import AiService
from tests.helpers.ai import FakeAiCompletionClient
from tests.helpers.runtime import build_test_runtime

CompletionRequester = Callable[
    [AiConfig, list[HistoryMessage]],
    Awaitable[AiResponseResult],
]


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


def _manual_action() -> AiIntentAction:
    return AiIntentAction(
        id="fire_manual",
        feature="ai_intent_fire_manual",
        keywords=["手册"],
        action="message",
        message="ok",
        intent="manual",
    )


def test_fire_manual_announcement_or_share_is_not_request() -> None:
    text = "火火手册正式版已发布：http删s:/掉/seerin这fo.几yuyuqaq.个cn/字firedict"
    action = _manual_action()

    assert intent.contains_any_keyword(text, action.keywords)
    assert intent.excluded_by_context(text, action)


def test_fire_manual_request_is_not_context_excluded() -> None:
    action = _manual_action()

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
    team_action = AiIntentAction(
        id="team",
        feature="ai_intent",
        keywords=["战队"],
        action="message",
        message="ok",
        intent="team",
    )

    assert not intent.passes_action_prefilter("火火手册", _manual_action())
    assert intent.passes_action_prefilter("求火火手册", _manual_action())
    assert intent.passes_action_prefilter("战队", team_action)


def _runtime(
    action: AiIntentAction,
    *allowed_features: str,
    superuser_bypass: bool = False,
    superuser_ids: tuple[int, ...] = (),
):
    enabled = allowed_features or ("ai_intent", action.feature)
    return build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={"4": list(dict.fromkeys(enabled))},
            superuser_bypass=superuser_bypass,
        ),
        superuser_ids=superuser_ids,
    )


async def _yes_completion(
    _config: AiConfig,
    _messages: list[HistoryMessage],
) -> AiResponseResult:
    return AiResponseResult(status_code=200, reply="yes")


def _service(
    action: AiIntentAction,
    *allowed_features: str,
    request_completion: CompletionRequester = _yes_completion,
) -> AiService:
    config = AiConfig(
        api_key="key",
        memory=False,
        intent_actions={action.id: action},
    )
    runtime = _runtime(action, *allowed_features)
    return AiService(
        config,
        runtime.features,
        runtime.admin_notices,
        ("战队",),
        FakeAiCompletionClient(config, request_completion),
    )


def test_fire_manual_action_requires_group_feature() -> None:
    action = _manual_action()
    runtime = _runtime(action, "ai_intent")

    assert not intent.is_action_allowed(runtime.features, 2, 4, action)


def test_fire_manual_action_allows_superuser_bypass() -> None:
    action = _manual_action()
    runtime = _runtime(
        action,
        "ai_intent",
        superuser_bypass=True,
        superuser_ids=(2,),
    )

    assert intent.is_action_allowed(runtime.features, 2, 4, action)


@pytest.mark.asyncio
async def test_fire_manual_weak_intent_does_not_call_ai() -> None:
    called = False

    async def request_completion(
        _config: AiConfig,
        _messages: list[HistoryMessage],
    ) -> AiResponseResult:
        nonlocal called
        called = True
        return AiResponseResult(status_code=200, reply="yes")

    matched = await _service(
        _manual_action(),
        request_completion=request_completion,
    ).classify_intent(
        "我是抄火火手册里面说的。",
        user_id=2,
        group_id=4,
    )

    assert matched is None
    assert not called


@pytest.mark.asyncio
async def test_ai_intent_feature_gate_blocks_action_specific_feature() -> None:
    called = False
    action = AiIntentAction(
        id="team_recommend",
        feature="ai_intent_team_recommend",
        keywords=["战队"],
        action="team_recommend",
        messages=["审核群链接", "审核群号"],
        intent="team",
    )

    async def request_completion(
        _config: AiConfig,
        _messages: list[HistoryMessage],
    ) -> AiResponseResult:
        nonlocal called
        called = True
        return AiResponseResult(status_code=200, reply="yes")

    matched = await _service(
        action,
        action.feature,
        request_completion=request_completion,
    ).classify_intent(
        "战队",
        user_id=2,
        group_id=4,
    )

    assert matched is None
    assert not called


@pytest.mark.asyncio
async def test_fire_manual_strong_intent_calls_ai_and_matches() -> None:
    prompts: list[str] = []

    async def request_completion(
        _config: AiConfig,
        messages: list[HistoryMessage],
    ) -> AiResponseResult:
        prompts.append(messages[-1]["content"])
        return AiResponseResult(status_code=200, reply="yes")

    action = _manual_action()
    matched = await _service(
        action,
        request_completion=request_completion,
    ).classify_intent(
        "求火火手册链接",
        user_id=2,
        group_id=4,
    )

    assert matched == action
    assert prompts


@pytest.mark.asyncio
async def test_fire_manual_strong_intent_respects_ai_no() -> None:
    async def request_completion(
        _config: AiConfig,
        _messages: list[HistoryMessage],
    ) -> AiResponseResult:
        return AiResponseResult(status_code=200, reply="no")

    matched = await _service(
        _manual_action(),
        request_completion=request_completion,
    ).classify_intent(
        "求火火手册链接",
        user_id=2,
        group_id=4,
    )

    assert matched is None
