# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import require

from ironsbot.services.seer.render_paths import UPSTREAM_SEER_INFO_TEMPLATES_PATH
from ironsbot.utils.image import to_data_uri

require(name="nonebot_plugin_htmlkit")

TEMPLATES_PATH = UPSTREAM_SEER_INFO_TEMPLATES_PATH

__all__ = ["TEMPLATES_PATH", "to_data_uri"]
