from pathlib import Path

from pytest import MonkeyPatch

from ironsbot.services.bilibili.dynamic_history import (
    BiliDynamicHistoryStore,
    DynamicHistoryRecord,
)
from ironsbot.services.bilibili.menu import (
    build_dynamic_detail_for_selection,
    build_dynamic_menu_text,
    dynamic_record_ids,
    select_cached_dynamic_id,
)


def _record(
    dynamic_id: str,
    *,
    pub_ts: int = 1781004683,
    suppressed: bool = False,
) -> DynamicHistoryRecord:
    return DynamicHistoryRecord(
        dynamic_id=dynamic_id,
        uid=1310714247,
        author_name="赛尔号",
        pub_ts=pub_ts,
        brief="测试动态",
        item={"id_str": dynamic_id},
        pushed=False,
        suppressed=suppressed,
        suppression_reason="命中规则：测试" if suppressed else "",
    )


def _save_record(
    history: BiliDynamicHistoryStore,
    record: DynamicHistoryRecord,
) -> None:
    history.save_item(
        record.item,
        pub_ts=record.pub_ts,
        author_mid=record.uid,
        author_name=record.author_name,
        brief=record.brief,
        pushed=record.pushed,
        suppressed=record.suppressed,
        suppression_reason=record.suppression_reason,
    )


def test_build_dynamic_menu_text_renders_records() -> None:
    text = build_dynamic_menu_text([_record("dynamic-1", suppressed=True)])

    assert "【最新动态列表】" in text
    assert "1. ⏰" in text
    assert "赛尔号（UID：1310714247）" in text
    assert "测试动态" in text
    assert "（未推送）" in text
    assert "两分钟内有效" not in text


def test_dynamic_record_ids_returns_cached_ids() -> None:
    assert dynamic_record_ids([_record("dynamic-1"), _record("dynamic-2")]) == [
        "dynamic-1",
        "dynamic-2",
    ]


def test_select_cached_dynamic_id_handles_statuses() -> None:
    ok = select_cached_dynamic_id(["a", "b"], "2")
    assert ok.is_ok
    assert ok.dynamic_id == "b"
    expected_count = 2
    assert ok.available_count == expected_count

    assert select_cached_dynamic_id([], "1").status == "expired"
    assert select_cached_dynamic_id(["a"], "x").status == "invalid"

    out_of_range = select_cached_dynamic_id(["a"], "2")
    assert out_of_range.status == "out_of_range"
    assert out_of_range.available_count == 1


def test_build_dynamic_detail_for_selection_renders_record(
    tmp_path: Path,
) -> None:
    history = BiliDynamicHistoryStore(tmp_path / "history.sqlite", 10)
    _save_record(history, _record("dynamic-1"))

    result = build_dynamic_detail_for_selection(
        history,
        ["dynamic-1"],
        "1",
    )

    assert result.is_ok
    assert result.message is not None
    assert result.available_count == 1
    assert "传送门: https://t.bilibili.com/dynamic-1" in str(result.message)


def test_build_dynamic_detail_for_selection_handles_missing_record(
    tmp_path: Path,
) -> None:
    history = BiliDynamicHistoryStore(tmp_path / "history.sqlite", 10)
    result = build_dynamic_detail_for_selection(
        history,
        ["dynamic-1"],
        "1",
    )

    assert result.status == "missing"
    assert result.message is None


def test_build_dynamic_detail_for_selection_handles_parse_failure(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    history = BiliDynamicHistoryStore(tmp_path / "history.sqlite", 10)
    _save_record(history, _record("dynamic-1"))
    monkeypatch.setattr(
        "ironsbot.services.bilibili.menu.parse_single_item",
        lambda *_args, **_kwargs: None,
    )

    result = build_dynamic_detail_for_selection(
        history,
        ["dynamic-1"],
        "1",
    )

    assert result.status == "parse_failed"
    assert result.message is None
