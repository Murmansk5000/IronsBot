from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core.outbound import BinaryImagePart, TextPart
from ironsbot.integrations.seer_data.autocard_repository import (
    AutocardDataset,
    PublishedAutocardRepository,
    load_autocard_dataset,
)
from ironsbot.services.seer.autocard import (
    AutocardPromptValue,
    AutocardService,
    _build_autocard_index,
)
from ironsbot.services.seer.autocard_media import AutocardMediaService

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ironsbot.services.seer.data import SeerDataAccess

CARD_ID = 101
AWAKENED_CARD_ID = 10101
SECOND_CARD_ID = 102
THIRD_CARD_ID = 103
AWAKENED_THIRD_CARD_ID = 10103
ROLE_ID = 201
VARIANT_IMAGE_COUNT = 2

CARDS = (
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
        "composeTo": AWAKENED_CARD_ID,
        "picID": 1,
        "cardTxt": "回合开始时回复1点生命",
        "des": "经典草系精灵牌",
    },
    {
        "id": AWAKENED_CARD_ID,
        "name": "布布种子",
        "type": 1,
        "nature": 1,
        "level": 2,
        "cost": 3,
        "attack": 6,
        "health": 10,
        "compose": 1,
        "composeTo": 0,
        "picID": 1,
        "cardTxt": "回合开始时回复2点生命",
        "des": "经典草系精灵牌",
    },
    {
        "id": SECOND_CARD_ID,
        "name": "破界法术",
        "type": 2,
        "nature": 2,
        "level": 1,
        "cost": 2,
        "attack": 0,
        "health": 0,
        "compose": 0,
        "composeTo": 0,
        "picID": 2,
    },
    {
        "id": THIRD_CARD_ID,
        "name": "布布花",
        "type": 1,
        "nature": 1,
        "level": 3,
        "cost": 3,
        "attack": 4,
        "health": 5,
        "compose": 0,
        "composeTo": AWAKENED_THIRD_CARD_ID,
        "picID": 2,
        "cardTxt": "护盾",
        "des": "",
    },
    {
        "id": AWAKENED_THIRD_CARD_ID,
        "name": "觉醒布布花",
        "type": 1,
        "nature": 1,
        "level": 3,
        "cost": 3,
        "attack": 4,
        "health": 5,
        "compose": 1,
        "composeTo": 0,
        "picID": 3,
        "cardTxt": "护盾",
        "des": "",
    },
)
ROLES = (
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
)
NATURES = ({"id": 1, "name": "草"}, {"id": 2, "name": "火"})


class FakeResult:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self._rows = rows

    def all(self) -> tuple[tuple[object, ...], ...]:
        return self._rows


class FakeSession:
    def execute(self, query: object) -> FakeResult:
        sql = str(query)
        if "autocard_role_raw" in sql:
            return FakeResult(
                tuple(
                    (
                        value["id"],
                        value["name"],
                        value["desc"],
                        value["health"],
                        value["skillTxt"],
                        value["nature"],
                        value["picID"],
                        value.get("skillID", 0),
                        value["skillName"],
                        value["skillUpgrade"],
                        json.dumps(value, ensure_ascii=False),
                    )
                    for value in ROLES
                )
            )
        values = (
            CARDS
            if "autocard_card" in sql
            else ROLES
            if "autocard_role" in sql
            else NATURES
        )
        return FakeResult(
            tuple((json.dumps(value, ensure_ascii=False),) for value in values)
        )


class FakeData:
    @contextmanager
    def query(
        self,
        operation: Callable[[Any], Any],
    ) -> Iterator[Any]:
        yield operation(FakeSession())


def _service() -> AutocardService:
    return AutocardService(
        PublishedAutocardRepository(cast("SeerDataAccess", FakeData()))
    )


def test_autocard_search_merges_normal_and_awakened_card() -> None:
    result = _service().search("群星牌布布种子")

    assert result.entry is not None
    assert result.entry.item_id == CARD_ID
    assert "🃏【群星牌】" in result.entry.text
    assert "布布种子（普通ID：101｜觉醒ID：10101）" in result.entry.text
    assert "类型：精灵牌 | 属性：草 | 等级：2 | 费用：3" in result.entry.text
    assert "普通身材：3/5" in result.entry.text
    assert "觉醒身材：6/10" in result.entry.text
    assert "普通效果：回合开始时回复1点生命" in result.entry.text
    assert "觉醒效果：回合开始时回复2点生命" in result.entry.text
    assert result.entry.text.count("描述：经典草系精灵牌") == 1
    assert result.entry.image_keys == ("card_1",)


def test_autocard_search_supports_card_id_and_rejects_plain_number() -> None:
    service = _service()

    normal = service.search(f"卡{CARD_ID}").entry
    awakened = service.search(f"卡{AWAKENED_CARD_ID}").entry

    assert normal is not None
    assert awakened is not None
    assert normal.text == awakened.text
    assert normal.item_id == awakened.item_id == CARD_ID
    assert service.search(str(CARD_ID)).entry is None
    assert service.search("").entry is None


def test_autocard_search_returns_selection_prompt_for_multiple_matches() -> None:
    result = _service().search("破界")

    assert result.prompt_values == (
        AutocardPromptValue(kind="card", item_id=SECOND_CARD_ID),
        AutocardPromptValue(kind="role", item_id=ROLE_ID),
    )
    assert "1. 破界法术（法术牌 102 普通 Lv1 火）" in result.prompt_text
    assert "2. 破界者（角色 201 火）" in result.prompt_text
    assert "0. 【退出】" in result.prompt_text


def test_autocard_partial_search_lists_each_card_pair_once() -> None:
    result = _service().search("布布")

    assert result.prompt_values == (
        AutocardPromptValue(kind="card_group", item_id=CARD_ID),
        AutocardPromptValue(kind="card_group", item_id=THIRD_CARD_ID),
    )
    assert "1. 布布种子（" in result.prompt_text
    assert "2. 布布花 / 觉醒布布花（" in result.prompt_text
    assert "3." not in result.prompt_text
    assert "普通101/觉醒10101" in result.prompt_text


def test_autocard_search_matches_awakened_variant_name() -> None:
    entry = _service().search("群星牌觉醒布布花").entry

    assert entry is not None
    assert entry.item_id == THIRD_CARD_ID
    assert "普通：布布花（ID：103）" in entry.text
    assert "觉醒：觉醒布布花（ID：10103）" in entry.text


def test_autocard_group_shows_identical_variant_fields_once() -> None:
    entry = _service().search("群星牌布布花").entry

    assert entry is not None
    assert entry.text.count("身材：4/5") == 1
    assert "普通身材" not in entry.text
    assert "觉醒身材" not in entry.text
    assert entry.text.count("效果：护盾") == 1
    assert entry.image_keys == ("card_2", "card_3")


def test_autocard_outbound_controls_images_without_rebuilding_text() -> None:
    entry = _service().search("群星牌布布花").entry

    assert entry is not None
    complete = entry.to_outbound(image_contents=(b"normal", b"awakened"))
    primary = entry.to_outbound(image_contents=(b"normal",))
    text_only = entry.to_outbound()

    assert (
        sum(isinstance(part, BinaryImagePart) for part in complete.parts)
        == VARIANT_IMAGE_COUNT
    )
    assert sum(isinstance(part, BinaryImagePart) for part in primary.parts) == 1
    assert text_only.parts == (TextPart(entry.text),)


@pytest.mark.asyncio
async def test_autocard_media_uses_versioned_asset_keys_and_skips_missing() -> None:
    class Images:
        def __init__(self) -> None:
            self.requests: list[tuple[str, str, bool]] = []

        async def fetch(self, kind: str, key: str, *, fallback: bool) -> bytes:
            self.requests.append((kind, key, fallback))
            if key == "card_3":
                raise RuntimeError("missing")
            return key.encode()

    entry = _service().search("群星牌布布花").entry
    assert entry is not None
    images = Images()

    message = await AutocardMediaService(images).outbound(entry)  # type: ignore[arg-type]

    assert images.requests == [
        ("autocard_card", "card_2", False),
        ("autocard_card", "card_3", False),
    ]
    assert message.parts == (
        BinaryImagePart(b"card_2", "image/png"),
        TextPart(entry.text),
    )


def test_autocard_raw_selection_keeps_single_card_for_new_content() -> None:
    entry = _service().select(AutocardPromptValue("card", CARD_ID))

    assert entry is not None
    assert "布布种子（ID：101，普通）" in entry.text
    assert "觉醒ID" not in entry.text


def test_autocard_without_awakened_variant_stays_single() -> None:
    entry = _service().search("群星牌破界法术").entry

    assert entry is not None
    assert "破界法术（ID：102，普通）" in entry.text
    assert "觉醒ID" not in entry.text


def test_invalid_autocard_compose_relation_is_not_grouped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    card = {"id": 1, "name": "测试卡牌", "compose": 0, "composeTo": 999}

    index = _build_autocard_index(AutocardDataset(cards=(card,), roles=(), natures={}))

    assert index.base_id_by_card_id == {}
    assert index.awakened_id_by_base_id == {}
    assert "invalid autocard compose relation: base_id=1 target_id=999" in caplog.text


def test_autocard_select_returns_rendered_role_entry() -> None:
    entry = _service().select(AutocardPromptValue("role", ROLE_ID))

    assert entry is not None
    assert "🧑‍🚀【群星牌角色】" in entry.text
    assert "破界者（ID：201）" in entry.text
    assert "属性：火 | 生命：20" in entry.text
    assert "技能：破界" in entry.text
    assert "升级：伤害+1" in entry.text
    assert entry.image_key == "role_7"


def test_autocard_repository_rejects_malformed_published_integer() -> None:
    malformed = dict(CARDS[0], cost="unknown")

    class MalformedSession(FakeSession):
        def execute(self, query: object) -> FakeResult:
            if "autocard_card" in str(query):
                return FakeResult(((json.dumps(malformed, ensure_ascii=False),),))
            return super().execute(query)

    with pytest.raises(RuntimeError, match="群星牌数据格式无效"):
        load_autocard_dataset(cast("Any", MalformedSession()))
