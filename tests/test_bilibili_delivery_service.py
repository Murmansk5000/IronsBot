from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core.features import FeatureConfig
from ironsbot.core.messaging import FIRE_MANUAL_LINK_MESSAGE, MessageTarget
from ironsbot.integrations.onebot.promotions import append_fire_manual_ad_for_target
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.plugins.bilibili.delivery import build_dynamic_message
from ironsbot.runtime.replies import append_text_hint
from ironsbot.services.bilibili.delivery import (
    BILI_PUSH_ADMIN_HINT,
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
        build_dynamic_message,
        append_text_hint,
        partial(append_fire_manual_ad_for_target, features),
    )


def test_delivery_service_plans_full_and_link_targets(
) -> None:
    features = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={
                "1001": ["fire_manual_ad"],
                "1002": ["fire_manual_ad"],
            }
        )
    ).features

    deliveries = _delivery_service(features).build_deliveries(
        _item(),
        PUB_TS,
        BiliPushTargets(
            full_group_ids=[1001],
            link_group_ids=[1002],
            full_user_ids=[2001],
            link_user_ids=[2002],
        ),
    )

    assert [delivery.action_name for delivery in deliveries] == [
        FULL_DYNAMIC_PUSH_ACTION,
        LINK_DYNAMIC_PUSH_ACTION,
    ]
    assert deliveries[0].group_ids == [1001]
    assert deliveries[0].private_user_ids == [2001]
    assert deliveries[1].group_ids == [1002]
    assert deliveries[1].private_user_ids == [2002]

    full_rendered = str(deliveries[0].message)
    link_rendered = str(deliveries[1].message)
    assert "正文内容" in full_rendered
    assert "[CQ:image" in full_rendered
    assert FIRE_MANUAL_LINK_MESSAGE not in full_rendered
    assert BILI_PUSH_ADMIN_HINT not in full_rendered
    assert "正文内容" not in link_rendered
    assert "[CQ:image" not in link_rendered
    assert FIRE_MANUAL_LINK_MESSAGE not in link_rendered
    assert BILI_PUSH_ADMIN_HINT not in link_rendered


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


def test_delivery_service_skips_empty_targets() -> None:
    deliveries = _delivery_service(
        build_test_runtime().features
    ).build_deliveries(
        _item(),
        PUB_TS,
        BiliPushTargets(
            full_group_ids=[],
            link_group_ids=[],
            full_user_ids=[],
            link_user_ids=[],
        ),
    )

    assert deliveries == []


@pytest.mark.asyncio
async def test_long_dynamic_sends_link_then_one_shared_summary(
    tmp_path: Path,
) -> None:
    sent: list[dict[str, Any]] = []
    summaries: list[tuple[str, int]] = []

    class RecordingDelivery:
        async def broadcast(self, message: object, **kwargs: object) -> None:
            sent.append({"message": message, **kwargs})

    async def summarize(content: str, max_chars: int) -> str:
        summaries.append((content, max_chars))
        return "这是忠实摘要。"

    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", RecordingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_message,
        append_text_hint,
        summary_renderer=lambda _item, _pub_ts, text: f"摘要：{text}",
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
        f"{FULL_DYNAMIC_PUSH_ACTION} notice",
        f"{FULL_DYNAMIC_PUSH_ACTION} summary",
    ]
    assert sent[0]["group_ids"] == [1002]
    assert sent[1]["group_ids"] == [1001]
    assert sent[2]["group_ids"] == [1001]
    assert "原文超过 10 字，下一条发送摘要。" in str(sent[1]["message"])
    assert sent[1].get("subscription_key") is None
    assert sent[2]["subscription_key"] == bili_push_subscription_key(1310714247)
    assert sent[2]["message"] == "摘要：这是忠实摘要。"


@pytest.mark.asyncio
async def test_long_dynamic_uses_original_excerpt_when_summary_unavailable(
    tmp_path: Path,
) -> None:
    sent: list[dict[str, Any]] = []

    class RecordingDelivery:
        async def broadcast(self, message: object, **kwargs: object) -> None:
            sent.append({"message": message, **kwargs})

    async def unavailable_summary(_content: str, _max_chars: int) -> None:
        return None

    service = BilibiliPushDeliveryService(
        cast("MessageDelivery", RecordingDelivery()),
        PushUnsubscribeStore(tmp_path / "push_unsubscriptions.sqlite"),
        build_dynamic_message,
        append_text_hint,
        summary_renderer=lambda _item, _pub_ts, text: text,
        summarize=unavailable_summary,
        content_max_chars=10,
        summary_max_chars=6,
    )

    await service.send(
        _item(text="第一段内容用于验证摘要失败时发送原文节选。"),
        PUB_TS,
        1310714247,
        BiliPushTargets([1001], [], [], []),
    )

    assert sent[-1]["message"] == "第一段内容用"


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
