from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.message import PushUnsubscribeConfig
from ironsbot.core.messaging import FIRE_MANUAL_LINK_MESSAGE
from ironsbot.services.bilibili import delivery as delivery_service
from ironsbot.services.bilibili.delivery import (
    BILI_PUSH_ADMIN_HINT,
    FULL_DYNAMIC_PUSH_ACTION,
    LINK_DYNAMIC_PUSH_ACTION,
    append_bili_admin_hint_for_group,
    build_dynamic_push_deliveries,
)
from tests.helpers.config import stub_app_config
from tests.helpers.runtime import build_test_runtime

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
) -> None:
    features = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={
                "1001": ["fire_manual_ad"],
                "1002": ["fire_manual_ad"],
            }
        )
    ).features

    deliveries = build_dynamic_push_deliveries(
        features,
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
        FULL_DYNAMIC_PUSH_ACTION,
        LINK_DYNAMIC_PUSH_ACTION,
        LINK_DYNAMIC_PUSH_ACTION,
    ]
    assert deliveries[0].group_ids == [1001]
    assert deliveries[0].private_user_ids == []
    assert deliveries[1].group_ids == []
    assert deliveries[1].private_user_ids == [2001]
    assert deliveries[2].group_ids == [1002]
    assert deliveries[2].private_user_ids == []
    assert deliveries[3].group_ids == []
    assert deliveries[3].private_user_ids == [2002]

    full_rendered = str(deliveries[0].message)
    full_private_rendered = str(deliveries[1].message)
    link_rendered = str(deliveries[2].message)
    link_private_rendered = str(deliveries[3].message)
    assert "正文内容" in full_rendered
    assert "[CQ:image" in full_rendered
    assert FIRE_MANUAL_LINK_MESSAGE in full_rendered
    assert BILI_PUSH_ADMIN_HINT not in full_rendered
    assert BILI_PUSH_ADMIN_HINT not in full_private_rendered
    assert "正文内容" not in link_rendered
    assert "[CQ:image" not in link_rendered
    assert FIRE_MANUAL_LINK_MESSAGE in link_rendered
    assert BILI_PUSH_ADMIN_HINT not in link_rendered
    assert BILI_PUSH_ADMIN_HINT not in link_private_rendered


def test_build_dynamic_push_deliveries_splits_groups_without_fire_manual_ad(
) -> None:
    deliveries = build_dynamic_push_deliveries(
        build_test_runtime(
            feature_config=FeatureConfig(
                group_policy={"1001": ["fire_manual_ad"]},
            )
        ).features,
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
    assert BILI_PUSH_ADMIN_HINT not in str(deliveries[0].message)
    assert deliveries[1].group_ids == [1002]
    assert FIRE_MANUAL_LINK_MESSAGE not in str(deliveries[1].message)
    assert BILI_PUSH_ADMIN_HINT not in str(deliveries[1].message)


def test_build_dynamic_push_deliveries_skips_empty_targets() -> None:
    deliveries = build_dynamic_push_deliveries(
        build_test_runtime().features,
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


def test_append_bili_admin_hint_for_group_once_per_day(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = PushUnsubscribeConfig(
        data_path=str(tmp_path / "push_unsubscriptions.sqlite")
    )
    monkeypatch.setattr(
        delivery_service,
        "get_app_config",
        lambda: stub_app_config(push_unsubscribe_config=config),
    )

    first = append_bili_admin_hint_for_group("正文", 1001)
    second = append_bili_admin_hint_for_group("正文2", 1001)
    other_group = append_bili_admin_hint_for_group("正文3", 1002)
    private = append_bili_admin_hint_for_group("正文4", None)

    assert first == f"正文\n\n{BILI_PUSH_ADMIN_HINT}"
    assert second == "正文2"
    assert other_group == f"正文3\n\n{BILI_PUSH_ADMIN_HINT}"
    assert private == "正文4"
