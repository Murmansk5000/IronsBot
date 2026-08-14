# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.messaging.admin_notice import AdminNoticeService

logger = getLogger(__name__)

MARKER_PATH = Path("data/seer/render_crash_marker.json")


def _now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _write_marker(payload: dict[str, Any]) -> None:
    MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    MARKER_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_marker() -> dict[str, Any] | None:
    if not MARKER_PATH.exists():
        return None

    try:
        raw = MARKER_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        logger.exception("failed to read render crash marker")
        return {"raw": "渲染崩溃标记存在，但内容读取失败"}

    return data if isinstance(data, dict) else {"raw": raw}


def _clear_marker() -> None:
    try:
        MARKER_PATH.unlink(missing_ok=True)
    except OSError:
        logger.exception("failed to clear render crash marker")


def _format_marker(marker: dict[str, Any]) -> str:
    fields = [
        ("时间", marker.get("started_at")),
        ("操作", marker.get("operation")),
        ("精灵", marker.get("pet_name")),
        ("精灵ID", marker.get("pet_id")),
        ("资源ID", marker.get("resource_id")),
    ]
    lines = [f"{label}：{value}" for label, value in fields if value not in {None, ""}]
    raw = marker.get("raw")
    if raw:
        lines.append(str(raw))
    return "\n".join(lines) if lines else "未能读取崩溃标记详情。"


@contextmanager
def render_crash_marker(
    *,
    operation: str,
    pet_id: int,
    pet_name: str,
    resource_id: int | None,
) -> Iterator[None]:
    _write_marker(
        {
            "started_at": _now_text(),
            "operation": operation,
            "pet_id": pet_id,
            "pet_name": pet_name,
            "resource_id": resource_id,
        }
    )
    try:
        yield
    finally:
        _clear_marker()


async def report_previous_render_crash(
    admin_notices: AdminNoticeService,
) -> None:
    marker = _read_marker()
    if marker is None:
        return

    _clear_marker()
    notice = (
        "⚠️ 上次精灵信息渲染未正常结束，可能是渲染进程或容器被中断。\n"
        f"{_format_marker(marker)}"
    )
    await admin_notices.send(
        notice,
        subscription_key="render_crash_notice",
        action_name="render crash notice",
    )
