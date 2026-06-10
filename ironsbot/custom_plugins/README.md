# 自定义插件目录

这个目录用于放置 IronsBot 的自定义插件。用户可触发的功能应优先放在
`ironsbot/custom_plugins`；`ironsbot/plugins` 只保留基础设施或上游/vendor 代码。

运行入口 `bot.py` 会按显式顺序加载外部插件、基础设施插件和自定义插件。
`pyproject.toml` 不再扫描整个自定义插件目录，避免空目录、试验代码或遗留插件被误加载：

```toml
plugin_dirs = []
```

新增可运行插件后，需要把模块名加入 `bot.py` 的 `CUSTOM_PLUGINS` 列表，避免
NoneBot 无序加载导致依赖插件先后顺序不稳定；没有加入 `bot.py` 的目录只会被视为普通代码。

## 当前插件

```text
ironsbot/custom_plugins/
  ai_chat/           # 接入 DeepSeek API，群聊 @机器人 或授权私聊触发
  bilibili_monitor/   # 监控指定 B 站账号动态，推送到配置的群/用户
  custom_about/       # 新版关于页
  custom_get_seer_info/ # 自定义赛尔号查询、榜单、群星牌、活动入口
  custom_help/        # 按当前群/私聊权限显示可用功能
  custom_sendpic/     # 本地固定关键词发图
  message_actions/    # 通用文本消息动作：指令回复、定时发送、批量推送、事件回复
  meeting_reply/      # 回复“开播/会议”的腾讯会议信息
  pet_config_reply/   # 对“精灵名 + 配置”提示暂不支持配置查询
  startup_notice/     # 机器人启动并连接后私聊通知超级管理员
  team_shortcut/      # 给战队群使用：群内短指令触发预设战队查询
```

## 新增插件

每个插件一个子目录，最小结构如下：

```text
ironsbot/custom_plugins/my_plugin/
  __init__.py
  config.py        # 可选：放配置模型
```

固定文本指令、定时私聊、定时群发优先不要写插件，直接用
`MSG_CONFIG` 配置。确实需要业务逻辑时，插件只负责判断和生成文本，
最终发送走 `message_actions`。

最小业务命令示例：

```python
from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.custom_plugins.message_actions import (
    command_text_matches,
    finish_event_reply,
)
from ironsbot.utils.rule import no_reply


async def _is_ping(event: MessageEvent) -> bool:
    return command_text_matches(event.get_plaintext(), ("ping",))


ping = on_message(rule=Rule(_is_ping) & no_reply(), priority=10, block=True)


@ping.handle()
async def handle_ping(matcher: Matcher, event: MessageEvent) -> None:
    await finish_event_reply(matcher, event, "pong")
```

把代码放进某个插件目录的 `__init__.py`，重启机器人后即可测试。

## 配置原则

不要把 QQ 号、群号、账号、密码、Cookie、token 写死在代码里。公开仓库里只保留空
默认值或无敏感的示例值。

推荐写法：

```python
from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    my_plugin_enabled: bool = True


plugin_config = get_plugin_config(Config)
```

然后在 `.env.dev`、`.env.prod`、Unraid 模板变量或 Docker 环境变量中填实际值。

示例：

```env
GROUP_ALIASES={"admin":686376929,"main":123456789}
FEATURE_GROUP_POLICY={"admin":["admin_notice"],"main":["seer","meeting","activity_query","bili_query","bili_push","team","ai_chat","ai_intent"]}

MEETING_NUMBER=1234567890
MEETING_TEMPLATE="腾讯会议\n腾讯会议号：{meeting_number}\n点击链接直接加入：{meeting_url}"

BILI_CONFIG={"uids":[1310714247,123456789],"storage":{"data_dir":"data/bilibili_monitor","history_max_items":1000},"polling":{"default_minutes":30,"windows":[{"start":"07:00","end":"23:00","minutes":5}]},"push":{"default_mode":"full","link_only_groups":[],"link_only_users":[]},"filters":{"suppress_push_patterns":["恭喜.*获得","记得及时查看私信通知","中奖","抽奖结果"]}}

STARTUP_CONFIG={"enabled":true,"message":"机器人已开启。","delay":0}
HEADLESS_NOTICE_CONFIG={"login_notice":true,"state_notice":true,"reconnect_check_times":"00:01,00:02"}
SERVER_STATUS_CONFIG={"broadcast":false,"broadcast_message":"赛尔号已经开服了。","broadcast_cooldown_minutes":1440}

# 群聊中由用户触发的文本回复是否在开头 @ 触发者；自动推送和定时消息不受影响。
MSG_CONFIG={
  "reply": {
    "default_lines": -1,
    "min_lines": 5,
    "max_lines": 80,
    "limit_path": "data/message_actions/reply_limits.sqlite"
  },
  "private_commands": [
    {
      "id": "activity_link_private",
      "commands": ["签到", "活动", "链接"],
      "feature": "activity_link",
      "message": "周年庆主题站签到活动：https://seerm.61.com/events/17years/#sign"
    }
  ],
  "private_schedules": [],
  "group_commands": [
    {
      "id": "activity_link_group",
      "feature": "activity_link",
      "commands": ["签到", "活动", "链接"],
      "message": "周年庆主题站签到活动：https://seerm.61.com/events/17years/#sign"
    }
  ],
  "group_schedules": [
    {
      "id": "activity_link_daily",
      "feature": "activity_link_push",
      "hour": 23,
      "minute": 0,
      "message": "周年庆主题站签到活动：https://seerm.61.com/events/17years/#sign"
    }
  ]
}

TEAM_IDS=[]
TEAM_RESOURCE_USERS=[]
TEAM_CONFIG={"commands":["战队"],"resource_threshold":1000,"query_timeout_seconds":20,"resource_message":"出来买资源，别逼我求你😡"}

AI_KEY=sk-...
AI_CONFIG={"base_url":"https://api.deepseek.com","model":"deepseek-v4-pro","intent_actions_enabled":true,"action_templates":{"keyword_info":{"action":"ai_reply","reply_prompt":"Keywords: {keywords}\nMessage: {message}\nReply briefly."}},"intent_actions":[{"template":"join_team"},{"id":"custom_keyword","template":"keyword_info","keywords":["keyword"]}]}
```

## 本地开发与部署

本地开发时使用 `.env.dev`，生产部署时使用 `.env.prod` 或 Unraid 模板变量。

常见流程：

```text
本地修改插件
  -> 测试
  -> commit
  -> push 到 GitHub main
  -> GitHub Actions 构建镜像
  -> Unraid 拉取新镜像并重启容器
```

如果只改群号、QQ 号、token 等运行配置，不需要重新构建镜像，直接改 `.env.prod`
或 Unraid 容器变量后重启容器即可。

## 隐私检查

提交前建议扫一遍敏感信息：

```powershell
rg "你的QQ号|群号|token|password|cookie" ironsbot/custom_plugins unraid .github
```

`.env.dev` 和 `.env.prod` 已被 `.gitignore` 忽略，不应提交到公开仓库。
