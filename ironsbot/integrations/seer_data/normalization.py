# SPDX-License-Identifier: MIT
from __future__ import annotations

import re

IGNORED_CHARS = ".·・•‧∙⋅。—\u2013-_/ "
_IGNORED_CHARS_PATTERN = re.compile(f"[{re.escape(IGNORED_CHARS)}]")


def strip_special(text: str) -> str:
    return _IGNORED_CHARS_PATTERN.sub("", text)


def normalize_key(text: str) -> str:
    return strip_special(text).casefold()
