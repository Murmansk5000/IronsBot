from dataclasses import dataclass
from typing import Any

from pytest import MonkeyPatch

from ironsbot.services.bilibili import delivery as delivery_service
from ironsbot.services.bilibili.delivery import (
    FULL_DYNAMIC_PUSH_ACTION,
    LINK_DYNAMIC_PUSH_ACTION,
    build_dynamic_push_deliveries,
)
from ironsbot.shared.promotions import FIRE_MANUAL_LINK_MESSAGE

PUB_TS = 1781004683
SPLIT_DELIVERY_COUNT = 2


@dataclass(frozen=True, slots=True)
class FakePushTargets:
    full_group_ids: list[int]
    link_group_ids: list[int]
    full_user_ids: list[int]
    link_user_ids: list[int]


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


def test_build_dynamic_push_deliveries_renders_full_and_link_targets(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        delivery_service,
        "split_fire_manual_ad_group_ids",
        lambda group_ids: (group_ids, []),
    )

    deliveries = build_dynamic_push_deliveries(
        _item(),
        PUB_TS,
        FakePushTargets(
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
    assert FIRE_MANUAL_LINK_MESSAGE in full_rendered
    assert "正文内容" not in link_rendered
    assert "[CQ:image" not in link_rendered
    assert FIRE_MANUAL_LINK_MESSAGE in link_rendered


def test_build_dynamic_push_deliveries_splits_groups_without_fire_manual_ad(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        delivery_service,
        "split_fire_manual_ad_group_ids",
        lambda group_ids: ([group_ids[0]], group_ids[1:]),
    )

    deliveries = build_dynamic_push_deliveries(
        _item(),
        PUB_TS,
        FakePushTargets(
            full_group_ids=[1001, 1002],
            link_group_ids=[],
            full_user_ids=[],
            link_user_ids=[],
        ),
    )

    assert len(deliveries) == SPLIT_DELIVERY_COUNT
    assert deliveries[0].group_ids == [1001]
    assert FIRE_MANUAL_LINK_MESSAGE in str(deliveries[0].message)
    assert deliveries[1].group_ids == [1002]
    assert FIRE_MANUAL_LINK_MESSAGE not in str(deliveries[1].message)


def test_build_dynamic_push_deliveries_skips_empty_targets() -> None:
    deliveries = build_dynamic_push_deliveries(
        _item(),
        PUB_TS,
        FakePushTargets(
            full_group_ids=[],
            link_group_ids=[],
            full_user_ids=[],
            link_user_ids=[],
        ),
    )

    assert deliveries == []
