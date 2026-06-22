# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nonebot.log import logger

from ironsbot.config import get_app_config
from ironsbot.services.ai.notifier import notify_superusers_once

if TYPE_CHECKING:
    from collections.abc import Iterator

MARKER_PATH = Path("data/seer/render_crash_marker.json")
LOG_TAIL_BYTES = 16 * 1024
LOG_TAIL_LINES = 24
NOTICE_MAX_CHARS = 3000


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
        logger.opt(exception=True).warning("failed to read render crash marker")
        return {"raw": "渲染崩溃标记存在，但内容读取失败"}

    return data if isinstance(data, dict) else {"raw": raw}


def _clear_marker() -> None:
    try:
        MARKER_PATH.unlink(missing_ok=True)
    except OSError:
        logger.opt(exception=True).warning("failed to clear render crash marker")


def _read_log_tail() -> str:
    log_config = get_app_config().runtime.logging
    if not log_config.file_enabled:
        return "文件日志未启用。"

    path = Path(log_config.file_path)
    if not path.exists():
        return f"日志文件不存在：{path}"

    try:
        with path.open("rb") as file:
            file.seek(0, 2)
            size = file.tell()
            file.seek(max(0, size - LOG_TAIL_BYTES))
            raw = file.read().decode("utf-8", errors="replace")
    except OSError:
        logger.opt(exception=True).warning("failed to read render crash log tail")
        return f"日志读取失败：{path}"

    lines = raw.splitlines()[-LOG_TAIL_LINES:]
    return "\n".join(lines)


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


def _truncate_notice(text: str) -> str:
    if len(text) <= NOTICE_MAX_CHARS:
        return text

    return text[: NOTICE_MAX_CHARS - 20] + "\n...（已截断）"


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


async def report_previous_render_crash() -> None:
    marker = _read_marker()
    if marker is None:
        return

    _clear_marker()
    log_tail = _read_log_tail()
    notice = _truncate_notice(
        "⚠️ 机器人上次可能在精灵信息渲染时异常退出。\n"
        "这类崩溃通常发生在 Chromium/htmlkit/native 渲染层，"
        "Python 不一定能捕获 traceback。\n\n"
        f"【崩溃前任务】\n{_format_marker(marker)}\n\n"
        f"【最近日志】\n{log_tail}"
    )
    key = "seer-render-crash-" + str(marker.get("started_at", "unknown"))
    await notify_superusers_once(key, notice)


__all__ = [
    "render_crash_marker",
    "report_previous_render_crash",
]
