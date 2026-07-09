from nonebot.plugin import PluginMetadata

from ironsbot.config.models.app import AppConfig

__plugin_meta__ = PluginMetadata(
    name="自定义无头登录",
    description="自定义无头登录状态检查、掉线播报和定时重连",
    usage=(
        "【自定义无头登录】\n"
        "启动后检查 HEADLESS_SEER_USER_ID / HEADLESS_SEER_PASSWORD 是否登录成功。\n"
        "登录状态从在线/离线发生变化时私聊 SUPERUSERS；正常维护窗口内不播报。\n"
        "每天按 runtime.headless_notice.reconnect_check_times "
        "检查无头状态，掉线则尝试重连。\n"
        "超级管理员可发送 /开服查询 触发开服查询和无头重连。"
    ),
    config=AppConfig,
)
