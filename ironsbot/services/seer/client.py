# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any

from ironsbot.integrations.headless_seer.client import (
    get_game_client as _get_game_client,
)


def get_game_client() -> Any:
    return _get_game_client()
