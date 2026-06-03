from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    headless_seer_login_failure_notice_enabled: bool = True
    headless_seer_login_failure_notice_message: str = (
        "无头米米号登录未成功。\n"
        "米米号：{user_id}\n"
        "状态：{reason}\n"
        "依赖米米号登录的功能可能不可用；请检查账号、MD5密码、网络或赛尔号服务器状态。"
    )


plugin_config = get_plugin_config(Config)
