from ironsbot.plugins.operations.db_sync import MANUAL_SYNC_COMMANDS
from ironsbot.services.seer.data_query_commands import (
    NEW_ACHIEVEMENTS_COMMANDS,
    NEW_AUTOCARD_CARDS_COMMANDS,
    NEW_AUTOCARD_ROLES_COMMANDS,
    NEW_AUTOCARD_SANCTUARIES_COMMANDS,
    NEW_CONTENT_COMMANDS,
    NEW_EQUIPS_COMMANDS,
    NEW_MINTMARKS_COMMANDS,
    NEW_MOUNTS_COMMANDS,
    NEW_PETS_COMMANDS,
    NEW_SKILLS_COMMANDS,
    NEW_SKINS_COMMANDS,
    NEW_SUITS_COMMANDS,
)


def test_new_content_root_commands_cover_natural_language_aliases() -> None:
    assert NEW_CONTENT_COMMANDS == (
        "新增内容",
        "新增",
        "每周",
        "内容",
        "本周更新",
        "每周更新",
        "更新内容",
        "内容更新",
    )
    assert "更新" not in NEW_CONTENT_COMMANDS
    assert not set(NEW_CONTENT_COMMANDS) & set(MANUAL_SYNC_COMMANDS)


def test_new_content_categories_use_prefix_aliases_only() -> None:
    categories = {
        "精灵": NEW_PETS_COMMANDS,
        "皮肤": NEW_SKINS_COMMANDS,
        "技能": NEW_SKILLS_COMMANDS,
        "刻印": NEW_MINTMARKS_COMMANDS,
        "套装": NEW_SUITS_COMMANDS,
        "部件": NEW_EQUIPS_COMMANDS,
        "座驾": NEW_MOUNTS_COMMANDS,
        "成就": NEW_ACHIEVEMENTS_COMMANDS,
        "群星牌": NEW_AUTOCARD_CARDS_COMMANDS,
        "群星牌角色": NEW_AUTOCARD_ROLES_COMMANDS,
        "群星牌圣域": NEW_AUTOCARD_SANCTUARIES_COMMANDS,
    }

    for category, commands in categories.items():
        assert any(command == f"每周{category}" for command in commands)
        assert any(command == f"本周{category}" for command in commands)
        assert any(command == f"更新{category}" for command in commands)

    assert {"新增群星牌卡牌", "新增卡牌"}.issubset(NEW_AUTOCARD_CARDS_COMMANDS)
    assert "新成就" not in NEW_ACHIEVEMENTS_COMMANDS
    assert "皮肤更新" not in NEW_SKINS_COMMANDS
