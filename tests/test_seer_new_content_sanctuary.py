import asyncio
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Literal
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.onebot.seer.query.commands.new_content import (
    NEW_CONTENT_SERVICES_KEY,
    NEW_CONTENT_SNAPSHOT_KEY,
    _content_prompt,
    _NewContentServices,
    _render_content_prompt,
    _send_item_detail,
)
from ironsbot.services.seer.autocard import AutocardEntry, AutocardPromptValue
from ironsbot.services.seer.data import (
    DataPublicationChangedError,
    DataUnavailableError,
)
from ironsbot.services.seer.new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    NewContentCategory,
    NewContentItem,
    NewContentSnapshot,
    NewContentSnapshotChangedError,
    format_new_content_item_description,
)
from ironsbot.services.seer.new_content_details import (
    NewContentDetailService,
    format_new_content_autocard_sanctuary_effect_detail,
    format_new_content_skill_detail,
)
from ironsbot.services.seer.new_content_menu import (
    NewContentMenuLayout,
    focus_new_content_category,
)
from ironsbot.services.seer.pet_query import PetImageSelection
from ironsbot.services.seer.query_result import QueryReply, QueryResult
from tests.helpers.onebot_events import group_message_event


def _menu_snapshot(item: NewContentItem) -> NewContentSnapshot:
    return NewContentSnapshot(
        baseline_established=True,
        config_version="20260912",
        weekly_cycle="2026-09-11",
        items=(item,),
    )


def _selection_scope(_snapshot: NewContentSnapshot) -> nullcontext[None]:
    return nullcontext()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("category", "selector", "args"),
    [
        ("pet", "pet.select_info", (9,)),
        ("peak_pool", "pet.select_info", (9,)),
        ("peak_expert_pool", "pet.select_info", (9,)),
        ("pet_skin", "pet.select_image", (PetImageSelection(123, "test", 9),)),
        ("mintmark", "mintmark.select_mintmark", (9,)),
        ("suit", "equipment.select", ("suit", 9)),
        ("equip", "equipment.select", ("equip", 9)),
        ("mount", "equipment.select", ("equip", 9)),
    ],
)
@pytest.mark.parametrize("message", ["", "missing"])
async def test_content_detail_reuses_domain_selector(
    category: NewContentCategory,
    selector: str,
    args: tuple[object, ...],
    message: str,
) -> None:
    reply = QueryReply(text="detail", image=b"image", complete=False)
    result = QueryResult[object](reply=reply, message=message)
    dependencies = Mock()
    dependencies.pet.select_info = AsyncMock(return_value=result)
    dependencies.pet.select_image = AsyncMock(return_value=result)
    dependencies.mintmark.select_mintmark = AsyncMock(return_value=result)
    dependencies.equipment.select = AsyncMock(return_value=result)
    service = NewContentDetailService(
        dependencies.pet,
        dependencies.mintmark,
        dependencies.equipment,
        dependencies.autocard,
        _selection_scope,
    )
    item = NewContentItem(category, 9, "test", 9, {"resource_id": 123})

    detail = await service.select(_menu_snapshot(item), item)

    assert detail == (message or reply)
    assert len(dependencies.mock_calls) == 1
    call = dependencies.mock_calls[0]
    assert call[0] == selector
    assert call.args == args


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["autocard_card", "autocard_role"])
@pytest.mark.parametrize("found", [True, False])
async def test_content_card_detail_preserves_entry_and_missing_result(
    category: NewContentCategory,
    *,
    found: bool,
) -> None:
    kind = "role" if category == "autocard_role" else "card"
    entry = AutocardEntry(
        kind=kind, item_id=9, name="test", text="detail", image_url="url"
    )
    dependencies = Mock()
    dependencies.autocard.select.return_value = entry if found else None
    service = NewContentDetailService(
        dependencies.pet,
        dependencies.mintmark,
        dependencies.equipment,
        dependencies.autocard,
        _selection_scope,
    )

    item = NewContentItem(category, 9, "test", 9, {})
    detail = await service.select(_menu_snapshot(item), item)

    assert detail is (entry if found else None)
    dependencies.autocard.select.assert_called_once_with(AutocardPromptValue(kind, 9))
    assert len(dependencies.mock_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category", ["skill", "achievement", "autocard_sanctuary_effect"]
)
async def test_content_embedded_detail_does_not_query_current_data(
    category: NewContentCategory,
) -> None:
    dependencies = Mock()
    service = NewContentDetailService(
        dependencies.pet,
        dependencies.mintmark,
        dependencies.equipment,
        dependencies.autocard,
        _selection_scope,
    )

    item = NewContentItem(category, 9, "old menu name", 9, {})
    detail = await service.select(_menu_snapshot(item), item)

    assert isinstance(detail, str) and "old menu name" in detail
    assert dependencies.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [DataUnavailableError, asyncio.CancelledError])
async def test_content_detail_propagates_failure_and_cancellation(
    error: type[BaseException],
) -> None:
    dependencies = Mock()
    dependencies.pet.select_info = AsyncMock(side_effect=error)
    service = NewContentDetailService(
        dependencies.pet,
        dependencies.mintmark,
        dependencies.equipment,
        dependencies.autocard,
        _selection_scope,
    )

    with pytest.raises(error):
        item = NewContentItem("pet", 9, "test", 9, {})
        await service.select(_menu_snapshot(item), item)

    dependencies.pet.select_info.assert_awaited_once_with(9)
    assert len(dependencies.mock_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["before", "after", "none"])
async def test_detail_scope_validates_before_lookup_and_before_result(
    change: str,
) -> None:
    active = False
    item = NewContentItem("pet", 9, "test", 9, {})
    snapshot = _menu_snapshot(item)

    @contextmanager
    def scope(expected: NewContentSnapshot) -> Iterator[None]:
        nonlocal active
        assert expected is snapshot
        if change == "before":
            raise NewContentSnapshotChangedError
        active = True
        try:
            yield
            if change == "after":
                raise DataPublicationChangedError
        finally:
            active = False

    async def select(_pet_id: int) -> QueryResult[object]:
        assert active
        await asyncio.sleep(0)
        assert active
        return QueryResult(reply=QueryReply(text="detail"))

    dependencies = Mock()
    dependencies.pet.select_info = AsyncMock(side_effect=select)
    service = NewContentDetailService(
        dependencies.pet,
        dependencies.mintmark,
        dependencies.equipment,
        dependencies.autocard,
        scope,
    )
    if change == "none":
        assert await service.select(snapshot, item) == QueryReply(text="detail")
    else:
        error = (
            NewContentSnapshotChangedError
            if change == "before"
            else DataPublicationChangedError
        )
        with pytest.raises(error):
            await service.select(snapshot, item)
    assert not active
    assert dependencies.pet.select_info.await_count == (0 if change == "before" else 1)


@pytest.mark.asyncio
async def test_detail_rejects_item_from_another_menu_without_starting_scope() -> None:
    item = NewContentItem("pet", 9, "test", 9, {})
    other = NewContentItem("pet", 10, "other", 10, {})
    dependencies = Mock()
    service = NewContentDetailService(
        dependencies.pet,
        dependencies.mintmark,
        dependencies.equipment,
        dependencies.autocard,
        dependencies.scope,
    )
    with pytest.raises(NewContentSnapshotChangedError):
        await service.select(_menu_snapshot(item), other)
    assert dependencies.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [NewContentSnapshotChangedError, DataPublicationChangedError]
)
async def test_changed_detail_finishes_menu_without_sending_result(
    error: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = NewContentItem("pet", 9, "test", 9, {})
    details = Mock(select=AsyncMock(side_effect=error))
    matcher = Mock(
        state={
            NEW_CONTENT_SERVICES_KEY: _NewContentServices(details, AsyncMock()),
            NEW_CONTENT_SNAPSHOT_KEY: _menu_snapshot(item),
        },
        finish=AsyncMock(),
    )
    messages = Mock()
    monkeypatch.setattr(
        "ironsbot.plugins.onebot.seer.query.commands.new_content.MessageFactory",
        messages,
    )

    await _send_item_detail(item, matcher, group_message_event("1"))

    matcher.finish.assert_awaited_once_with(
        "数据已更新，当前新增内容菜单已失效，重新发送指令查看。"
    )
    messages.assert_not_called()


def _effect(*, change_kind: Literal["added", "modified"] = "added") -> NewContentItem:
    return NewContentItem(
        category="autocard_sanctuary_effect",
        entity_id=9,
        name="潮涌",
        sort_value=9,
        payload={
            "sanctuary_id": 2,
            "sanctuary_name": "沧岚",
            "sanctuary_pet_id": 3105,
            "sanctuary_pet_name": "精灵王测试",
            "unlock_round": 5,
            "buff_id": "50041",
            "buff_param": "2",
            "description": "测试效果",
        },
        change_kind=change_kind,
    )


def test_sanctuary_effect_list_preserves_sanctuary_context() -> None:
    assert format_new_content_item_description(_effect()) == (
        "新增｜沧岚｜精灵王：精灵王测试｜第 5 回合祝印"
    )


def test_sanctuary_effect_detail_explains_blessing_context() -> None:
    detail = format_new_content_autocard_sanctuary_effect_detail(
        _effect(change_kind="modified")
    )

    assert "状态：修改" in detail
    assert "圣域：沧岚" in detail
    assert "阶段：第 5 回合祝印" in detail
    assert "关联精灵王：精灵王测试（3105）" in detail
    assert "关联 Buff：50041（参数：2）" in detail


def test_new_skill_detail_includes_effect_and_linked_pet() -> None:
    skill = NewContentItem(
        category="skill",
        entity_id=38474,
        name="测试技能",
        sort_value=38474,
        payload={
            "power": 150,
            "max_pp": 5,
            "accuracy": 95,
            "priority": 1,
            "info": "测试效果",
            "pets": [{"id": 4927, "name": "超级噗纽", "is_fifth": True}],
        },
    )

    assert format_new_content_item_description(skill) == "新增｜38474｜超级噗纽"
    detail = format_new_content_skill_detail(skill)
    assert "威力：150｜PP：5" in detail
    assert "效果：测试效果" in detail
    assert "超级噗纽（4927）（第五技能）" in detail


def test_new_autocard_prompt_includes_sanctuary_effects() -> None:
    card = NewContentItem(
        category="autocard_card",
        entity_id=98,
        name="测试卡牌",
        sort_value=98,
        payload={},
    )
    role = NewContentItem(
        category="autocard_role",
        entity_id=7,
        name="测试角色",
        sort_value=7,
        payload={},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(card, role, _effect()),
    )

    prompt = _content_prompt(
        snapshot,
        NewContentMenuLayout(
            display_categories=AUTOCARD_NEW_CONTENT_CATEGORIES,
        ),
    )

    assert [item.name for item in prompt.items] == [
        "▶ 新增群星牌",
        "▶ 新增群星牌角色",
        "▶ 新增群星牌圣域",
    ]


def test_new_content_root_menu_only_lists_categories() -> None:
    pet = NewContentItem(
        category="pet",
        entity_id=4927,
        name="超级噗纽",
        sort_value=4927,
        payload={},
    )
    skill = NewContentItem(
        category="skill",
        entity_id=38474,
        name="金属缠绕",
        sort_value=38474,
        payload={},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(pet, skill),
    )

    prompt = _content_prompt(
        snapshot,
        NewContentMenuLayout(
            display_categories=("pet", "skill"),
        ),
    )

    assert [item.name for item in prompt.items if item.is_visible] == [
        "▶ 新增精灵",
        "▶ 新增技能",
    ]
    assert prompt.get_item_by_input("a1") is None
    assert prompt.get_item_by_input("b1") is None
    assert "a1. 超级噗纽" not in prompt.build_message()
    assert "a. ▶ 新增精灵（1 项）" in prompt.build_message()


def test_new_content_category_selection_opens_a_numeric_menu() -> None:
    pet = NewContentItem(
        category="pet",
        entity_id=4927,
        name="超级噗纽",
        sort_value=4927,
        payload={},
    )
    skill = NewContentItem(
        category="skill",
        entity_id=38474,
        name="金属缠绕",
        sort_value=38474,
        payload={},
    )
    achievement = NewContentItem(
        category="achievement",
        entity_id=6171016,
        name="深海之泪",
        sort_value=6171016,
        payload={"point": 10},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(pet, skill, achievement),
    )
    root_layout = NewContentMenuLayout(
        display_categories=("pet", "skill", "achievement"),
    )
    layout = focus_new_content_category(root_layout, "achievement")

    prompt = _content_prompt(snapshot, layout)

    assert prompt.title == "🆕【新增成就】输入编号查看详情：\n"
    assert "1. 深海之泪" in prompt.build_message()
    assert "a. ▶ 新增精灵" not in prompt.build_message()
    assert "b. ▶ 新增技能" not in prompt.build_message()
    assert prompt.get_item_by_input("1") is not None
    assert prompt.get_item_by_input("c1") is None


def test_new_pet_category_uses_plain_numeric_choices() -> None:
    first = NewContentItem(
        category="pet",
        entity_id=4927,
        name="超级噗纽",
        sort_value=4927,
        payload={},
    )
    second = NewContentItem(
        category="pet",
        entity_id=4928,
        name="维克佐斯",
        sort_value=4928,
        payload={},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(first, second),
    )

    prompt = _content_prompt(
        snapshot,
        NewContentMenuLayout(
            display_categories=("pet",),
            focused_category="pet",
        ),
    )

    assert "1. 超级噗纽" in prompt.build_message()
    assert "2. 维克佐斯" in prompt.build_message()
    assert prompt.get_item_by_input("a1") is None


def test_new_content_category_shortcut_uses_numeric_keys() -> None:
    pet = NewContentItem(
        category="pet",
        entity_id=4927,
        name="超级噗纽",
        sort_value=4927,
        payload={},
    )
    skill = NewContentItem(
        category="skill",
        entity_id=38474,
        name="金属缠绕",
        sort_value=38474,
        payload={},
    )
    achievement = NewContentItem(
        category="achievement",
        entity_id=6171016,
        name="深海之泪",
        sort_value=6171016,
        payload={"point": 10},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(pet, skill, achievement),
    )
    layout = NewContentMenuLayout(
        display_categories=("achievement",),
        focused_category="achievement",
    )

    prompt = _content_prompt(snapshot, layout)

    assert "a. " not in prompt.build_message()
    assert "b. " not in prompt.build_message()
    assert "1. 深海之泪" in prompt.build_message()


@pytest.mark.parametrize(
    "render_error", [RuntimeError, NewContentSnapshotChangedError, None]
)
def test_menu_image_and_text_fallback_share_layout_and_sender(
    render_error: type[Exception] | None,
) -> None:
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260904",
        weekly_cycle="2026-09-04",
        items=(_effect(),),
    )
    layout = NewContentMenuLayout(
        display_categories=("autocard_sanctuary_effect",),
        focused_category="autocard_sanctuary_effect",
    )
    event = group_message_event("新增群星牌圣域")
    prompt = _content_prompt(snapshot, layout)
    renderer_calls: list[tuple[object, ...]] = []

    async def renderer(*args: object, **kwargs: object) -> bytes:
        assert not kwargs
        renderer_calls.append(args)
        if render_error is not None:
            raise render_error
        return b"test image"

    message = asyncio.run(
        _render_content_prompt(prompt, snapshot, layout, renderer, event)
    )

    assert isinstance(message, Message)
    assert message[0].type == "at"
    assert message[0].data["qq"] == str(event.user_id)
    assert renderer_calls[0][:3] == (
        snapshot,
        layout.display_categories,
        layout.focused_category,
    )
    selection = prompt.get_item_by_input("1")
    assert selection is not None and selection.value.item == snapshot.items[0]
    if render_error is not None:
        assert "1. 潮涌" in message.extract_plain_text()
        assert "0.【退出】" in message.extract_plain_text()
    else:
        assert message[-1].type == "image"
