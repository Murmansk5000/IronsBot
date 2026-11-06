from __future__ import annotations

from dataclasses import replace

from jinja2 import Environment, FileSystemLoader

from ironsbot.integrations.seer_data.new_content_details import NewContentItemDetails
from ironsbot.integrations.seer_data.new_content_renderer import _content_row
from ironsbot.integrations.seer_data.new_content_snapshot import NewContentPreparedItem
from ironsbot.services.seer.new_content import NewContentItem
from ironsbot.services.seer.new_content_diff import present_field_changes
from ironsbot.services.seer.new_content_text import (
    plain_weekly_skill,
    plain_weekly_text,
)
from ironsbot.services.seer.render_paths import (
    NEW_CONTENT_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.analyze_description import (
    format_analyze_description,
)
from ironsbot.services.seer.rendering.custom_pet_models import SkillDict
from ironsbot.services.seer.rendering.new_content import present_new_content_menu


def _item(old: str, new: str, path: list[str]) -> NewContentItem:
    return NewContentItem(
        "pet",
        90001,
        "测试精灵",
        1,
        {
            "field_changes_version": 1,
            "field_changes": [
                {
                    "path": path,
                    "old_exists": True,
                    "new_exists": True,
                    "old": old,
                    "new": new,
                }
            ],
        },
        "modified",
    )


def _skill() -> SkillDict:
    return SkillDict(
        id=90002,
        name="测试技能",
        type_id=1,
        type_name="普通",
        category_id=1,
        category_name="物理攻击",
        power=120,
        max_pp=10,
        accuracy=100,
        crit_rate=None,
        priority=0,
        must_hit=False,
        learning_level=None,
        is_special=False,
        is_advanced=False,
        is_fifth=False,
        activation_item=None,
        friend_bonus=False,
        info=format_analyze_description("[color=#57c975]攻击结束时[/color]"),
        hide_effect_desc=format_analyze_description("[color=#52a5f2]固定伤害[/color]"),
        effects=[
            {
                "id": 1,
                "info": format_analyze_description(
                    "[color=#52a5f2]恢复30点[/color]|数值(007) <安全>"
                ),
            }
        ],
    )


def _html(item: NewContentItem, details: NewContentItemDetails) -> str:
    row = _content_row("1", NewContentPreparedItem(item, details, None))
    doc = present_new_content_menu("test", [row], {1: "data:image/png;base64,"})
    env = Environment(
        loader=FileSystemLoader([NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH]),
        autoescape=True,
    )
    return env.get_template("template.html.j2").render(**doc.templates)


def test_plain_text_keeps_numbers_paragraphs_and_boss_semantics() -> None:
    raw = (
        "[sprite name=dot4]自身[color=#57c975]攻击结束时[/color]造成20点伤害(007)"
        "[spritename=dot1]首次死亡时复活|[sprite name=dot1]复活后威力翻倍"
    )
    assert plain_weekly_text(raw, soulmark=True) == (
        "自身攻击结束时造成20点伤害(007)（BOSS无效）\n"
        "首次死亡时复活（BOSS有效）\n复活后威力翻倍（BOSS有效）"
    )
    assert plain_weekly_text("[sprite name=dot99]未知含义", soulmark=True) == "未知含义"
    assert plain_weekly_text("[sprite name=dot1]效果（BOSS有效）", soulmark=True) == (
        "效果（BOSS有效）"
    )


def test_soulmark_diff_compares_visible_effect_and_boss_status_not_tags() -> None:
    item = _item(
        "[sprite name=dot1]造成[color=#52a5f2]20[/color]点固定伤害",
        "[sprite name=dot4]造成[color=#57c975]30[/color]点固定伤害",
        ["soulmarks", "id=638", "analyze_desc"],
    )
    fields, notice = present_field_changes(item)
    assert not notice
    assert fields[0].label == "魂印 / ID 638 / 效果说明"
    before = "".join(p.text for p in fields[0].fragments if p.kind != "insert")
    after = "".join(p.text for p in fields[0].fragments if p.kind != "delete")
    assert before == "造成20点固定伤害（BOSS有效）"
    assert after == "造成30点固定伤害（BOSS无效）"
    assert any(p.text == "20" and p.kind == "delete" for p in fields[0].fragments)
    assert any(p.text == "30" and p.kind == "insert" for p in fields[0].fragments)
    assert "[" not in before + after


def test_color_only_change_keeps_current_text_without_fake_revisions() -> None:
    old = "[color=#52a5f2]固定伤害[/color]"
    new = "[color=#57c975]固定伤害[/color]"
    item = _item(old, new, ["payload", "description"])
    fields, notice = present_field_changes(item)
    assert not fields and notice == "文本样式调整"
    row = _content_row(
        "1",
        NewContentPreparedItem(
            item, NewContentItemDetails(metadata="ID", description=new), None
        ),
    )
    assert row.description == "固定伤害"
    assert item.payload["field_changes"][0]["new"] == new


def test_weekly_skill_unwraps_safe_html_without_mutating_ordinary_card() -> None:
    skill = _skill()
    plain = plain_weekly_skill(skill)
    assert plain is not None
    assert plain["info"] == "攻击结束时"
    assert plain["hide_effect_desc"] == "固定伤害"
    assert plain["effects"][0]["info"] == "恢复30点\n数值(007) <安全>"
    assert "#57c975" in (skill["info"] or "")
    assert "<b" in str(skill["effects"][0]["info"])


def test_nested_colors_and_unknown_color_controls_do_not_leak() -> None:
    assert (
        plain_weekly_text(
            "[color=#52a5f2][color=#57c975]攻击[/color]增加30点[/color]|下一段"
        )
        == "攻击增加30点\n下一段"
    )
    assert plain_weekly_text("[color=invalid]内容[/color]") == "内容"


def test_weekly_skill_and_revisions_are_plain_safe_and_not_repeated() -> None:
    old = "[color=#52a5f2]恢复20点[/color]"
    new = "[color=#57c975]恢复30点[/color]|数值(007) <安全>"
    skill = _skill()
    item = _item(old, new, ["effects", "id=1", "info"])
    details = NewContentItemDetails(metadata="ID", description="", skill=skill)
    row = _content_row("1", NewContentPreparedItem(item, details, None))
    assert row.skill is not None and not row.skill["effects"]
    html = _html(item, details)
    assert "#52a5f2" not in html and "#57c975" not in html
    assert "[color" not in html and "[sprite" not in html
    assert "&lt;b" not in html
    assert "攻击结束时" in html and "固定伤害" in html
    assert "<del>" in html and "<ins>" in html and "&lt;安全&gt;" in html


def test_html_in_source_is_escaped_after_plain_text_comparison() -> None:
    item = _item(
        "[color=#52a5f2]<script>old</script>[/color]",
        "[color=#57c975]<script>new</script>[/color]",
        ["payload", "description"],
    )
    html = _html(item, NewContentItemDetails(metadata="ID", description=""))
    assert "<script>" not in html and "&lt;" in html
    assert "[color" not in html and "<del>" in html and "<ins>" in html


def test_parameter_strings_do_not_use_paragraph_cleanup() -> None:
    item = _item("1_2|3_4", "1_5|6_7", ["payload", "BuffParam"])
    fields, _ = present_field_changes(item)
    assert [(p.text, p.kind) for p in fields[0].fragments] == [
        ("1_2|3_4", "delete"),
        ("1_5|6_7", "insert"),
    ]


def test_nested_list_description_is_cleaned_without_rewriting_parameters() -> None:
    old = [{"id": 1, "info": "[color=#52a5f2]恢复20点[/color]", "BuffParam": "1|2"}]
    new = [{"id": 1, "info": "[color=#57c975]恢复30点[/color]", "BuffParam": "1|3"}]
    item = replace(
        _item("", "", ["payload", "skills"]),
        payload={
            "field_changes_version": 1,
            "field_changes": [
                {
                    "path": ["payload", "skills"],
                    "old_exists": True,
                    "new_exists": True,
                    "old": old,
                    "new": new,
                }
            ],
        },
    )
    fields, notice = present_field_changes(item)
    assert not notice
    before = "".join(p.text for p in fields[0].fragments if p.kind != "insert")
    after = "".join(p.text for p in fields[0].fragments if p.kind != "delete")
    assert "[color" not in before + after
    assert "恢复20点" in before and "恢复30点" in after
    assert '"1|2"' in before and '"1|3"' in after
    assert new[0]["info"] == "[color=#57c975]恢复30点[/color]"
