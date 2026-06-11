from typing import Any

from pytest import MonkeyPatch

from ironsbot.services.bilibili import cache
from ironsbot.services.bilibili.push import DynamicHistorySnapshot

AUTHOR_UID = 1310714247
PUB_TS = 1781004683


def test_save_dynamic_history_snapshot_forwards_snapshot_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def fake_save_dynamic_history_item(
        item: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        calls.append((item, kwargs))

    monkeypatch.setattr(
        cache,
        "save_dynamic_history_item",
        fake_save_dynamic_history_item,
    )
    item = {"id_str": "dynamic-1"}
    snapshot = DynamicHistorySnapshot(
        item=item,
        pub_ts=PUB_TS,
        author_mid=AUTHOR_UID,
        author_name="赛尔号",
        brief="测试动态",
        pushed=True,
        suppressed=True,
        suppression_reason="命中规则：测试",
    )

    cache.save_dynamic_history_snapshot(snapshot)

    assert calls == [
        (
            item,
            {
                "pub_ts": PUB_TS,
                "author_mid": AUTHOR_UID,
                "author_name": "赛尔号",
                "brief": "测试动态",
                "pushed": True,
                "suppressed": True,
                "suppression_reason": "命中规则：测试",
            },
        )
    ]
