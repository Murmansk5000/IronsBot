from typing import Any

from pytest import MonkeyPatch

from ironsbot.services.bilibili import cache
from ironsbot.services.bilibili.push import DynamicHistorySnapshot

AUTHOR_UID = 1310714247
PUB_TS = 1781004683


def _dynamic_item(*, text: str = "恭喜测试用户获得赛尔号奖励内容") -> dict[str, Any]:
    return {
        "id_str": "dynamic-1",
        "modules": {
            "module_author": {
                "mid": AUTHOR_UID,
                "name": "赛尔号",
                "pub_ts": PUB_TS,
            },
            "module_dynamic": {
                "major": {
                    "opus": {
                        "summary": {"text": text},
                    }
                }
            },
        },
    }


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


def test_save_target_dynamic_history_builds_and_saves_snapshots(
    monkeypatch: MonkeyPatch,
) -> None:
    saved_snapshots: list[DynamicHistorySnapshot] = []

    def fake_save_dynamic_history_snapshot(
        snapshot: DynamicHistorySnapshot,
    ) -> None:
        saved_snapshots.append(snapshot)

    monkeypatch.setattr(
        cache,
        "save_dynamic_history_snapshot",
        fake_save_dynamic_history_snapshot,
    )

    saved_count = cache.save_target_dynamic_history(
        [
            (PUB_TS, _dynamic_item()),
            (PUB_TS, {"id_str": "missing-author"}),
        ],
        suppress_patterns=["恭喜.*获得"],
    )

    assert saved_count == 1
    assert len(saved_snapshots) == 1
    snapshot = saved_snapshots[0]
    assert snapshot.author_mid == AUTHOR_UID
    assert snapshot.suppressed
    assert snapshot.suppression_reason == "命中规则：恭喜.*获得"
