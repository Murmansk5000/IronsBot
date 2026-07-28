# SPDX-License-Identifier: MIT
# ruff: noqa: E501
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.core.messaging import FIXED_IMAGE_COMMANDS
from ironsbot.runtime.commands import CommandDescriptor
from ironsbot.runtime.feature_policy import event_is_feature_visible_in_help

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.config.models.messaging import MessageConfig
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.features import FeatureService


def _commands(
    plugin_id: str,
    section: str,
    feature: str | None,
    rows: tuple[tuple[str, tuple[str, ...], str, dict[str, Any]], ...],
) -> tuple[CommandDescriptor, ...]:
    descriptors = []
    for command_id, examples, description, raw_options in rows:
        options = dict(raw_options)
        command_feature = options.pop("feature", feature)
        descriptors.append(
            CommandDescriptor(
                id=command_id,
                plugin_id=plugin_id,
                section=section,
                examples=examples,
                description=description,
                feature=command_feature,
                **options,
            )
        )
    return tuple(descriptors)


def messaging_help_visible(
    event: Event,
    *,
    features: FeatureService,
    config: MessageConfig,
) -> bool:
    if not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
        return False
    actions = [*config.commands, *config.schedules]
    return any(
        action.enabled
        and event_is_feature_visible_in_help(features, event, action.feature)
        for action in actions
    )


def configured_message_commands(
    config: MessageConfig,
) -> tuple[CommandDescriptor, ...]:
    configured = tuple(
        CommandDescriptor(
            id=f"messaging.{action.id}",
            plugin_id="messaging",
            section="配置口令",
            examples=tuple(action.commands),
            description=action.name or "发送配置的文本或链接",
            feature=action.feature,
            show_in_poke=True,
        )
        for action in config.commands
        if action.enabled
    )
    subscription_commands = tuple(
        dict.fromkeys(
            (
                "推送管理",
                *config.push_unsubscribe.commands,
                *config.push_unsubscribe.restore_commands,
            )
        )
    )
    return (
        *configured,
        *_commands(
            "messaging",
            "推送管理",
            None,
            (
                (
                    "messaging.push_subscription",
                    subscription_commands,
                    "查看当前会话的推送订阅；群主和管理员可切换本群订阅",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *_commands(
            "messaging",
            "本群管理",
            None,
            (
                (
                    "messaging.push_time",
                    ("推送时间", "提醒时间"),
                    "管理本群定时推送和活动提醒时间",
                    {
                        "scope": "group",
                        "audience": "group_manager",
                        "show_in_poke": True,
                    },
                ),
            ),
        ),
    )


def configured_image_commands(config: Settings) -> tuple[CommandDescriptor, ...]:
    fixed = tuple(
        CommandDescriptor(
            id=f"sendpic.fixed.{command}",
            plugin_id="sendpic",
            section="固定图片",
            examples=(command,),
            description="发送固定图片",
            feature="image",
            show_in_poke=True,
        )
        for command in FIXED_IMAGE_COMMANDS
    )
    configured = tuple(
        CommandDescriptor(
            id=f"sendpic.{item.id}",
            plugin_id="sendpic",
            section="自定义图片",
            examples=(item.command, *sorted(item.aliases)),
            description="发送配置的图片；可在命令后附加编号",
            feature="image",
            show_in_poke=True,
        )
        for item in config.messaging.sendpic.configs
        if item.id in config.messaging.sendpic.enabled_ids
    )
    return (*fixed, *configured)


def ai_intent_commands(config: Settings) -> tuple[CommandDescriptor, ...]:
    if not config.ai.api_key.strip() or not config.ai.intent_actions_enabled:
        return ()
    return tuple(
        CommandDescriptor(
            id=f"ai_intent.{action_id}",
            plugin_id="ai_intent",
            section="关键词意图",
            examples=tuple(action.keywords),
            description="机器人识别到相应意图后自动回复",
            feature=action.feature,
        )
        for action_id, action in config.ai.intent_actions.items()
        if action.enabled and action.keywords
    )


def seer_query_commands() -> tuple[CommandDescriptor, ...]:
    return (
        *_commands(
            "seer_query",
            "玩家",
            "seer_player",
            (
                (
                    "seer.player.query",
                    ("米米号123456", "查询玩家信息123456"),
                    "查询玩家基础信息；随后按提示回复数字查看详情",
                    {"show_in_poke": True},
                ),
                (
                    "seer.player.default",
                    ("米米号", "收集", "巅峰", "群星牌", "阵容"),
                    "查询已绑定默认米米号的对应数据",
                    {},
                ),
                (
                    "seer.player.unbind",
                    ("解绑米米号",),
                    "解除当前 QQ 绑定的默认米米号",
                    {},
                ),
            ),
        ),
        *_commands(
            "seer_query",
            "战队",
            "seer_team",
            (
                (
                    "seer.team.query",
                    ("战队123456", "查询战队信息123456"),
                    "查询指定战队信息",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *_commands(
            "seer_query",
            "精灵、技能与魂印",
            "seer_pet",
            (
                (
                    "seer.pet.query",
                    ("精灵雷伊", "雷伊技能", "雷伊魂印"),
                    "查询精灵、技能和魂印信息",
                    {"show_in_poke": True},
                ),
                (
                    "seer.pet.image",
                    ("雷伊立绘", "雷伊皮肤", "皮肤雷伊"),
                    "查询精灵立绘或皮肤",
                    {},
                ),
            ),
        ),
        *_commands(
            "seer_query",
            "刻印与宝石",
            "seer_mintmark",
            (
                (
                    "seer.mintmark.query",
                    ("刻印V8", "精灵王刻印", "宝石绝命"),
                    "查询刻印、刻印系列或宝石",
                    {"show_in_poke": True},
                ),
                (
                    "seer.mintmark.rank",
                    ("刻印攻击榜", "六角双攻榜", "特攻双防刻印榜"),
                    "查询刻印数值榜",
                    {},
                ),
            ),
        ),
        *_commands(
            "seer_query",
            "套装、部件与称号",
            "seer_equipment",
            (
                (
                    "seer.equipment.query",
                    ("典狱套装", "部件漫游者", "称号神话"),
                    "查询套装、部件或称号",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *_commands(
            "seer_query",
            "属性与异常",
            "seer_type",
            (
                (
                    "seer.type.query",
                    ("属性圣灵", "火战斗属性", "异常中毒"),
                    "查询属性克制或异常状态",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *_commands(
            "seer_query",
            "巅峰相关",
            "seer_peak",
            (
                (
                    "seer.peak.query",
                    ("竞技池", "专家池", "巅峰投票"),
                    "查询巅峰池和投票信息",
                    {"show_in_poke": True},
                ),
                (
                    "seer.peak.rank",
                    ("竞技套装榜", "狂野称号榜", "竞技精灵月榜"),
                    "查询巅峰套装、称号和精灵榜",
                    {},
                ),
            ),
        ),
        *_commands(
            "seer_query",
            "群星牌",
            "seer_autocard",
            (
                (
                    "seer.autocard.query",
                    ("群星牌布布种子", "布布种子群星牌", "群星牌卡98"),
                    "查询群星牌资料",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *_commands(
            "seer_query",
            "数据工具",
            "seer_data",
            (
                (
                    "seer.data.query",
                    ("下周预告", "新增成就", "数据版本", "赛季倒计时"),
                    "查询赛尔数据和赛季信息",
                    {"show_in_poke": True},
                ),
            ),
        ),
    )


def rank_commands() -> tuple[CommandDescriptor, ...]:
    regular_rows = (
        (
            "rank.help",
            "榜单查询",
            ("榜单", "排行榜", "榜单帮助"),
            "查看可用榜单和查询格式",
            {"show_in_poke": True},
        ),
        (
            "rank.global_collection",
            "全服图鉴榜",
            ("图鉴榜", "成就榜", "精灵榜", "皮肤榜", "套装榜", "部件榜", "座驾榜", "刻印榜", "群星牌榜"),
            "查看全服图鉴类榜单；可追加页码、名次、米米号或分数",
            {"show_in_poke": True},
        ),
        (
            "rank.global_peak",
            "全服巅峰段位榜",
            ("竞技段位榜", "狂野段位榜", "专家段位榜"),
            "查看全服巅峰段位榜；可追加名次或分数",
            {},
        ),
        (
            "rank.mintmark",
            "刻印数值榜",
            ("刻印攻击榜", "六角双攻榜", "特攻双防刻印榜"),
            "按角数和属性组合查看刻印数值榜；双刀=双攻，盾=双防",
            {},
        ),
        (
            "rank.sample_collection",
            "样本图鉴榜",
            ("样本图鉴榜", "样本成就榜", "样本精灵数量榜"),
            "查看机器人样本中的图鉴和收集排行",
            {},
        ),
        (
            "rank.sample_peak",
            "巅峰样本榜",
            ("样本竞技段位榜", "竞技胜率榜", "专家场次榜"),
            "查看机器人样本中的巅峰段位、胜率和场次排行",
            {},
        ),
    )
    regular = tuple(
        CommandDescriptor(
            id=command_id,
            plugin_id="rank_help",
            section=section,
            examples=examples,
            description=description,
            feature="seer_rank",
            show_in_poke=options.get("show_in_poke", False),
        )
        for command_id, section, examples, description, options in regular_rows
    )
    return (
        *regular,
        *_commands(
            "rank_help",
            "本群管理",
            "seer_rank",
            (
                (
                    "rank.display_limit",
                    ("/榜单显示 20",),
                    "设置本群榜单默认显示名次",
                    {
                        "scope": "group",
                        "audience": "group_manager",
                        "show_in_poke": True,
                    },
                ),
            ),
        ),
        *_commands(
            "rank_help",
            "超级管理员",
            "seer_rank",
            (
                ("rank.sample_status", ("/样本情况",), "查看样本缓存情况", {"audience": "superuser"}),
                ("rank.sample_refresh", ("/刷新样本",), "刷新样本缓存", {"audience": "superuser"}),
                ("rank.page_status", ("/榜单情况", "/榜单情况 图鉴榜"), "查看全服榜单缓存", {"audience": "superuser"}),
                ("rank.page_refresh", ("/刷新榜单", "/刷新榜单 图鉴榜"), "刷新全服榜单缓存", {"audience": "superuser"}),
                ("rank.page_batch", ("/缓存榜单 刻印榜 1-100",), "缓存指定全服榜单区间", {"audience": "superuser"}),
            ),
        ),
    )


def server_status_commands() -> tuple[CommandDescriptor, ...]:
    return (
        *_commands(
            "server_status",
            "查询",
            "server_status_query",
            (("server_status.query", ("开服了吗",), "查询当前维护和开服状态", {"show_in_poke": True}),),
        ),
        *_commands(
            "server_status",
            "超级管理员",
            None,
            (
                ("server_status.admin_query", ("/开服查询",), "查询开服状态，并在无头未登录时尝试重连", {"feature": "server_status_query", "audience": "superuser"}),
                ("server_status.restart", ("/机器人重启", "/重启机器人"), "重启机器人进程", {"audience": "superuser"}),
                ("server_status.image_update", ("/更新镜像", "/更新Docker"), "检查镜像并重启机器人", {"audience": "superuser"}),
                ("server_status.image_check", ("/检查更新镜像", "/检查镜像更新"), "只检查远端镜像，不拉取或重启机器人", {"audience": "superuser"}),
            ),
        ),
    )


def data_sync_commands() -> tuple[CommandDescriptor, ...]:
    return _commands(
        "db_sync",
        "超级管理员",
        None,
        (
            ("db_sync.update", ("/更新数据", "/数据更新"), "构建远程数据并同步到机器人", {"audience": "superuser"}),
            ("db_sync.force_update", ("/强制更新数据", "/强制数据更新"), "忽略本地指纹，强制同步数据", {"audience": "superuser"}),
        ),
    )


def bilibili_commands() -> tuple[CommandDescriptor, ...]:
    return (
        *_commands("bilibili", "查询", "bili_query", (("bilibili.dynamic", ("动态",), "查看订阅账号的最新动态", {"show_in_poke": True}), ("bilibili.accounts", ("B站账号",), "查看当前会话订阅的账号", {}))),
        *_commands("bilibili", "本群管理", "bili_push", (("bilibili.push_mode", ("B站推送模式 <账号> <内容|链接|默认>",), "调整当前会话指定账号的推送模式", {"scope": "group", "audience": "group_manager"}),)),
        *_commands("bilibili", "超级管理员", "bili_push", (("bilibili.private_push_mode", ("B站推送模式 <账号> <内容|链接|默认>",), "调整私聊订阅账号的推送模式", {"scope": "private", "audience": "superuser"}), ("bilibili.refresh", ("/动态更新", "/动态刷新"), "立即刷新订阅动态", {"audience": "superuser"}))),
    )


def activity_commands() -> tuple[CommandDescriptor, ...]:
    return (
        *_commands("activity", "查询", "seer_activity_query", (("activity.ending", ("快结束活动",), "查询即将结束的活动", {"show_in_poke": True}),)),
        *_commands("activity", "超级管理员", "seer_activity_query", (("activity.current", ("/当前活动",), "查询完整活动列表", {"audience": "superuser"}),)),
    )


def team_resource_commands(*, enabled: bool) -> tuple[CommandDescriptor, ...]:
    if not enabled:
        return ()
    return (
        *_commands("team_resource", "查询", "team_resource_subscription", (("team_resource.query", ("战队",), "查看本群订阅战队的信息和资源", {"scope": "group", "show_in_poke": True}),)),
        *_commands("team_resource", "本群管理", "team_resource_subscription", (("team_resource.subscribe", ("订阅战队123456",), "订阅战队资源提醒；可在末尾 @ 提醒对象", {"scope": "group", "audience": "group_manager", "show_in_poke": True}), ("team_resource.unsubscribe", ("取消订阅战队123456",), "取消本群指定战队订阅", {"scope": "group", "audience": "group_manager", "show_in_poke": True}), ("team_resource.list", ("战队订阅",), "查看和管理本群战队订阅", {"scope": "group", "audience": "group_manager", "show_in_poke": True}))),
    )


def ai_chat_commands(*, enabled: bool) -> tuple[CommandDescriptor, ...]:
    if not enabled:
        return ()
    return (
        *_commands("ai_chat", "群聊", "ai_chat", (("ai_chat.group", ("@机器人 <问题>",), "向 AI 聊天提问", {"scope": "group"}),)),
        *_commands("ai_chat", "私聊", "ai_chat", (("ai_chat.private", ("<问题>",), "直接向 AI 聊天提问", {"scope": "private"}),)),
    )


def about_commands() -> tuple[CommandDescriptor, ...]:
    return _commands("about", "查看", "about", (("about", ("关于",), "查看项目、版本和主要能力", {}),))


def help_commands() -> tuple[CommandDescriptor, ...]:
    return _commands("help", "查看", "help", (("help", ("帮助",), "查看当前会话可用功能", {"show_in_poke": True}),))


def meeting_commands(config: Settings) -> tuple[CommandDescriptor, ...]:
    return _commands("meeting", "查询", "meeting", (("meeting", tuple(config.messaging.meeting.commands), "获取配置的腾讯会议信息", {"show_in_poke": True}),))
