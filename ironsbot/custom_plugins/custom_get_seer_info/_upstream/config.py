# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    render_cache_dir: Path | None = None
    render_cache_max_size_mb: int = 200
    render_cache_clear_on_startup: bool = True


plugin_config = get_plugin_config(Config)
