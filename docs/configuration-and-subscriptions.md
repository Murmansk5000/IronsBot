# 配置、消息与订阅

行为与部署配置默认写在 TOML 文件里，并通过 `APP_CONFIG_PATH` 指向它。环境变量包含：

- 配置位置：`APP_CONFIG_PATH`
- 密钥：`ONEBOT_ACCESS_TOKEN`、每个官方账号的 `APP_SECRET_<AppID>`、
  每个 AI 提供商的 `AI_KEY_<提供商别名>`、
  按账号库配置的 `SEER_PASSWORD_<米米号>`、`SENDPIC_CNB_TOKEN`、
  `GITHUB_WORKFLOW_TOKEN`，以及启用私有扩展时使用的 Docker Registry 凭据
- Unraid 部署覆盖：`ONEBOT_ENABLED`、`ONEBOT_SEND_MESSAGES`、
  `ONEBOT_IDENTITY_VERIFICATION` 和 `ONEBOT_TRUSTED_OFFICIAL_BOT_<账号别名>`

示例配置按用户可见功能和运行依赖排列，而不是按 Python 模块名排列。新增功能或配置项前，先参照
[配置布局与新增功能指南](configuration-layout.md)，确认它应归入消息推送、赛尔实时无头查询、
赛尔本地资料，还是数据同步与生命周期。

示例环境变量：

```env
APP_CONFIG_PATH=/config/ironsbot.toml
ONEBOT_ACCESS_TOKEN=change-me
ONEBOT_ENABLED=true
ONEBOT_SEND_MESSAGES=true
ONEBOT_IDENTITY_VERIFICATION=false
ONEBOT_TRUSTED_OFFICIAL_BOT_EXAMPLE_BOT=
APP_SECRET_10001=
AI_KEY_DEEPSEEK=
# 若 TOML 声明了 fumin、nomiss，还可分别设置：
AI_KEY_FUMIN=
AI_KEY_NOMISS=
# 为 [[seer.player_accounts]] 中需要登录的账号设置明文密码；机器人会在内存中转为 MD5。
SEER_PASSWORD_123456789=
SEER_PASSWORD_987654321=
SENDPIC_CNB_TOKEN=
GITHUB_WORKFLOW_TOKEN=
DOCKER_REGISTRY_USERNAME=
DOCKER_REGISTRY_TOKEN=
```

## 配置文件与启动校验

`APP_CONFIG_PATH` 是容器内路径。Docker/Unraid 常用值是 `/config/ironsbot.toml`；
宿主机上的真实位置取决于你把哪个目录挂载到了 `/config`。例如 Windows Docker
Desktop 可以把任意可写目录挂载到 `/config`：

```text
<你的 Windows 配置目录>\ironsbot.toml -> /config/ironsbot.toml
```

该文件必须在启动前存在，可直接以 [config.example.toml](../config.example.toml) 为模板。
程序只读配置，不会修改磁盘上的 TOML。未知或已删除的 TOML 字段会按完整路径记录
warning 后忽略且不会生效；普通功能组合及群／用户策略中的未注册权限项也按位置
告警并忽略，不授予权限。其他已知字段的类型、取值、必填项及身份引用仍严格校验，
错误时阻止启动。真实 env 文件包含密钥，不纳入仓库；
使用 Docker Compose 时可参考 [.env.example](../.env.example) 手动创建。

改动 TOML 或环境变量后，可以只执行配置校验，不启动 NoneBot、QQ 官方连接、
调度器、数据库或其他网络客户端：

```bash
python -m ironsbot.config_check --config /config/ironsbot.toml
```

源码环境可将 `python` 换成 `uv run python`。命令默认按正常启动顺序读取 `.env` 和
`.env.<ENVIRONMENT>`；容器环境只使用已经注入的变量时可加 `--no-dotenv`。成功输出只包含
所选发送平台、已启用的官方账号别名和 AI provider 别名/模型数量，不输出 Key、AppID、
OpenID、QQ 号或密码。建议复制生产 TOML 后先对副本运行，再修改真实生产配置。

如果没有设置 `APP_CONFIG_PATH`，IronsBot 会默认读取当前工作目录的
`config/ironsbot.toml`；文件不存在会立即报错。日志默认写入当前工作目录的 `logs/`，
运行数据默认写入 `data/`。Docker/Unraid 推荐额外挂载
`/app/logs`，启用文件日志后完整日志和错误日志都能在宿主机上直接查看。
默认按本地时间每天 `00:00` 轮转，保留 30 天且不压缩；可在 `[bot.logging]` 按磁盘空间调整。

## 文本、B站与战队配置示例

示例 TOML：

```toml
[identities.groups]
admin = { qq = 123456789 }
example = { qq = 987654321 }

[identities.users]
owner = { qq = 1234567890 }

[features]
superuser_bypass = true

[features.bundles]
all = ["my_extension_feature"]
standard = ["seer", "player_lineup_private", "image", "seerinfo", "bili_query", "bili_push", "seer_activity_query", "seer_activity_push", "server_status_query", "ai_intent"]
lite = ["seer_pet", "seer_player", "player_lineup_private", "seer_team", "seer_equipment", "seer_type", "seer_peak", "seer_autocard", "seer_rank", "seer_data"]

[features.group_policy]
admin = ["admin_notice"]
example = ["standard", "meeting", "team_resource_subscription"]

[features.user_policy]
owner = ["all", "admin_notice"]

[[messaging.commands]]
id = "seerinfo_page"
commands = ["xm", "xrym", "雷小伊", "重聚"]
messages = ["https://seerinfo.yuyuqaq.cn/"]
feature = "seerinfo"

[bilibili.accounts.seer]
uid = 1310714247

[bilibili.push]
accounts = ["seer"]
mode = "link"
modes = { seer = "full" }

[bilibili.push.groups.example]
accounts = []
mode = "link"

# 群主/管理员可在群里发送：
# B站账号
# B站推送模式 seer 链接
# 也可使用 B站公开昵称或 UID；QQ 展示只使用公开昵称

[seer.team_resource]
times = ["23:00"]
default_threshold = 1000
default_at_users = ["owner"]

# 群主/管理员在启用 feature 的群里发送：
# 订阅战队123456
# 订阅战队123456 1000 @提醒人
# 战队订阅
# 取消订阅战队123456
```

## B站加强轮询

`bilibili.polling.boost_windows` 以各窗口的 `start` 为起点，每隔 `interval_minutes` 分钟建立一个轮询时段；`offset_seconds` 是相对该时段起点的秒偏移，不是整分钟的秒位。
例如 `23:59:50` 的偏移 `15` 在次日 `00:00:05` 触发。窗口含起点、不含终点；最后一个不完整间隔中达到或超过终点的偏移不触发。
重叠窗口的同一时刻只注册一个加强调度，但各窗口的完成状态仍独立。普通轮询仍按原配置执行；与普通轮询秒位重合时不另建重复的加强任务。

## B站投递与诊断

B站推送只补发明确未提交成功的内容，失败后按 2、5、10 秒重试，最多四轮。
补发按上一轮失败会话数二分批执行，并遵守 `max_parallel_targets` 上限；
`retry_batch_divisor` 默认为 2，可在主动推送配置中调整。
链接、正文与每张原图、拼图或动图独立记账，成功内容不重复发送。
24 小时内的安全未完成任务可在重启后恢复，次数不重置；消息提交结果不确定、
永久错误和缺少逐图回执的旧失败记录不自动重放。
准备好的图片存放在统一缓存目录，缓存丢失时不猜测重建发送清单。

B站推送诊断默认以 INFO 写入主日志，可按 `dynamic=<动态ID>` 筛选同一条推送。
日志包含轮次、批次并发、目标摘要、排队与执行耗时、图片序号/体积/指纹、
冻结缓存命中、实际执行 AppID，以及各单元回执摘要和最终状态统计。
官方图片通道另记录上传准备、COS 分片 PUT、确认、完成和消息提交阶段，
包括安全节点域名、超时参数、HTTP 状态、平台错误码和 trace ID；
DNS、TLS、连接/读取/写入/连接池超时分别标记，不记录签名上传地址或图片内容。
有上传完成但没有消息提交成功回执时，不能据此认定群内已收到图片。

## 功能组合与限制

配置字段、默认值、中英文说明和示例集中维护在
[config.example.toml](../config.example.toml)。查询权限和推送权限是分开的功能名，
例如 `bili_query` 和 `bili_push`；`admin_notice` 只用于管理员通知，不包含在
`all` 里。游戏内每周活动使用 `seer_activity_query` / `seer_activity_push`；
游戏外活动链接使用 `web_activity_link` / `web_activity_push`。消息动作可以
声明自己的 feature 名：`[[messaging.commands]]` 和 `[[messaging.schedules]]`
中的 `feature` 会注册为原子权限，随后可在 `[features.bundles]`、
`group_policy` 和 `user_policy` 中引用，不需要修改 Python 枚举。动作的 `id`
只负责唯一标识动作，不会自动成为权限名。未被内置功能或消息动作声明的权限仍会
阻止启动；动态命令权限会进入 `all`、`text`、`message`，动态定时权限会进入
`all`、`text_push`、`message`。`admin_notice` 仍不会被组合间接授予。
`fire_manual_ad`
只控制主动推送末尾的火火手册链接；`ai_intent_fire_manual`
控制用户明确索要手册链接时的 AI 意图动作。

`[features.bundles]` 可以定义 `standard`、`lite` 等可复用组合；组合之间可以引用，
最终按并集展开。`all = ["my_extension_feature"]` 可把自定义原子 feature 追加到
内置 `all`，并让它成为可在策略中引用的扩展权限。自定义名称不能覆盖内置
feature/组合；未注册功能引用只告警并忽略，组合因此变空时不授予任何权限。
显式空组合、名称冲突和循环引用仍阻止启动。为避免管理异常或静默拦截
被普通群间接获得，`admin_notice` 与 `blacklist` 不能放入组合，必须在
`group_policy` 或 `user_policy` 的目标项中显式写出。

未注册功能权限项不再阻止启动，也不自动改名或恢复旧功能；`all` 显式声明的扩展
功能保留既有含义。未知 B站账号引用、未知 Seer 展示区块和残缺 AI action 仍会
阻止启动，并在校验错误中给出准确路径。
无法识别的多余字段会按完整路径告警后忽略，不继续提供旧字段兼容；
[config.example.toml](../config.example.toml) 是当前唯一权威示例。

在 `group_policy` 或 `user_policy` 的目标项中写入 `blacklist`，可永远静默忽略该
群或用户；超级管理员也不会绕过黑名单。帮助戳一戳提示的限流配置位于
`[features.help]`。所有表示 OneBot QQ 用户、群或 @ 对象的 TOML 值都支持对应别名、
数字字符串或数字 ID；别名在 `[identities.users]` 和
`[identities.groups]` 中定义，纯数字别名不可用。
命令滑动窗口限频放在 `[messaging.command_cooldown]`：同一 QQ 的同一语义命令
跨群、私聊和多个机器人账号共用多个精确滑动窗口，不同语义命令互不影响。
默认关闭；显式设置 `enabled = true` 后，内置窗口是 `60 秒 3 次` 与 `300 秒 5 次`。
成功、失败、超时和异常都会在命令结束后计入相同窗口，超级管理员绕过。玩家基础查询、收集、巅峰、群星牌分别使用
`seer_player`、`seer_player_collection`、`seer_player_peak`、`seer_player_autocard`
四个独立额度，可在 `commands` 中单独覆盖。
同一操作者、机器人、会话、动作和真实目标的重复限制由
`[messaging.command_cooldown.duplicate_window_seconds]` 分别设置：
`taomee = 120`、`local = 0`、`other_network = 120`，单位秒；0 只关闭完成后的重复限制。
执行中仍防重复；失败或取消不新增成功记录，不受上方 `enabled` 影响。
菜单独立等待 120 秒，新根菜单替换旧菜单，返回上级重新计时；
详见[指令分类与菜单计时](command-duplicate-categories.md)。
未启用 AI 时，群内未知 @ 提示复用 `[features.help]` 的提示窗口，并按用户与会话
分别限流；有效的 `@机器人 + 指令` 不受提示限流影响。
常用语义 ID 包括 `seer_player`、`seer_player_collection`、
`seer_player_peak`、`seer_player_autocard`、`seer_team`、
`seer_rank_list`、`seer_rank_player`、`seer_rank_score`、
`server_status_query`、`ai_chat` 和 `data_sync`。动态文本命令使用
`message.<id>`，AI 意图使用
`ai_intent.<action_id>`；对应 `id` 必须稳定且不可为空。

群消息发送额度默认关闭；显式设置 `[messaging.outbound_rate_limit].enabled = true` 后，使用
`[messaging.outbound_rate_limit].windows` 的多个精确滑动窗口。
任一窗口达到上限都会抑制后续普通回复；主动推送与超级管理员触发的群回复会在
每群独立的无上限优先队列中等待，其中超级管理员回复优先。私聊和启用
`admin_notice` 的管理群不计入群额度。

行为配置只属于 `ironsbot.toml`；`.env` 和 Unraid 模板只保存部署参数与密钥。

## AI 提供商与意图

以下为配置片段，合并到完整 TOML 中；仅设置以下字段不会自动给用户或群开启 AI。

```toml
[ai]
provider_order = ["deepseek"]

[ai.providers.deepseek]
base_url = "https://api.deepseek.com"
models = ["deepseek-v4-pro"]
thinking = false
```

设置 `AI_KEY_DEEPSEEK`；新增提供商如 `backup` 时，声明对应表、将名称加入
`provider_order`，并设置 `AI_KEY_BACKUP`。提供商按顺序尝试，各自模型也按数组顺序尝试。
旧 `AI_KEY` 不受支持，`ai.waiting_notice` 已删除。群聊正常 AI 需要正确提及且不被已识别指令占用；
开启“接收所有消息”也不会让普通闲聊自动进入 AI。私聊按当前用户策略决定。
`ai_chat` 控制聊天，`ai_intent` 与具体动作权限控制意图功能；内置查询优先于 AI 回退。
记忆、超时、token 数和输出长度分别在 `[ai]` 配置，不以删除等待提示代替超时处理。

## 会议、图片与定时消息

```toml
[messaging.meeting]
number = "1234567890"
commands = ["开播", "会议"]
template = "会议号：{meeting_number}\n{meeting_url}"

[[messaging.schedules]]
id = "daily-example"
name = "每日提醒"
feature = "daily_example"
time = "12:00:00"
target_groups = ["example"]
messages = ["今天的提醒内容。"]
```

会议模板使用 `meeting_number`、`meeting_url`，功能权限为 `meeting`。
定时任务使用独立稳定 ID，`day_of_week` 可限定星期，`time` 使用含秒的时刻；
需要给目标显式授予 `daily_example`，且配置发送机器人及所需身份端点。
以上配置片段不包含这项授权，合并时在 `features.group_policy.example` 的列表中追加该项。
消息的实际提及对象遵循显式成员优先、否则配置对象、均无则正常回复发送者；不重复附加发起人。
官方端无法解析目标身份时明确提示，不替换成另一位收件人。

固定图、编号图库、覆盖与关闭内置图片见[固定图片配置](examples/fixed-images.md)。
本地图片从配置目录读取，远程素材使用配置的后端；不要将路径误当成容器宿主机路径。

## 关键词与订阅菜单

```toml
[[messaging.keyword_replies]]
id = "example-winrate"
keywords = ["竞技胜率", "竞技胜率榜"]
match_mode = "contains"
feature = "seerinfo"
messages = ["https://seerinfo.yuyuqaq.cn/peak/pvprank/sports/monster"]
```

关键词默认 `exact`，只有显式 `contains` 才使用整条消息包含匹配；固定口令保持完整匹配。
多个命中沿用配置顺序和单次回复规则，详见[文本匹配](text-matching.md)。

私聊 TD 只展示实际选定推送机器人的项目；切换机器人不删除已有退订和时间偏好。
普通 B站账号在 TD 顶层切换整体订阅，仅配置分类的账号进入正文、图片和标签子菜单。
普通账号的旧正文／图片退订不再过滤内容，整体订阅和全文／链接模式仍生效。
赛尔号分类中的抽奖标签显示为“转发抽奖”，分类由当前部署 TOML 决定。

固定时刻项目显示每日或星期与时刻；橱窗显示配置时间，活动结束提醒显示截止前小时数。
可编辑的定时消息优先展示会话“推送时间”覆盖值，恢复默认后使用 TOML。
事件触发的动态、启动及错误通知不虚构发送时刻。群订阅修改仅限有管理权限者，
子菜单 `0` 返回上级，顶层 `0` 退出；退出后可立即重新打开 TD。
通用主题的全部命令、直发、历史与去重规则见[主题推送](push-topics.md)。

[返回 README](../README.md) · [玩家查询](player-query-guide.md) ·
[平台接入细节](qq-platform-guide.md) · [运维](operations-guide.md)

自动拼图采用等高横排、等宽竖排或铺满分行，保持原始顺序、完整内容和比例，
每行宽度一致，不为凑正方形增加大片留白；小图可以放大，大图可以缩小。
布局优先避免某张图过度缩小，再比较实际显示面积和形状；原图自身的空白不会裁掉。
