# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ironsbot.services.bilibili.commands import is_dynamic_selection


def test_dynamic_selection_accepts_any_numeric_reply() -> None:
    assert is_dynamic_selection("11")
    assert is_dynamic_selection("0")
    assert not is_dynamic_selection("第11条")
