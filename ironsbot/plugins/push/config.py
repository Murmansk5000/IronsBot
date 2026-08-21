# SPDX-License-Identifier: MIT
from pathlib import Path

from nonebot import get_plugin_config, require
from pydantic import BaseModel, Field

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_data_dir


class Config(BaseModel):
    #: 数据目录（订阅关系、推送历史 SQLite 文件所在目录）
    push_data_dir: Path = get_data_dir("push")
    #: 每个主题保留的最大推送历史条数，超出后自动清理最旧记录
    push_max_history: int = Field(default=500, ge=1)
    #: 去重窗口（秒），窗口内同 dedup_key 的成功推送会被跳过
    push_dedup_window_seconds: int = Field(default=3600, ge=0)
    #: （可选）推送管理命令可用的群号白名单，为空表示不限制
    push_admin_manage_group_ids: set[int] = Field(default_factory=set)


plugin_config = get_plugin_config(Config)
