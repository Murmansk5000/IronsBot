# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from nonebot import require

from ironsbot.utils.image import to_data_uri

require(name="nonebot_plugin_htmlkit")

TEMPLATES_PATH = Path(__file__).parent.parent / "templates"

__all__ = ["TEMPLATES_PATH", "to_data_uri"]
