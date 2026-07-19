# SPDX-License-Identifier: MIT
from collections.abc import Iterable
from pathlib import Path
from typing import Final, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.core.commands import (
    NormalizedIntList,
    NormalizedStringFrozenSet,
    NormalizedStringList,
    NormalizedStringSet,
)

FIRE_MANUAL_URL: Final = "https://seerinfo.yuyuqaq.cn/firedict"
FIRE_MANUAL_LINK_MESSAGE: Final = f"火火手册链接：{FIRE_MANUAL_URL}"
FIXED_IMAGE_COMMANDS: Final = {
    "学习力": "学习力表格.png",
    "学习力表": "学习力表格.png",
    "学习力表格": "学习力表格.png",
    "巅峰姬": "巅峰姬.png",
    "必先": "必先.png",
    "技能石": "技能石.png",
    "周年庆伪随机表": "周年庆伪随机表.png",
    "伪随机表": "周年庆伪随机表.png",
}
DEFAULT_JOIN_TEAM_INTENT = (
    "Judge whether the QQ group message means the sender wants to join, apply for, "
    "or find a Seer team/guild. Answer yes only when the sender is asking to join "
    "a team, asking whether they can enter the team, or asking for the team info "
    "for joining. Answer no when the message only queries team data, discusses "
    "team resources, asks someone to buy resources, or casually mentions teams."
)
DEFAULT_JOIN_TEAM_MESSAGE = (
    "\u70b9\u51fb\u94fe\u63a5\u52a0\u51655\u7ea7\u6218\u961f\u5ba1\u6838\u7fa4\uff1a"
    "http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&"
    "k=zZcvC2GF9tB027Kyq04Fl9_7bF-_v8FB&"
    "authKey=ZTZrJewKretFEap44nIcKtMkF8zpI1nhcR6ok2%2FXM6LNMO%2BE8ZVdYWLvWvwEwVjM&"
    "noverify=0&group_code=719544559"
)
DEFAULT_CLASSIFIER_PROMPT = (
    "You are a strict intent classifier for a QQ bot.\n"
    "Only output one word: yes or no.\n"
    "Intent definition: {intent}\n"
    "Message: {message}\n"
    "Does the message match the intent?"
)


class MessageTarget(NamedTuple):
    target_type: Literal["private", "group"]
    target_id: int
    at_user_ids: tuple[int, ...] = ()


class TargetSendSummary(NamedTuple):
    succeeded: list[MessageTarget]
    failed: list[MessageTarget]


class AiIntentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    enabled: bool = True
    feature: str = "ai_intent"
    keywords: NormalizedStringList = Field(default_factory=list)
    intent: str = DEFAULT_JOIN_TEAM_INTENT
    classifier_prompt: str = DEFAULT_CLASSIFIER_PROMPT
    action: Literal["message", "team_recommend", "team_resource", "ai_reply"] = (
        "team_recommend"
    )
    message: str = ""
    reply_prompt: str = ""
    team_ids: NormalizedIntList = Field(default_factory=list)
    include_team_resource_notice: bool = False
    exclude_commands: NormalizedStringList = Field(default_factory=list)

    @field_validator("feature")
    @classmethod
    def normalize_feature(cls, value: str) -> str:
        return value.strip() or "ai_intent"


class PicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    backend: Literal["cnb", "local"]
    command: str
    aliases: NormalizedStringSet = Field(default_factory=set)
    image_dir: str
    image_filename_template: str
    message_template: str = "{image}"

class SendpicBehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cnb_token: str | None = Field(default=None, exclude=True, repr=False)
    cnb_repo: str | None = None
    local_root: Path = Path("sendpic")
    configs: list[PicConfig] = Field(default_factory=list)
    enabled_ids: NormalizedStringFrozenSet = Field(default_factory=frozenset)


def private_targets(user_ids: Iterable[int]) -> list[MessageTarget]:
    return [MessageTarget("private", user_id) for user_id in dict.fromkeys(user_ids)]


def group_targets(
    group_ids: Iterable[int],
    *,
    at_user_ids: Iterable[int] = (),
) -> list[MessageTarget]:
    at_users = tuple(dict.fromkeys(at_user_ids))
    return [
        MessageTarget("group", group_id, at_users)
        for group_id in dict.fromkeys(group_ids)
    ]


def broadcast_targets(
    *,
    private_user_ids: Iterable[int] = (),
    group_ids: Iterable[int] = (),
    group_at_user_ids: Iterable[int] = (),
) -> list[MessageTarget]:
    return [
        *group_targets(group_ids, at_user_ids=group_at_user_ids),
        *private_targets(private_user_ids),
    ]


def append_fire_manual_ad_text(message: str) -> str:
    text = message.rstrip()
    if FIRE_MANUAL_URL in text:
        return text
    if not text:
        return FIRE_MANUAL_LINK_MESSAGE
    return f"{text}\n\n{FIRE_MANUAL_LINK_MESSAGE}"
