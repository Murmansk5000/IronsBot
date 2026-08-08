# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from ironsbot.services.seer.flash_mount_images import load_flash_mount_image
from ironsbot.services.seer.formatting import format_sub_lines
from ironsbot.services.seer.images import fetch_optional_image
from ironsbot.services.seer.query_result import (
    QueryChoice,
    QueryReply,
    QueryResult,
)

if TYPE_CHECKING:
    from seerapi_models import AchievementORM, EquipORM, SuitORM, TitlePartORM

    from ironsbot.services.seer.data import DataGetter, SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource

EquipmentKind = Literal["suit", "equip", "title"]
PROMPT_MAX_ITEMS = 20
MOUNT_PART_TYPE_ID = 6
EQUIP_PART_TYPE_MAP = {
    0: "头部",
    1: "眼部",
    2: "腰部",
    3: "手部",
    4: "脚部",
    5: "背景",
    MOUNT_PART_TYPE_ID: "星际座驾",
}


@dataclass(frozen=True, slots=True)
class _EquipmentReplyData:
    kind: EquipmentKind
    item_id: int
    text: str
    is_mount: bool = False


class EquipmentQueryService:
    def __init__(
        self,
        data: SeerDataAccess,
        images: SeerImageSource,
    ) -> None:
        self._data = data
        self._images = images

    async def search(
        self,
        kind: EquipmentKind,
        arg: str,
    ) -> QueryResult[int]:
        getter = self._getter(kind)
        with self._data.resolve(getter, arg) as values:
            items = tuple(values)
            if not items:
                return QueryResult()
            if len(items) == 1:
                reply_data = self._reply_data(kind, items[0])
            elif len(items) > PROMPT_MAX_ITEMS:
                return QueryResult(
                    message=f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！"
                )
            else:
                return QueryResult(
                    choices=tuple(
                        QueryChoice(
                            name=str(item.name),
                            description=str(item.id),
                            value=int(item.id),
                        )
                        for item in items
                    ),
                )
        return QueryResult(reply=await self._build_reply(reply_data))

    async def select(
        self,
        kind: EquipmentKind,
        item_id: int,
    ) -> QueryResult[int]:
        with self._data.get(self._getter(kind), item_id) as item:
            if item is None:
                return QueryResult(
                    message=(
                        f"❌未找到{self._entity_name(kind)} {item_id}"
                        "（这是一个bug，请反馈给开发者）"
                    )
                )
            reply_data = self._reply_data(kind, item)
        return QueryResult(
            reply=await self._build_reply(reply_data)
        )

    def _getter(self, kind: EquipmentKind) -> DataGetter[Any]:
        return cast(
            "DataGetter[Any]",
            {
                "suit": self._data.suit,
                "equip": self._data.equip,
                "title": self._data.title,
            }[kind],
        )

    def _reply_data(
        self,
        kind: EquipmentKind,
        item: Any,
    ) -> _EquipmentReplyData:
        text = (
            self._format_suit(cast("SuitORM", item))
            if kind == "suit"
            else self._format_equip(cast("EquipORM", item))
            if kind == "equip"
            else self._format_title(cast("TitlePartORM", item))
        )
        return _EquipmentReplyData(
            kind=kind,
            item_id=int(item.id),
            text=text,
            is_mount=(
                kind == "equip"
                and int(getattr(getattr(item, "part_type", None), "id", -1))
                == MOUNT_PART_TYPE_ID
            ),
        )

    async def _build_reply(
        self,
        reply_data: _EquipmentReplyData,
    ) -> QueryReply:
        image = await fetch_optional_image(
            self._images,
            reply_data.kind,
            str(reply_data.item_id),
        )
        if (
            reply_data.is_mount
            and image.data is None
            and (
                flash_image := load_flash_mount_image(
                    self._data,
                    reply_data.item_id,
                )
            )
        ):
            return QueryReply(text=reply_data.text, image=flash_image)
        if (
            reply_data.is_mount
            and image.data is None
            and "原因：404" in image.error
        ):
            return QueryReply(
                text=(
                    f"{reply_data.text}\n"
                    "图片：官方图片暂未上线，暂无法展示。"
                )
            )
        return QueryReply(
            text=reply_data.text,
            image=image.data,
            image_error=image.error,
        )

    @staticmethod
    def _format_suit(suit: SuitORM) -> str:
        equips = []
        for equip in suit.equips:
            text = (
                f"{EQUIP_PART_TYPE_MAP[equip.part_type.id]}："
                f"{equip.name}（{equip.id}）"
            )
            if equip.bonus:
                text += f"\n    效果：{equip.bonus.desc}"
            equips.append(text)
        bonus_desc = suit.bonus.desc if suit.bonus else "无"
        return (
            f"【{suit.name}】\n"
            f"🆔：{suit.id}\n"
            "部件：\n"
            f"{format_sub_lines(equips)}"
            f"套装效果：{bonus_desc}"
        )

    @staticmethod
    def _format_equip(equip: EquipORM) -> str:
        lines = [
            f"【{equip.name}】",
            f"🆔：{equip.id}",
            f"部件类型：{EQUIP_PART_TYPE_MAP[equip.part_type.id]}",
        ]
        if equip.suit:
            lines.append(f"所属套装：{equip.suit.name}（{equip.suit.id}）")
        lines.append(f"效果：{equip.bonus.desc if equip.bonus else '无'}")
        return "\n".join(lines)

    @staticmethod
    def _format_title(title: TitlePartORM) -> str:
        lines = [f"【{title.name}】", f"🆔：{title.id}"]
        achievement = cast("AchievementORM | None", title.achievement)
        if achievement is not None:
            lines.append(f"成就点数：{achievement.point}点")
        if title.ability_desc:
            lines.append(f"效果：{title.ability_desc}")
        return "\n".join(lines)

    @staticmethod
    def _entity_name(kind: EquipmentKind) -> str:
        return {"suit": "套装", "equip": "装备部件", "title": "称号"}[kind]
