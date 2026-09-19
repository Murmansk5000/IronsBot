# SPDX-License-Identifier: MIT
"""Shared Docker HTTP response semantics."""

from __future__ import annotations

import httpx


def docker_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()
    if isinstance(payload, dict):
        for key in ("message", "error", "errorDetail"):
            detail = payload.get(key)
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
            if isinstance(detail, dict):
                message = detail.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
    return response.text.strip()


def raise_for_docker_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = docker_error_detail(response)
        if not detail:
            raise
        message = f"Docker API returned HTTP {response.status_code}: {detail}"
        raise RuntimeError(message) from exc
