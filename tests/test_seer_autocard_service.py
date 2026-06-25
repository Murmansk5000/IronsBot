from ironsbot.services.seer.autocard import (
    AutocardDataset,
    AutocardPromptValue,
    autocard_image_url,
    build_autocard_prompt_text,
    build_autocard_prompt_values,
    extract_autocard_query_arg,
    format_autocard_entry,
    format_autocard_public_info,
    is_autocard_help_query,
    search_autocard_items,
)

CARD_ID = 101
ROLE_ID = 201


def _dataset() -> AutocardDataset:
    return AutocardDataset(
        cards=(
            {
                "id": CARD_ID,
                "name": "布布种子",
                "type": 1,
                "nature": 1,
                "level": 2,
                "cost": 3,
                "attack": 3,
                "health": 5,
                "compose": 0,
                "picID": 1,
                "cardTxt": "回合开始时回复1点生命",
                "des": "经典草系精灵牌",
            },
        ),
        roles=(
            {
                "id": ROLE_ID,
                "name": "破界者",
                "nature": 2,
                "health": 20,
                "picID": 7,
                "skillName": "破界",
                "skillTxt": "造成2点伤害",
                "skillUpgrade": "伤害+1",
                "desc": "赛尔角色",
            },
        ),
        natures={
            1: "草",
            2: "火",
        },
    )


def test_extract_autocard_query_arg_strips_known_prefixes_and_suffixes() -> None:
    assert extract_autocard_query_arg("群星牌布布种子") == "布布种子"
    assert extract_autocard_query_arg("布布种子群星牌") == "布布种子"
    assert extract_autocard_query_arg("卡牌 破界者") == "破界者"


def test_help_query_recognizes_empty_and_help_terms() -> None:
    assert is_autocard_help_query("")
    assert is_autocard_help_query("帮助")
    assert not is_autocard_help_query("布布种子")


def test_search_autocard_items_supports_exact_partial_and_id_queries() -> None:
    dataset = _dataset()

    assert search_autocard_items(dataset, "布布种子") == [
        ("card", dataset.cards[0]),
    ]
    assert search_autocard_items(dataset, "破界") == [
        ("role", dataset.roles[0]),
    ]
    assert search_autocard_items(dataset, str(CARD_ID)) == [
        ("card", dataset.cards[0]),
    ]


def test_format_autocard_entry_renders_card_public_fields() -> None:
    message = format_autocard_entry(_dataset(), "card", _dataset().cards[0])

    assert "🃏【群星牌】" in message
    assert "布布种子（ID：101，普通）" in message
    assert "类型：精灵牌 | 属性：草 | 等级：2 | 费用：3" in message
    assert "身材：3/5" in message
    assert "效果：回合开始时回复1点生命" in message


def test_format_autocard_entry_renders_role_public_fields() -> None:
    message = format_autocard_entry(_dataset(), "role", _dataset().roles[0])

    assert "🧑‍🚀【群星牌角色】" in message
    assert "破界者（ID：201）" in message
    assert "属性：火 | 生命：20" in message
    assert "技能：破界" in message
    assert "升级：伤害+1" in message


def test_autocard_image_url_resolves_card_asset_paths() -> None:
    dataset = _dataset()

    assert autocard_image_url("card", dataset.cards[0]).endswith(
        "/newseer/assets/art/autocard/texture/cards/card_1.png"
    )
    assert autocard_image_url(
        "card",
        {"id": 10001, "picID": 1, "compose": 1},
    ).endswith("/newseer/assets/art/autocard/texture/cards/card_1.png")
    assert autocard_image_url(
        "card",
        {"id": 20001, "picID": 20001, "compose": 0},
    ).endswith("/newseer/assets/art/autocard/texture/cards/card_20001.png")


def test_autocard_image_url_resolves_role_asset_path() -> None:
    assert autocard_image_url("role", _dataset().roles[0]).endswith(
        "/newseer/assets/art/autocard/texture/roles/card/role_7.png"
    )


def test_prompt_helpers_keep_item_ids_and_descriptions() -> None:
    dataset = _dataset()
    matches = [
        ("card", dataset.cards[0]),
        ("role", dataset.roles[0]),
    ]

    assert build_autocard_prompt_values(matches) == (
        AutocardPromptValue(kind="card", item_id=CARD_ID),
        AutocardPromptValue(kind="role", item_id=ROLE_ID),
    )

    text = build_autocard_prompt_text(dataset, matches)

    assert "1. 布布种子（精灵牌 101 普通 Lv2 草）" in text
    assert "2. 破界者（角色 201 火）" in text
    assert "输入 0 退出" in text


def test_format_autocard_public_info_includes_query_examples() -> None:
    text = format_autocard_public_info()

    assert "群星牌布布种子" in text
    assert "群星牌金币卡" in text
