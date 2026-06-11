from dataclasses import dataclass
from typing import Any

from ironsbot.services.bilibili.push import (
    build_dynamic_history_snapshot,
    build_dynamic_history_snapshot_for_item,
    decide_dynamic_push_after_targets,
    decide_dynamic_push_before_targets,
    mark_history_snapshot_pushed,
)

AUTHOR_UID = 1310714247
OLD_TS = 100
NEW_TS = 150


@dataclass(frozen=True, slots=True)
class FakeTargets:
    has_targets: bool


def _item(*, text: str = "这是一条测试动态") -> dict[str, Any]:
    return {
        "id_str": "dynamic-1",
        "modules": {
            "module_author": {
                "mid": AUTHOR_UID,
                "name": "赛尔号",
                "pub_ts": NEW_TS,
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


def test_build_dynamic_history_snapshot_collects_display_fields() -> None:
    snapshot = build_dynamic_history_snapshot(
        _item(),
        pub_ts=NEW_TS,
        author_mid=AUTHOR_UID,
        suppression_reason="命中规则：测试",
    )

    assert snapshot.author_name == "赛尔号"
    assert "赛尔号" in snapshot.brief
    assert snapshot.suppressed
    assert snapshot.suppression_reason == "命中规则：测试"
    assert not snapshot.pushed


def test_build_dynamic_history_snapshot_for_item_applies_suppression() -> None:
    snapshot = build_dynamic_history_snapshot_for_item(
        _item(text="恭喜测试用户获得赛尔号超长测试奖励内容"),
        pub_ts=NEW_TS,
        suppress_patterns=["恭喜.*获得"],
    )

    assert snapshot is not None
    assert snapshot.author_mid == AUTHOR_UID
    assert snapshot.suppressed
    assert snapshot.suppression_reason == "命中规则：恭喜.*获得"


def test_build_dynamic_history_snapshot_for_item_skips_missing_author() -> None:
    assert (
        build_dynamic_history_snapshot_for_item(
            {"id_str": "dynamic-without-author"},
            pub_ts=NEW_TS,
            suppress_patterns=[],
        )
        is None
    )


def test_mark_history_snapshot_pushed_preserves_existing_fields() -> None:
    snapshot = build_dynamic_history_snapshot(
        _item(),
        pub_ts=NEW_TS,
        author_mid=AUTHOR_UID,
    )

    pushed = mark_history_snapshot_pushed(snapshot)

    assert pushed.pushed
    assert pushed.item == snapshot.item
    assert pushed.author_mid == snapshot.author_mid
    assert pushed.brief == snapshot.brief


def test_decide_dynamic_push_before_targets_handles_skip_and_suppression() -> None:
    assert (
        decide_dynamic_push_before_targets(
            pub_ts=OLD_TS,
            last_saved_time=NEW_TS,
            suppression_reason="",
        ).status
        == "skip_existing"
    )
    assert (
        decide_dynamic_push_before_targets(
            pub_ts=NEW_TS,
            last_saved_time=OLD_TS,
            suppression_reason="命中规则：测试",
        ).status
        == "suppressed"
    )

    assert (
        decide_dynamic_push_before_targets(
            pub_ts=NEW_TS,
            last_saved_time=OLD_TS,
            suppression_reason="",
        )
        is None
    )


def test_decide_dynamic_push_after_targets_handles_target_statuses() -> None:
    assert (
        decide_dynamic_push_after_targets(FakeTargets(has_targets=False)).status
        == "no_targets"
    )

    decision = decide_dynamic_push_after_targets(FakeTargets(has_targets=True))
    assert decision.should_push
    assert decision.status == "push"
