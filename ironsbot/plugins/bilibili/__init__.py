from nonebot.plugin import PluginMetadata

from ironsbot.config.models.app import AppConfig

__plugin_meta__ = PluginMetadata(
    name="B站动态",
    description="查询、刷新和自动推送配置账号的 Bilibili 动态",
    usage=(
        "【B站动态】\n"
        "动态：拉取当前会话订阅账号的最新动态列表，继续发送数字查看详情。\n"
        "/动态更新、/动态刷新：超级管理员手动刷新并推送新动态。\n"
        "B站账号：查看当前会话订阅的 B 站账号。\n"
        "B站推送模式 <账号昵称> <内容|链接|默认>："
        "群主/管理员修改当前群某账号推送模式。\n"
        "自动推送支持按群/用户/UID 配置全文或只发链接；抽奖中奖结果不推送，"
        "但仍可在历史动态里查询。TD 菜单支持按账号退订。"
    ),
    config=AppConfig,
)
