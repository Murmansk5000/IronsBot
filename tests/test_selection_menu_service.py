from ironsbot.core.selection import (
    SelectionMenuItem,
    SelectionMenuSection,
    format_selection_menu,
)


def test_format_selection_menu_numbers_items() -> None:
    text = format_selection_menu(
        title="请选择：",
        items=("苹果", "香蕉"),
    )

    assert "请选择：" in text
    assert "1. 苹果" in text
    assert "2. 香蕉" in text
    assert "0.【退出】" in text
    assert "💬 输入序号选择" in text


def test_format_selection_menu_numbers_across_sections() -> None:
    text = format_selection_menu(
        title="📖 可用功能：",
        items=(
            SelectionMenuSection(title="基础", items=("帮助",)),
            SelectionMenuSection(title="赛尔查询", items=("群星牌", "榜单")),
        ),
    )

    assert "【基础】" in text
    assert "1. 帮助" in text
    assert "【赛尔查询】" in text
    assert "2. 群星牌" in text
    assert "3. 榜单" in text


def test_format_selection_menu_supports_prefix_and_detail_lines() -> None:
    text = format_selection_menu(
        title="请选择要切换的推送订阅：",
        items=(
            SelectionMenuItem(label="活动结束提醒", prefix="✅"),
            SelectionMenuItem(
                label="⏰ 2026-07-06 12:00:00",
                detail_lines=("👤 赛尔号（UID：1310714247）", "📝 测试动态"),
            ),
            SelectionMenuItem(label="子项", is_sub_item=True),
        ),
        footer="✅ 已订阅 · ❌ 已退订，输入序号切换",
    )

    assert "1. ✅ 活动结束提醒" in text
    assert "2. ⏰ 2026-07-06 12:00:00" in text
    assert "   👤 赛尔号（UID：1310714247）" in text
    assert "   📝 测试动态" in text
    assert " ↳ 3. 子项" in text
    assert "0.【退出】" in text
    assert "✅ 已订阅 · ❌ 已退订，输入序号切换" in text
