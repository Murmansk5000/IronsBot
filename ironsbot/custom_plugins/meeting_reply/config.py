from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    meeting_number: str = ""
    meeting_template: str = (
        "腾讯会议\n"
        "腾讯会议号：{meeting_number}\n"
        "点击链接直接加入：{meeting_url}"
    )


plugin_config = get_plugin_config(Config)
