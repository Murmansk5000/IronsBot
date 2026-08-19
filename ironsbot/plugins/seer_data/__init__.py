# SPDX-License-Identifier: MIT
from nonebot import require
from nonebot.plugin import PluginMetadata

require("ironsbot.plugins.db_sync")
require("ironsbot.plugins.http_client")

from . import db, image, sync_cmd  # noqa: F401
from .config import Config
from .sync_cmd import build_usage

__plugin_meta__ = PluginMetadata(
    name="赛尔号数据",
    description="赛尔号 API 数据库同步、查询依赖与游戏资源图片获取",
    usage=build_usage(),
    config=Config,
)
