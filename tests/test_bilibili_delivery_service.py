from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core.features import FeatureConfig
from ironsbot.core.messaging import FIRE_MANUAL_LINK_MESSAGE, MessageTarget
from ironsbot.integrations.onebot.promotions import append_fire_manual_ad_for_target
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.plugins.bilibili.delivery import (
    build_dynamic_content_message,
    build_dynamic_link_message,
)
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
EXPECTED_FULL_PUSH_COUNT = 2


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
    assert "账号：赛尔号" in link_rendered
    assert "B站动态更新" in link_rendered
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


@pytest.mark.asyncio
async def test_full_dynamic_always_sends_link_then_compact_content(
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
    assert "B站动态更新" in str(sent[1]["message"])
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
        async def broadcast(self, message: object, **kwargs: object) -> None:
            sent.append({"message": message, **kwargs})

    async def unexpected_summary(_content: str, _max_chars: int) -> str:
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
        ) -> None:
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
    assert "B站动态更新" in str(sent[0])
    assert "传送门：" in str(sent[0])
    assert FIRE_MANUAL_LINK_MESSAGE in str(sent[0])
    assert BILI_PUSH_ADMIN_HINT in str(sent[0])
    assert "正文内容" in str(sent[1])
    assert "传送门：" not in str(sent[1])
    assert FIRE_MANUAL_LINK_MESSAGE not in str(sent[1])
    assert BILI_PUSH_ADMIN_HINT not in str(sent[1])


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
