# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.integrations.seer_data.pet_display_data import (
    _load_soulmark_display_data,
)


class _DisplayFactSession:
    def execute(self, *_args: object, **_kwargs: object) -> list[tuple[int, int, str]]:
        return [(10, 0, "base"), (20, 1, "partner_upgrade")]


def test_load_soulmark_display_data_reads_order_and_published_kind() -> None:
    order, kinds = _load_soulmark_display_data(_DisplayFactSession(), 7000)  # type: ignore[arg-type]

    assert order == {10: 0, 20: 1}
    assert kinds == {10: "base", 20: "partner_upgrade"}
