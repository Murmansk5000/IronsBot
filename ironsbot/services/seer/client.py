# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any


def get_game_client() -> Any:
    from ironsbot.plugins.headless_seer.manager import client_manager

    return client_manager.get_client()
