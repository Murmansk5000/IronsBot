# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Iterable
from typing import Any

from nonebot import logger
from sqlmodel import select


def _lookup_model_names(model: type[Any], ids: Iterable[int]) -> dict[int, str]:
    valid_ids = tuple(dict.fromkeys(int(i) for i in ids if int(i) > 0))
    if not valid_ids:
        return {}

    try:
        from ironsbot.plugins.db_sync.manager import db_manager
    except Exception:  # noqa: BLE001
        return {}

    session_gen = db_manager.get_session("seerapi")
    if session_gen is None:
        return {}

    try:
        session = next(session_gen)
        result: dict[int, str] = {}
        for item_id in valid_ids:
            obj = session.get(model, item_id)
            name = getattr(obj, "name", "") if obj is not None else ""
            if name:
                result[item_id] = str(name)
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).debug("扩展查询名称映射失败")
        return {}
    else:
        return result
    finally:
        session_gen.close()


def lookup_pet_names(ids: Iterable[int]) -> dict[int, str]:
    try:
        from seerapi_models import PetORM
    except Exception:  # noqa: BLE001
        return {}
    return _lookup_model_names(PetORM, ids)


def lookup_title_names(ids: Iterable[int]) -> dict[int, str]:
    try:
        from seerapi_models import TitlePartORM
    except Exception:  # noqa: BLE001
        return {}
    return _lookup_model_names(TitlePartORM, ids)


def lookup_equip_names(ids: Iterable[int]) -> dict[int, str]:
    try:
        from seerapi_models import EquipORM
    except Exception:  # noqa: BLE001
        return {}
    return _lookup_model_names(EquipORM, ids)


def _lookup_decoration_names(model: type[Any], ids: Iterable[int]) -> dict[int, str]:
    valid_ids = tuple(dict.fromkeys(int(i) for i in ids if int(i) > 0))
    if not valid_ids:
        return {}

    try:
        from ironsbot.plugins.db_sync.manager import db_manager
    except Exception:  # noqa: BLE001
        return {}

    session_gen = db_manager.get_session("seerapi")
    if session_gen is None:
        return {}

    try:
        session = next(session_gen)
        result: dict[int, str] = {}
        for item_id in valid_ids:
            obj = session.get(model, item_id)
            if obj is None:
                obj = session.exec(select(model).where(model.id == item_id)).first()
            name = getattr(obj, "name", "") if obj is not None else ""
            if name:
                result[item_id] = str(name)
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).debug("扩展查询装饰名称映射失败")
        return {}
    else:
        return result
    finally:
        session_gen.close()


def lookup_avatar_head_names(ids: Iterable[int]) -> dict[int, str]:
    try:
        from seerapi_models import AvatarHeadORM
    except Exception:  # noqa: BLE001
        return {}
    return _lookup_decoration_names(AvatarHeadORM, ids)


def lookup_avatar_frame_names(ids: Iterable[int]) -> dict[int, str]:
    try:
        from seerapi_models import AvatarFrameORM
    except Exception:  # noqa: BLE001
        return {}
    return _lookup_decoration_names(AvatarFrameORM, ids)
