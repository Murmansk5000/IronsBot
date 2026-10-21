# SPDX-License-Identifier: MIT
"""Bounded platform explanations without identifiers or upload credentials."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_ROUTE = re.compile(r"^/v2/(groups|users)/[^/]+/([a-z_]+)$")


def request_endpoint(url: str) -> str:
    match = _ROUTE.fullmatch(urlsplit(url).path)
    if match is None:
        return "平台未提供接口模板"
    return f"/v2/{match[1]}/{{target}}/{match[2]}"
