from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core.bilibili import truncate_bilibili_text
from ironsbot.core.features import FeatureConfig
from ironsbot.core.messaging import (
    FIRE_MANUAL_LINK_MESSAGE,
    MessageTarget,
    TargetSendSummary,
)
from ironsbot.integrations.onebot.promotions import append_fire_manual_ad_for_target
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.plugins.bilibili.delivery import (
    build_dynamic_content_message,
    build_dynamic_link_message,
)
from ironsbot.runtime.replies import append_text_hint
from ironsbot.services.bilibili.delivery import (
    BILI_PUSH_ADMIN_HINT,
    BILIBILI_SUMMARY_FAILURE_ACTION,
    BILIBILI_SUMMARY_MAX_ATTEMPTS,
    DYNAMIC_HISTORY_HINT,
    FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS,
    FULL_DYNAMIC_PUSH_ACTION,
    LINK_DYNAMIC_PUSH_ACTION,
    BilibiliPushDeliveryService,
)
from ironsbot.services.bilibili.preferences import bili_push_subscription_key
from ironsbot.services.bilibili.targets import BiliPushTargets
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.features import FeatureService
    from ironsbot.services.messaging.delivery import MessageDelivery
    from ironsbot.services.messaging.subscriptions import (
        PushSubscriptionRepository,
    )

PUB_TS = 1781004683
EXPECTED_FULL_PUSH_COUNT = 2
EXPECTED_RETRIED_CONTENT_PUSH_COUNT = 2
QUERY_ENABLED_GROUP_ID = 1001


def _item(
    *,
    text: str = "这是一条普通动态，正文内容应该只在全文模式里出现",
) -> dict[str, Any]:
    return {
        "id_str": "1211894957538803730",
        "modules": {
            "module_author": {
                "mid": 1310714247,
                "name": "赛尔号",
                "pub_ts": PUB_TS,
            },
            "module_dynamic": {
                "major": {
                    "opus": {
                        "summary": {"text": text},
                        "pics": [
                            {"url": "http://i0.hdslb.com/bfs/new_dyn/test.jpg]"}
                        ],
                    }
                }
            },
        },
    }


def _delivery_service(
    features: FeatureService,
    subscriptions: PushSubscriptionRepository | None = None,
) -> BilibiliPushDeliveryService:
    return BilibiliPushDeliveryService(
        cast("MessageDelivery", object()),
        subscriptions or cast("PushSubscriptionRepository", object()),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        partial(append_fire_manual_ad_for_target, features),
    )


def test_dynamic_renderers_split_link_from_compact_content() -> None:
    link_rendered = str(build_dynamic_link_message(_item(), PUB_TS))
    content_rendered = str(build_dynamic_content_message(_item()))

    assert "传送门：" in link_rendered
    assert "正文内容" not in link_rendered
    assert "【赛尔号】发布了一条B站动态" in link_rendered
    assert "UID：1310714247" in link_rendered
    assert "正文内容" in content_rendered
    assert "[CQ:image" in content_rendered
    assert "传送门:" not in content_rendered
    assert "账号：" not in content_rendered


def test_delivery_service_appends_fire_manual_ad_per_target(
    tmp_path: Path,
) -> None:
    service = _delivery_service(
        build_test_runtime(
            feature_config=FeatureConfig(
                group_policy={"1001": ["fire_manual_ad"]},
                user_policy={"2001": ["fire_manual_ad"]},
            )
        ).features,
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
    )

    assert FIRE_MANUAL_LINK_MESSAGE in str(
        service._transform_target_message("正文", MessageTarget("group", 1001))
    )
    assert FIRE_MANUAL_LINK_MESSAGE not in str(
        service._transform_target_message("正文", MessageTarget("group", 1002))
    )
    assert FIRE_MANUAL_LINK_MESSAGE in str(
        service._transform_target_message("正文", MessageTarget("private", 2001))
    )
    assert FIRE_MANUAL_LINK_MESSAGE not in str(
        service._transform_target_message("正文", MessageTarget("private", 2002))
    )


def test_delivery_service_only_appends_history_hint_for_query_targets(
    tmp_path: Path,
) -> None:
    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", object()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        can_query_history=lambda target: target.target_id == QUERY_ENABLED_GROUP_ID,
    )

    assert DYNAMIC_HISTORY_HINT in str(
        service._transform_target_message(
            "正文",
            MessageTarget("group", QUERY_ENABLED_GROUP_ID),
        )
    )
    assert DYNAMIC_HISTORY_HINT not in str(
        service._transform_target_message("正文", MessageTarget("group", 1002))
    )


@pytest.mark.asyncio
async def test_full_dynamic_always_sends_link_then_compact_content(
    tmp_path: Path,
) -> None:
    sent: list[dict[str, Any]] = []
    summaries: list[tuple[str, int]] = []

    class RecordingDelivery:
        async def broadcast(
            self,
            message: object,
            **kwargs: object,
        ) -> TargetSendSummary:
            sent.append({"message": message, **kwargs})
            return TargetSendSummary([], [])

    async def summarize(text: str, *, max_chars: int) -> str:
        summaries.append((text, max_chars))
        return "这是忠实摘要。"

    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", RecordingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        None,
        summarize=summarize,
        content_max_chars=10,
        summary_max_chars=8,
    )

    await service.send(
        _item(text="这是一条超过十个字符的长动态正文，用于验证统一摘要投递。"),
        PUB_TS,
        1310714247,
        BiliPushTargets(
            full_group_ids=[1001],
            link_group_ids=[1002],
            full_user_ids=[],
            link_user_ids=[],
        ),
    )

    assert summaries == [
        ("这是一条超过十个字符的长动态正文，用于验证统一摘要投递。", 8)
    ]
    assert [entry["action_name"] for entry in sent] == [
        LINK_DYNAMIC_PUSH_ACTION,
        f"{FULL_DYNAMIC_PUSH_ACTION} link",
        FULL_DYNAMIC_PUSH_ACTION,
    ]
    assert sent[0]["group_ids"] == [1002]
    assert sent[1]["group_ids"] == [1001]
    assert sent[2]["group_ids"] == [1001]
    assert "【赛尔号】发布了一条B站动态" in str(sent[1]["message"])
    assert "传送门：" in str(sent[1]["message"])
    assert sent[1]["subscription_key"] == bili_push_subscription_key(1310714247)
    assert "subscription_key" not in sent[2]
    assert "这是忠实摘要。" in str(sent[2]["message"])
    assert "[CQ:image" in str(sent[2]["message"])
    assert "传送门：" not in str(sent[2]["message"])


@pytest.mark.asyncio
async def test_short_full_dynamic_does_not_call_ai(
    tmp_path: Path,
) -> None:
    sent: list[dict[str, Any]] = []

    class RecordingDelivery:
        async def broadcast(
            self,
            message: object,
            **kwargs: object,
        ) -> TargetSendSummary:
            sent.append({"message": message, **kwargs})
            return TargetSendSummary([], [])

    async def unexpected_summary(text: str, *, max_chars: int) -> str:
        del text
        del max_chars
        raise AssertionError

    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", RecordingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        None,
        summarize=unexpected_summary,
        content_max_chars=100,
        summary_max_chars=6,
    )

    await service.send(
        _item(text="这是一条不会触发 AI 的短动态正文。"),
        PUB_TS,
        1310714247,
        BiliPushTargets([1001], [], [], []),
    )

    assert len(sent) == EXPECTED_FULL_PUSH_COUNT
    assert "不会触发 AI 的短动态正文" in str(sent[-1]["message"])


@pytest.mark.asyncio
async def test_800_character_dynamic_sends_the_complete_original_without_ai(
    tmp_path: Path,
) -> None:
    sent: list[dict[str, Any]] = []

    class RecordingDelivery:
        async def broadcast(
            self,
            message: object,
            **kwargs: object,
        ) -> TargetSendSummary:
            sent.append({"message": message, **kwargs})
            return TargetSendSummary([], [])

    async def unexpected_summary(text: str, *, max_chars: int) -> str:
        del text
        del max_chars
        raise AssertionError

    content = "甲" * 800
    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", RecordingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        None,
        summarize=unexpected_summary,
        content_max_chars=800,
        summary_max_chars=500,
    )

    await service.send(
        _item(text=content),
        PUB_TS,
        1310714247,
        BiliPushTargets([1001], [], [], []),
    )

    assert content in str(sent[-1]["message"])


@pytest.mark.asyncio
async def test_801_character_dynamic_uses_a_500_character_ai_summary(
    tmp_path: Path,
) -> None:
    summaries: list[tuple[str, int]] = []

    class RecordingDelivery:
        async def broadcast(
            self,
            _message: object,
            **_kwargs: object,
        ) -> TargetSendSummary:
            return TargetSendSummary([], [])

    async def summarize(text: str, *, max_chars: int) -> str:
        summaries.append((text, max_chars))
        return "摘要。"

    content = "甲" * 801
    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", RecordingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        None,
        summarize=summarize,
        content_max_chars=800,
        summary_max_chars=500,
    )

    await service.send(
        _item(text=content),
        PUB_TS,
        1310714247,
        BiliPushTargets([1001], [], [], []),
    )

    assert summaries == [(content, 500)]


def test_bilibili_fallback_truncation_keeps_a_complete_list_item() -> None:
    text = "一、第一项内容。\n二、第二项内容。\n三、第三项内容。"

    assert truncate_bilibili_text(text, 10) == "一、第一项内容。"


@pytest.mark.asyncio
async def test_delivery_retries_an_oversized_ai_summary_until_it_fits(
    tmp_path: Path,
) -> None:
    summary_limit = 15
    attempts: list[int] = []
    admin_notices: list[str] = []

    async def oversized_summary(text: str, *, max_chars: int) -> str:
        del text
        del max_chars
        attempts.append(1)
        return (
            "一、第一项。二、第二项。三、第三项。" * 20
            if len(attempts) < BILIBILI_SUMMARY_MAX_ATTEMPTS
            else "一、第一项。二、第二项。"
        )

    class RecordingAdminNotices:
        async def send_private_to_superusers(
            self,
            message: str,
            **_kwargs: object,
        ) -> None:
            admin_notices.append(message)

    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", object()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        None,
        summarize=oversized_summary,
        content_max_chars=10,
        summary_max_chars=summary_limit,
        admin_notices=cast("Any", RecordingAdminNotices()),
    )

    summary = await service._content_override(
        _item(text="这是一条需要摘要的长动态正文。"),
        1310714247,
        "这是一条需要摘要的长动态正文。",
    )

    assert summary == "一、第一项。二、第二项。"
    assert len(summary) <= summary_limit
    assert len(attempts) == BILIBILI_SUMMARY_MAX_ATTEMPTS
    assert admin_notices == []


@pytest.mark.asyncio
async def test_full_dynamic_uses_truncated_content_when_summary_fails(
    tmp_path: Path,
) -> None:
    sent: list[dict[str, Any]] = []
    admin_notices: list[dict[str, object]] = []

    class RecordingDelivery:
        async def broadcast(
            self,
            message: object,
            **kwargs: object,
        ) -> TargetSendSummary:
            sent.append({"message": message, **kwargs})
            return TargetSendSummary([], [])

    async def broken_summary(text: str, *, max_chars: int) -> str:
        del text
        del max_chars
        raise TypeError

    class RecordingAdminNotices:
        async def send_private_to_superusers(
            self,
            message: str,
            **kwargs: object,
        ) -> None:
            admin_notices.append({"message": message, **kwargs})

    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", RecordingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        None,
        summarize=broken_summary,
        content_max_chars=10,
        summary_max_chars=50,
        admin_notices=cast("Any", RecordingAdminNotices()),
    )

    await service.send(
        _item(text="这是一条超过十个字符的长动态正文，用于验证摘要失败降级。"),
        PUB_TS,
        1310714247,
        BiliPushTargets([1001], [], [], []),
    )

    assert [entry["action_name"] for entry in sent] == [
        f"{FULL_DYNAMIC_PUSH_ACTION} link",
        FULL_DYNAMIC_PUSH_ACTION,
    ]
    assert "这是一条超过十" in str(sent[-1]["message"])
    assert len(admin_notices) == 1
    assert "B站动态 AI 摘要失败" in str(admin_notices[0]["message"])
    assert "调用异常：TypeError" in str(admin_notices[0]["message"])
    assert admin_notices[0]["action_name"] == BILIBILI_SUMMARY_FAILURE_ACTION
    assert "摘要生成失败，完整内容请见传送门" in str(sent[-1]["message"])


@pytest.mark.asyncio
async def test_full_dynamic_notifies_superusers_when_summary_returns_none(
    tmp_path: Path,
) -> None:
    admin_notices: list[dict[str, object]] = []

    class RecordingDelivery:
        async def broadcast(
            self,
            _message: object,
            **_kwargs: object,
        ) -> TargetSendSummary:
            return TargetSendSummary([], [])

    class RecordingAdminNotices:
        async def send_private_to_superusers(
            self,
            message: str,
            **kwargs: object,
        ) -> None:
            admin_notices.append({"message": message, **kwargs})

    async def empty_summary(text: str, *, max_chars: int) -> None:
        del text
        del max_chars

    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", RecordingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        None,
        summarize=empty_summary,
        content_max_chars=10,
        summary_max_chars=8,
        admin_notices=cast("Any", RecordingAdminNotices()),
    )

    await service.send(
        _item(text="这是一条超过十个字符的长动态正文，用于验证空摘要告警。"),
        PUB_TS,
        1310714247,
        BiliPushTargets([1001], [], [], []),
    )

    assert len(admin_notices) == 1
    assert "AI 未返回有效摘要" in str(admin_notices[0]["message"])


@pytest.mark.asyncio
async def test_full_dynamic_excludes_unsubscribed_targets_from_both_messages(
    tmp_path: Path,
) -> None:
    sent: list[dict[str, Any]] = []

    class RecordingDelivery:
        async def broadcast(
            self,
            message: object,
            **kwargs: object,
        ) -> TargetSendSummary:
            sent.append({"message": message, **kwargs})
            return TargetSendSummary([], [])

    subscriptions = PushUnsubscribeStore(
        tmp_path / "push_unsubscriptions.sqlite"
    )
    subscription_key = bili_push_subscription_key(1310714247)
    subscriptions.unsubscribe_target(
        "group",
        1001,
        subscription_key,
        "bili_push",
    )
    subscriptions.unsubscribe_target(
        "private",
        2001,
        subscription_key,
        "bili_push",
    )
    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", RecordingDelivery()),
        subscriptions,
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
    )

    await service.send(
        _item(),
        PUB_TS,
        1310714247,
        BiliPushTargets(
            full_group_ids=[1001, 1002],
            link_group_ids=[],
            full_user_ids=[2001, 2002],
            link_user_ids=[],
        ),
    )

    assert len(sent) == EXPECTED_FULL_PUSH_COUNT
    assert [entry["group_ids"] for entry in sent] == [[1002], [1002]]
    assert [entry["private_user_ids"] for entry in sent] == [[2002], [2002]]


@pytest.mark.asyncio
async def test_full_dynamic_puts_target_hints_on_link_message_only(
    tmp_path: Path,
) -> None:
    sent: list[object] = []

    class ApplyingDelivery:
        async def broadcast(
            self,
            message: object,
            *,
            group_ids: list[int],
            private_user_ids: list[int],
            **kwargs: object,
        ) -> TargetSendSummary:
            limiter = kwargs.get("message_limiter")
            for group_id in group_ids:
                target = MessageTarget("group", group_id)
                sent.append(
                    limiter(message, target) if callable(limiter) else message
                )
            for user_id in private_user_ids:
                target = MessageTarget("private", user_id)
                sent.append(
                    limiter(message, target) if callable(limiter) else message
                )
            return TargetSendSummary([], [])

    runtime = build_test_runtime(
        feature_config=FeatureConfig(group_policy={"1001": ["fire_manual_ad"]})
    )
    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", ApplyingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        partial(append_fire_manual_ad_for_target, runtime.features),
    )

    await service.send(
        _item(),
        PUB_TS,
        1310714247,
        BiliPushTargets([1001], [], [], []),
    )

    assert len(sent) == EXPECTED_FULL_PUSH_COUNT
    assert "【赛尔号】发布了一条B站动态" in str(sent[0])
    assert "传送门：" in str(sent[0])
    assert FIRE_MANUAL_LINK_MESSAGE in str(sent[0])
    assert BILI_PUSH_ADMIN_HINT in str(sent[0])
    assert "正文内容" in str(sent[1])
    assert "传送门：" not in str(sent[1])
    assert FIRE_MANUAL_LINK_MESSAGE not in str(sent[1])
    assert BILI_PUSH_ADMIN_HINT not in str(sent[1])


@pytest.mark.asyncio
async def test_full_dynamic_retries_only_failed_content_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: list[dict[str, object]] = []

    class PartiallyFailingDelivery:
        async def broadcast(
            self,
            message: object,
            **kwargs: object,
        ) -> TargetSendSummary:
            sent.append({"message": message, **kwargs})
            if kwargs["action_name"] == FULL_DYNAMIC_PUSH_ACTION:
                return TargetSendSummary(
                    [MessageTarget("group", 1001)],
                    [MessageTarget("private", 2001)],
                )
            return TargetSendSummary([], [])

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "ironsbot.services.bilibili.delivery.asyncio.sleep",
        no_sleep,
    )
    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", PartiallyFailingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
    )

    await service.send(
        _item(),
        PUB_TS,
        1310714247,
        BiliPushTargets([1001], [], [2001], []),
    )

    content_attempts = [
        entry
        for entry in sent
        if str(entry["action_name"]) == FULL_DYNAMIC_PUSH_ACTION
        or str(entry["action_name"]).startswith(
            f"{FULL_DYNAMIC_PUSH_ACTION} retry "
        )
    ]
    assert len(content_attempts) == EXPECTED_RETRIED_CONTENT_PUSH_COUNT
    assert content_attempts[1]["group_ids"] == []
    assert content_attempts[1]["private_user_ids"] == [2001]


@pytest.mark.asyncio
async def test_full_dynamic_notifies_superusers_once_after_three_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content_attempts: list[dict[str, object]] = []
    admin_notices: list[dict[str, object]] = []

    class AlwaysFailingDelivery:
        async def broadcast(
            self,
            _message: object,
            **kwargs: object,
        ) -> TargetSendSummary:
            action_name = str(kwargs["action_name"])
            if action_name == FULL_DYNAMIC_PUSH_ACTION or action_name.startswith(
                f"{FULL_DYNAMIC_PUSH_ACTION} retry "
            ):
                content_attempts.append(kwargs)
                return TargetSendSummary(
                    [],
                    [MessageTarget("group", 1001), MessageTarget("private", 2001)],
                )
            return TargetSendSummary([], [])

    class RecordingAdminNotices:
        async def send_private_to_superusers(
            self,
            message: str,
            **kwargs: object,
        ) -> None:
            admin_notices.append({"message": message, **kwargs})

    async def no_sleep(_delay: float) -> None:
        return None

    async def group_name(_bot: object, _group_id: int, **_kwargs: object) -> str:
        return "投递失败群"

    monkeypatch.setattr(
        "ironsbot.services.bilibili.delivery.asyncio.sleep",
        no_sleep,
    )
    monkeypatch.setattr(
        "ironsbot.services.bilibili.delivery.resolve_group_name",
        group_name,
    )
    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", AlwaysFailingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        admin_notices=cast("Any", RecordingAdminNotices()),
    )

    await service.send(
        _item(),
        PUB_TS,
        1310714247,
        BiliPushTargets([1001], [], [2001], []),
    )

    assert len(content_attempts) == FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS
    assert len(admin_notices) == 1
    assert f"已尝试 {FULL_DYNAMIC_CONTENT_MAX_ATTEMPTS} 次" in str(
        admin_notices[0]["message"]
    )
    assert "群：投递失败群（1001）" in str(admin_notices[0]["message"])
    assert "私聊：2001" in str(admin_notices[0]["message"])


def test_content_message_for_image_only_dynamic_omits_synthetic_notice() -> None:
    item = _item(text="")

    rendered = str(build_dynamic_content_message(item))

    assert "发布了一条动态" not in rendered
    assert "回复“动态”查询历史动态" not in rendered
    assert "[CQ:image" in rendered


def test_delivery_service_appends_admin_hint_once_per_day(
    tmp_path: Path,
) -> None:
    store = PushUnsubscribeStore(
        tmp_path / "push_unsubscriptions.sqlite"
    )

    service = _delivery_service(build_test_runtime().features, store)
    first = service._transform_target_message("正文", MessageTarget("group", 1001))
    second = service._transform_target_message("正文2", MessageTarget("group", 1001))
    other_group = service._transform_target_message(
        "正文3",
        MessageTarget("group", 1002),
    )
    private = service._transform_target_message("正文4", MessageTarget("private", 1))

    assert first == f"正文\n\n{BILI_PUSH_ADMIN_HINT}"
    assert second == "正文2"
    assert other_group == f"正文3\n\n{BILI_PUSH_ADMIN_HINT}"
    assert private == "正文4"
