# SPDX-License-Identifier: MIT
"""Protocol failures without framework objects or untrusted response text."""

from __future__ import annotations


class OneBotActionError(Exception):
    def __init__(self, retcode: int | None = None) -> None:
        self.retcode = retcode
        super().__init__("OneBot action rejected")


class OneBotTransportError(Exception):
    def __init__(self, *, definitely_not_sent: bool = False) -> None:
        self.definitely_not_sent = definitely_not_sent
        super().__init__("OneBot transport unavailable")
