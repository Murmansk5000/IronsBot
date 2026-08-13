from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.exc import SQLAlchemyError

from ironsbot.services.seer.autocard import (
    AutocardPromptValue,
    AutocardService,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ironsbot.services.seer.data import SeerDataAccess

CARD_ID = 101
SECOND_CARD_ID = 102
ROLE_ID = 201

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
        "picID": 1,
        "cardTxt": "回合开始时回复1点生命",
        "des": "经典草系精灵牌",
    },
    {
        "id": SECOND_CARD_ID,
        "name": "破界法术",
        "type": 2,
        "nature": 2,
        "level": 1,
        "cost": 2,
        "picID": 2,
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
    def __init__(self, *, new_role_schema: bool) -> None:
        self._new_role_schema = new_role_schema

    def execute(self, query: object) -> FakeResult:
        sql = str(query)
        if "autocard_role_raw" in sql:
            if not self._new_role_schema:
                raise SQLAlchemyError
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
    def __init__(self, *, new_role_schema: bool) -> None:
        self._new_role_schema = new_role_schema

    @contextmanager
    def query(
        self,
        operation: Callable[[Any], Any],
    ) -> Iterator[Any]:
        yield operation(FakeSession(new_role_schema=self._new_role_schema))


def _service(*, new_role_schema: bool = True) -> AutocardService:
    return AutocardService(
        cast("SeerDataAccess", FakeData(new_role_schema=new_role_schema))
    )


def test_autocard_search_returns_rendered_card_entry() -> None:
    result = _service().search("群星牌布布种子")

    assert result.entry is not None
    assert result.entry.item_id == CARD_ID
    assert "🃏【群星牌】" in result.entry.text
    assert "布布种子（ID：101，普通）" in result.entry.text
    assert "类型：精灵牌 | 属性：草 | 等级：2 | 费用：3" in result.entry.text
    assert "身材：3/5" in result.entry.text
    assert "效果：回合开始时回复1点生命" in result.entry.text
    assert result.entry.image_url.endswith(
        "/newseer/assets/art/autocard/texture/cards/card_1.png"
    )


def test_autocard_search_supports_card_id_and_rejects_plain_number() -> None:
    service = _service()

    assert service.search(f"卡{CARD_ID}").entry is not None
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
    assert "0.【退出】" in result.prompt_text


def test_autocard_select_returns_rendered_role_entry() -> None:
    entry = _service().select(AutocardPromptValue("role", ROLE_ID))

    assert entry is not None
    assert "🧑‍🚀【群星牌角色】" in entry.text
    assert "破界者（ID：201）" in entry.text
    assert "属性：火 | 生命：20" in entry.text
    assert "技能：破界" in entry.text
    assert "升级：伤害+1" in entry.text
    assert entry.image_url.endswith(
        "/newseer/assets/art/autocard/texture/roles/card/role_7.png"
    )


def test_autocard_select_falls_back_to_legacy_role_raw_json() -> None:
    entry = _service(new_role_schema=False).select(AutocardPromptValue("role", ROLE_ID))

    assert entry is not None
    assert entry.skill_name == ROLES[0]["skillName"]
    assert entry.skill_text == ROLES[0]["skillTxt"]
    assert entry.skill_upgrade == ROLES[0]["skillUpgrade"]
    assert entry.image_url.endswith("/roles/card/role_7.png")
