# SPDX-License-Identifier: MIT
from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from httpx import HTTPError

from ironsbot.services.bilibili.live_models import (
    LiveObservation,
    LiveStatusUnavailableError,
)

if TYPE_CHECKING:
    from httpx import AsyncClient

LIVE_STATUS_URL = "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"


async def fetch_live_status(
    client: AsyncClient, uids: list[int]
) -> dict[int, LiveObservation]:
    if not uids:
        return {}
    try:
        response = await client.get(
            LIVE_STATUS_URL,
            params=[("uids[]", str(uid)) for uid in uids],
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://live.bilibili.com/",
            },
            timeout=10,
        )
        payload = response.json() if response.status_code == HTTPStatus.OK else None
    except (HTTPError, ValueError, TypeError) as error:
        raise LiveStatusUnavailableError(type(error).__name__) from error
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise LiveStatusUnavailableError.http(response.status_code)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise LiveStatusUnavailableError.invalid()
    result = {}
    for uid in uids:
        row = data.get(str(uid))
        if not isinstance(row, dict) or row.get("live_status") not in {0, 1, 2}:
            continue
        try:
            room = int(row.get("room_id", 0))
            if room <= 0 or int(row.get("uid", 0)) != uid:
                continue
            result[uid] = LiveObservation(
                uid,
                room,
                row["live_status"] == 1,
                int(row.get("live_time", 0)),
                str(row.get("title") or ""),
                str(row.get("uname") or f"UID {uid}"),
            )
        except (ValueError, TypeError):
            continue
    return result
