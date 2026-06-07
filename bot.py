# SPDX-License-Identifier: MIT
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

EXTERNAL_PLUGINS = (
    "nonebot_plugin_apscheduler",
    "nonebot_plugin_localstore",
    "nonebot_plugin_htmlkit",
    "nonebot_plugin_saa",
)

INFRASTRUCTURE_PLUGINS = (
    "ironsbot.plugins.db_sync",
    "ironsbot.plugins.http_client",
    "ironsbot.plugins.seer_data",
    "ironsbot.plugins.headless_seer",
)

CUSTOM_CORE_PLUGINS = (
    "ironsbot.custom_plugins.superuser_priority",
    "ironsbot.custom_plugins.message_actions",
)

CUSTOM_PLUGINS = (
    "ironsbot.custom_plugins.headless_seer_notice",
    "ironsbot.custom_plugins.ai_chat",
    "ironsbot.custom_plugins.team_shortcut",
    "ironsbot.custom_plugins.activity_reminder",
    "ironsbot.custom_plugins.ai_mention_guard",
    "ironsbot.custom_plugins.ai_intent_actions",
    "ironsbot.custom_plugins.bilibili_monitor",
    "ironsbot.custom_plugins.custom_about",
    "ironsbot.custom_plugins.custom_get_seer_info",
    "ironsbot.custom_plugins.custom_help",
    "ironsbot.custom_plugins.custom_sendpic",
    "ironsbot.custom_plugins.meeting_reply",
    "ironsbot.custom_plugins.pet_config_reply",
    "ironsbot.custom_plugins.rank_help",
    "ironsbot.custom_plugins.scheduled_restart",
    "ironsbot.custom_plugins.server_status",
    "ironsbot.custom_plugins.startup_notice",
)

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)

app = nonebot.get_asgi()

# driver.register_adapter(CONSOLE_Adapter)
# nonebot.load_builtin_plugins("echo")
for plugin in (
    *EXTERNAL_PLUGINS,
    *CUSTOM_CORE_PLUGINS,
    *INFRASTRUCTURE_PLUGINS,
    *CUSTOM_PLUGINS,
):
    nonebot.load_plugin(plugin)

if __name__ == "__main__":
    nonebot.run(host="127.0.0.1", port=8080, app=app)
