from __future__ import annotations

import base64
import io
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from jinja2 import Environment, FileSystemLoader
from PIL import Image, ImageDraw

from ironsbot.integrations.seer_data.new_content_details import NewContentItemDetails
from ironsbot.integrations.seer_data.new_content_renderer import _content_row
from ironsbot.integrations.seer_data.new_content_snapshot import NewContentPreparedItem
from ironsbot.services.seer.new_content import NewContentItem
from ironsbot.services.seer.new_content_diff import present_field_changes
from ironsbot.services.seer.render_paths import (
    NEW_CONTENT_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.new_content import present_new_content_menu

if TYPE_CHECKING:
    from ironsbot.services.seer.rendering.new_content import NewContentMenuItem


def _change(old: object, new: object, field: str = "description") -> dict:
    return {
        "path": ["payload", field],
        "old_exists": True,
        "new_exists": True,
        "old": old,
        "new": new,
    }


def _item(changes: list[dict]) -> NewContentItem:
    return NewContentItem(
        "autocard_chip",
        90001,
        "测试战斗芯片",
        1,
        {"field_changes_version": 1, "field_changes": changes},
        "modified",
    )


def test_chinese_diff_highlights_only_changed_characters() -> None:
    fields, notice = present_field_changes(
        _item([_change("回复20点生命值", "回复30点生命值")])
    )
    assert notice == ""
    line = fields[0].lines[0]
    assert [(part.text, part.changed) for part in line.old] == [
        ("回复", False),
        ("2", True),
        ("0点生命值", False),
    ]
    assert [(part.text, part.changed) for part in line.new] == [
        ("回复", False),
        ("3", True),
        ("0点生命值", False),
    ]


def test_multiline_alignment_keeps_context_and_full_long_text() -> None:
    before = "保持不变\n回复20点\n结束"
    after = "保持不变\n回复30点\n新增效果\n结束"
    fields, _ = present_field_changes(_item([_change(before, after)]))
    lines = fields[0].lines
    assert all(not part.changed for part in (*lines[0].old, *lines[0].new))
    assert "".join(part.text for line in lines for part in line.old) == before.replace(
        "\n", ""
    )
    assert "".join(part.text for line in lines for part in line.new) == after.replace(
        "\n", ""
    )
    long = "相同内容" * 1000
    fields, _ = present_field_changes(_item([_change(long + "旧", long + "新")]))
    assert "".join(fragment.text for fragment in fields[0].lines[0].new) == long + "新"


@pytest.mark.parametrize(
    "old,new", [(None, ""), (0, None), ([], None), (0, "0"), (None, "null")]
)
def test_null_empty_zero_and_scalar_types_remain_distinct(
    old: object, new: object
) -> None:
    fields, _ = present_field_changes(_item([_change(old, new)]))
    assert len(fields) == 1
    line = fields[0].lines[0]
    assert "".join(part.text for part in line.old) != "".join(
        part.text for part in line.new
    )


def test_missing_field_is_not_the_same_as_missing_historical_data() -> None:
    change = {
        "path": ["payload", "info"],
        "old_exists": False,
        "new_exists": True,
        "new": "新增效果",
    }
    fields, notice = present_field_changes(_item([change]))
    assert notice == ""
    assert "字段不存在" in "".join(part.text for part in fields[0].lines[0].old)
    broken = {**change, "old_exists": True}
    fields, notice = present_field_changes(_item([broken]))
    assert not fields and "旧值未提供" in notice
    legacy = replace(_item([]), payload={"change_summary": ["说明已更新"]})
    assert present_field_changes(legacy) == ((), "旧值未提供，无法对比")


def test_new_and_pool_entries_do_not_get_fake_diff_warnings() -> None:
    assert present_field_changes(replace(_item([]), change_kind="added")) == ((), "")
    assert present_field_changes(replace(_item([]), category="peak_pool")) == ((), "")


def test_compared_effect_is_not_repeated_in_the_current_text() -> None:
    row = _content_row(
        "1",
        NewContentPreparedItem(
            _item([_change("回复20点生命值", "回复30点生命值")]),
            NewContentItemDetails(
                metadata="ID：90001",
                description="",
                side_title="芯片效果",
                side_description="回复30点生命值",
            ),
            None,
        ),
    )
    assert row.side_description == row.side_title == ""
    assert row.diff_fields
    assert row.metadata == "ID：90001"


def _sample_row(
    item: NewContentItem, details: NewContentItemDetails
) -> NewContentMenuItem:
    return _content_row("1", NewContentPreparedItem(item, details, None))


def sample_diff_html() -> str:
    """Deterministic fictional visual fixture, also usable for screenshot QA."""
    thumbnail = Image.new("RGB", (82, 110), "#305e76")
    draw = ImageDraw.Draw(thumbnail)
    draw.rectangle((12, 14, 70, 96), fill="#4eaf99", outline="#b7e9dc", width=3)
    draw.text((24, 48), "DEMO", fill="white")
    output = io.BytesIO()
    thumbnail.save(output, format="PNG")
    image = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    card = _sample_row(
        NewContentItem("autocard_card", 90002, "没有简介的测试卡牌", 2, {}),
        NewContentItemDetails(
            metadata="ID：90002｜卡牌",
            description="",
            side_title="技能：风之守护",
            side_description="己方获得护盾。\n升级：护盾持续时间增加1回合。",
        ),
    )
    card = replace(card, image=image, image_layout="portrait")
    chip = _sample_row(
        _item(
            [
                _change(
                    "每回合回复20点生命值\n持续2回合", "每回合回复30点生命值\n持续3回合"
                ),
                _change(1, 2, "rarity"),
            ]
        ),
        NewContentItemDetails(metadata="修改｜ID：90001｜战斗芯片", description=""),
    )
    skill = _sample_row(
        replace(
            _item(
                [
                    _change(100, 120, "power"),
                    _change("使对手攻击降低1级。", "使对手攻击降低2级。", "info"),
                ]
            ),
            category="skill",
            name="测试技能",
        ),
        NewContentItemDetails(
            metadata="修改｜ID：90003",
            description="关联精灵：测试精灵",
            stats=(("威力", "120"), ("PP", "10")),
            stats_layout="skill",
        ),
    )
    missing = _sample_row(
        replace(_item([]), name="缺少旧版本的条目", payload={}),
        NewContentItemDetails(
            metadata="修改｜ID：90004", description="当前效果正常展示，不猜测旧值。"
        ),
    )
    rows = [
        replace(row, code=str(index))
        for index, row in enumerate((card, chip, skill, missing), start=1)
    ]
    document = present_new_content_menu("2026-10-23", rows, {})
    environment = Environment(
        loader=FileSystemLoader([NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH]),
        autoescape=True,
    )
    return environment.get_template("template.html.j2").render(**document.templates)


def test_diff_template_escapes_content_and_uses_equal_width_columns() -> None:
    row = _sample_row(
        _item([_change("<script>alert(1)</script>", "<b>新效果</b>")]),
        NewContentItemDetails(metadata="ID", description=""),
    )
    document = present_new_content_menu("test", [row], {})
    environment = Environment(
        loader=FileSystemLoader([NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH])
    )
    html = environment.get_template("template.html.j2").render(**document.templates)
    assert "<script>" not in html and "<b>新效果</b>" not in html
    assert "&lt;" in html
    assert "diff-fragment old" in html and "diff-fragment new" in html
    assert "修改前" in html and "修改后" in html
    assert "width: 50%" in html
    assert "flex: 0 0 330px" not in html
    assert "min-height: 100px" not in html
