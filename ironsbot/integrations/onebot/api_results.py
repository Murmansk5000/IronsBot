# SPDX-License-Identifier: MIT
"""Authoritative OneBot action-envelope validation for HTTP and WebSocket."""

from __future__ import annotations

from collections.abc import Mapping

from ironsbot.integrations.onebot.errors import OneBotActionError


def onebot_api_result(payload: object) -> object:
    if not isinstance(payload, Mapping):
        raise OneBotActionError
    status, retcode = payload.get("status"), payload.get("retcode")
    if status == "ok" and type(retcode) is int and retcode == 0:
        return payload.get("data")
    if status == "async" and type(retcode) is int and retcode == 1:
        return None
    raise OneBotActionError(retcode if type(retcode) is int else None)
