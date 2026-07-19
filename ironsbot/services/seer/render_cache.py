# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Protocol


class RenderCache(Protocol):
    def get(self, category: str, content_key: str) -> bytes | None: ...

    def put(self, category: str, content_key: str, data: bytes) -> None: ...
