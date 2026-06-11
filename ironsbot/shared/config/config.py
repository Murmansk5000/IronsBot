# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from typing_extensions import Self

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.shared.config.parsing import (
    int_list,
    json_array,
    json_object,
    nested_json_config,
    string_list,
    unique_items,
)
from ironsbot.shared.config.time import (
    normalize_daily_time,
    normalized_daily_time_csv,
    normalized_daily_times,
)

KEYWORDS_REQUIRED_ERROR = "enabled AI action must configure keywords"
MESSAGE_REQUIRED_ERROR = "message AI action must configure message"
AI_REPLY_PROMPT_REQUIRED_ERROR = "ai_reply AI action must configure reply_prompt"
ENABLED_COMMANDS_REQUIRED_ERROR = "已启用的指令消息动作必须配置 commands"
INVALID_INTERVAL_TIME_ERROR = (
    "APP_CONFIG.bilibili.polling.windows time must use HH:MM"
)
INVALID_RESTART_TIME_ERROR = (
    "APP_CONFIG.runtime.restart.times must contain daily HH:MM times, "
    'for example "04:30,16:10" or ["04:30","16:10"]'
)
INVALID_RECONNECT_TIME_ERROR = (
    "APP_CONFIG.runtime.headless_notice.reconnect_check_times must contain "
    "daily HH:MM times, "
    'for example "00:01,00:02" or ["00:01","00:02"]'
)

DEFAULT_AI_PROMPT = (
    "你是 IronsBot，一个接入 QQ 群的赛尔号信息查询机器人。"
    "回答应简洁、友好、诚实；无法确认时直接说明不确定，不要编造。"
)
DEFAULT_AI_MENTION_GUARD_MESSAGE = (
    "这个群没有开启 AI 聊天，@或回复我不会触发功能。"
    "直接发送指令就可以查询；不会用可以发送“帮助”。"
)
DEFAULT_AI_MENTION_GUARD_REPLY_WINDOW_SECONDS = 60.0
DEFAULT_AI_MENTION_GUARD_REPLY_MAX_PER_WINDOW = 10
DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS = 600.0
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
DEFAULT_KEYWORD_INFO_PROMPT = (
    "You are IronsBot, a concise QQ group assistant.\n"
    "Matched action: {action_id}\n"
    "Keywords: {keywords}\n"
    "User message: {message}\n"
    "Reply briefly and directly. If real-time bot data is needed, say which bot "
    "command or feature should be used instead of inventing data."
)

BiliPushMode = Literal["full", "link"]
DEFAULT_BILI_SUPPRESS_PATTERNS = [
    "恭喜.*获得",
    "记得及时查看私信通知",
    "中奖",
    "抽奖结果",
]
DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS = 300.0

PLAYER_SECTION_KEYS: tuple[str, ...] = (
    "basic",
    "appearance",
    "social",
    "collection",
    "rank",
    "local_rank",
    "achievement",
    "peak",
    "titles",
    "pets",
    "stages",
    "battle",
    "raw",
)
TEAM_SECTION_KEYS: tuple[str, ...] = (
    "basic",
    "resource",
    "facilities",
    "status",
    "logo",
    "text",
)
DEFAULT_BROADCAST_MESSAGE = "赛尔号已经开服了。"
DEFAULT_SENDPIC_MESSAGE_TEMPLATE = "{image}"
SendpicBackendType: TypeAlias = Literal["cnb", "local"]
IRONS_DATA_RELEASE = "https://github.com/Murmansk5000/seerapi/releases/download"

KNOWN_FEATURES = frozenset(
    {
        "seer",
        "image",
        "rank",
        "meeting",
        "text",
        "text_push",
        "activity_link",
        "activity_link_push",
        "seerinfo",
        "bili_query",
        "bili_push",
        "activity_query",
        "activity_push",
        "server_status_query",
        "server_status_push",
        "team",
        "ai_chat",
        "ai_intent",
        "admin_notice",
    }
)
FEATURE_ALIASES: dict[str, frozenset[str]] = {
    "all": KNOWN_FEATURES - {"admin_notice"},
    "custom": frozenset(
        {
            "seer",
            "image",
            "rank",
            "bili_query",
            "activity_query",
            "server_status_query",
        }
    ),
    "bili": frozenset({"bili_query", "bili_push"}),
    "activity": frozenset({"activity_query", "activity_push"}),
    "server_status": frozenset({"server_status_query", "server_status_push"}),
    "text": frozenset({"text", "activity_link", "seerinfo"}),
    "text_push": frozenset({"text_push", "activity_link_push"}),
    "message": frozenset(
        {
            "text",
            "text_push",
            "activity_link",
            "activity_link_push",
            "seerinfo",
        }
    ),
}


def _normalize_mode(value: object) -> object:
    if value is None or value == "":
        return value
    mode = str(value).strip().lower()
    if mode not in {"full", "link"}:
        msg = "APP_CONFIG.bilibili push mode must be full or link"
        raise ValueError(msg)
    return mode


def _coerce_sections(value: object) -> object:
    if value is None or value == "":
        return ["all"]

    return string_list(value)


def _normalize_sections(value: Iterable[str], allowed: tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    unknown: list[str] = []

    for raw in value:
        section = str(raw).strip().lower()
        if not section:
            continue
        if section in {"*", "all"}:
            return list(allowed)
        if section not in allowed:
            unknown.append(section)
            continue
        if section not in normalized:
            normalized.append(section)

    if unknown:
        raise ValueError(f"unknown sections: {', '.join(unknown)}")  # noqa: TRY003

    return normalized


def _validate_sqlite_path(value: Path) -> Path:
    if value.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("cache path must use .sqlite, .sqlite3, or .db")  # noqa: TRY003

    return value


def _default_sendpic_local_root() -> Path:
    return Path("sendpic")


def _coerce_int_mapping(value: object) -> dict[str, int]:
    parsed = json_object(value, name="feature policy aliases")
    result: dict[str, int] = {}
    for raw_key, raw_value in parsed.items():
        key = str(raw_key).strip()
        if key:
            result[key] = int(raw_value)
    return result


def _coerce_policy_mapping(value: object) -> dict[str, list[str]]:
    parsed = json_object(value, name="feature policy")
    result: dict[str, list[str]] = {}
    for raw_key, raw_features in parsed.items():
        key = str(raw_key).strip()
        if key:
            result[key] = string_list(raw_features)
    return result


class AiActionBase(BaseModel):
    id: str = ""
    enabled: bool = True
    template: str = ""
    feature: str = "ai_intent"
    keywords: list[str] = Field(default_factory=list)
    intent: str = DEFAULT_JOIN_TEAM_INTENT
    classifier_prompt: str = DEFAULT_CLASSIFIER_PROMPT
    action: Literal["message", "team_shortcut", "ai_reply"] = "team_shortcut"
    message: str = ""
    reply_prompt: str = ""
    team_ids: list[int] = Field(default_factory=list)
    include_team_resource_notice: bool = False
    exclude_commands: list[str] = Field(default_factory=list)

    @field_validator("keywords", "exclude_commands", mode="before")
    @classmethod
    def normalize_string_list(cls, value: object) -> object:
        return string_list(value)

    @field_validator("team_ids", mode="before")
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        return int_list(value)

    @field_validator("feature")
    @classmethod
    def normalize_feature(cls, value: str) -> str:
        feature = value.strip()
        return feature or "ai_intent"


class AiActionTemplate(AiActionBase):
    pass


class AiIntentAction(AiActionBase):
    @model_validator(mode="after")
    def validate_enabled_action(self) -> Self:
        if not self.enabled:
            return self

        if not self.keywords and not self.template:
            raise ValueError(KEYWORDS_REQUIRED_ERROR)

        if self.action == "message" and not self.message.strip():
            raise ValueError(MESSAGE_REQUIRED_ERROR)

        if self.action == "ai_reply" and not self.reply_prompt.strip():
            raise ValueError(AI_REPLY_PROMPT_REQUIRED_ERROR)

        return self


def default_ai_templates() -> dict[str, AiActionTemplate]:
    return {
        "join_team": AiActionTemplate(
            id="join_team",
            keywords=["战队"],
            action="message",
            intent=DEFAULT_JOIN_TEAM_INTENT,
            message=DEFAULT_JOIN_TEAM_MESSAGE,
            include_team_resource_notice=False,
        ),
        "keyword_info": AiActionTemplate(
            id="keyword_info",
            action="ai_reply",
            intent=(
                "The message is asking for information or explanation about "
                "the configured keywords."
            ),
            reply_prompt=DEFAULT_KEYWORD_INFO_PROMPT,
        ),
    }


def default_ai_actions() -> list[AiIntentAction]:
    return [AiIntentAction(template="join_team")]


class AiConfig(BaseModel):
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    prompt: str = DEFAULT_AI_PROMPT
    reset_commands: list[str] = Field(
        default_factory=lambda: ["清空聊天", "重置聊天", "清空上下文"]
    )
    history_turns: int = Field(default=6, ge=0, le=20)
    memory: bool = True
    memory_path: Path = Path("data/ai_chat/memory.sqlite")
    memory_turns: int = Field(default=8, ge=0, le=50)
    memory_max_chars: int = Field(default=1200, gt=0)
    timeout: float = Field(default=45.0, gt=0)
    max_tokens: int = Field(default=800, gt=0)
    temperature: float = Field(default=0.7, ge=0, le=2)
    thinking: bool = False
    waiting_notice: bool = False
    max_reply_chars: int = Field(default=1500, gt=0)
    mention_guard_reply_window_seconds: float = Field(
        default=DEFAULT_AI_MENTION_GUARD_REPLY_WINDOW_SECONDS,
        gt=0,
    )
    mention_guard_reply_max_per_window: int = Field(
        default=DEFAULT_AI_MENTION_GUARD_REPLY_MAX_PER_WINDOW,
        ge=1,
    )
    mention_guard_message: str = DEFAULT_AI_MENTION_GUARD_MESSAGE
    admin_notice_cooldown_seconds: float = Field(
        default=DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS,
        ge=0,
    )
    intent_actions_enabled: bool = True
    action_templates: dict[str, AiActionTemplate] = Field(
        default_factory=default_ai_templates
    )
    intent_actions: list[AiIntentAction] = Field(default_factory=default_ai_actions)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("reset_commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)

    @field_validator("action_templates", mode="before")
    @classmethod
    def normalize_templates(cls, value: object) -> object:
        if value is None or value == "":
            return default_ai_templates()

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return default_ai_templates()
            return json_object(text, name="APP_CONFIG.ai.action_templates")

        return value

    @field_validator("intent_actions", mode="before")
    @classmethod
    def normalize_actions(cls, value: object) -> object:
        if value is None or value == "":
            return default_ai_actions()

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return default_ai_actions()
            return json_array(text, name="APP_CONFIG.ai.intent_actions")

        return value

    @model_validator(mode="after")
    def merge_default_templates(self) -> Self:
        templates = default_ai_templates()
        for template_id, template in self.action_templates.items():
            base = templates.get(template_id)
            if base is None:
                templates[template_id] = template
                continue

            merged = base.model_dump()
            merged.update(template.model_dump(exclude_unset=True))
            templates[template_id] = AiActionTemplate.model_validate(merged)

        self.action_templates = templates
        return self


class BiliIntervalWindow(BaseModel):
    start: str
    end: str
    minutes: int = Field(gt=0)

    @field_validator("start", "end")
    @classmethod
    def validate_hhmm(cls, value: str) -> str:
        return normalize_daily_time(
            value,
            error_message=INVALID_INTERVAL_TIME_ERROR,
        )


class BiliStorageConfig(BaseModel):
    data_dir: Path = Path("data/bilibili_monitor")
    history_max_items: int = Field(default=1000, ge=1)


class BiliPollingConfig(BaseModel):
    default_minutes: int = Field(default=30, gt=0)
    windows: list[BiliIntervalWindow] = Field(
        default_factory=lambda: [
            BiliIntervalWindow(start="07:00", end="23:00", minutes=5)
        ]
    )


class BiliPushTargetConfig(BaseModel):
    uids: list[int] = Field(default_factory=list)
    mode: BiliPushMode | None = None
    uid_modes: dict[int, BiliPushMode] = Field(default_factory=dict)

    @field_validator("uids", mode="before")
    @classmethod
    def normalize_uids(cls, value: object) -> object:
        return int_list(value)

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        return _normalize_mode(value)

    @field_validator("uid_modes", mode="before")
    @classmethod
    def normalize_uid_modes(cls, value: object) -> object:
        parsed = json_object(value, name="APP_CONFIG.bilibili.push uid_modes")
        result: dict[int, BiliPushMode] = {}
        for raw_uid, raw_mode in parsed.items():
            uid = int(raw_uid)
            mode = _normalize_mode(raw_mode)
            if mode in {"full", "link"}:
                result[uid] = mode
        return result


class BiliPushConfig(BaseModel):
    default_mode: BiliPushMode = "full"
    groups: dict[str, BiliPushTargetConfig] = Field(default_factory=dict)
    users: dict[str, BiliPushTargetConfig] = Field(default_factory=dict)

    @field_validator("default_mode", mode="before")
    @classmethod
    def normalize_default_mode(cls, value: object) -> object:
        return _normalize_mode(value)

    @field_validator("groups", "users", mode="before")
    @classmethod
    def normalize_targets(cls, value: object) -> object:
        parsed = json_object(value, name="APP_CONFIG.bilibili.push targets")
        result: dict[str, object] = {}
        for raw_ref, raw_config in parsed.items():
            ref = str(raw_ref).strip()
            if not ref:
                continue

            if raw_config is None or raw_config == "":
                result[ref] = {}
            elif (
                isinstance(raw_config, Iterable)
                and not isinstance(raw_config, str | bytes | Mapping)
            ):
                result[ref] = {"uids": list(raw_config)}
            else:
                result[ref] = raw_config
        return result


class BiliFilterConfig(BaseModel):
    suppress_push_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_BILI_SUPPRESS_PATTERNS)
    )

    @field_validator("suppress_push_patterns", mode="before")
    @classmethod
    def normalize_patterns(cls, value: object) -> object:
        return string_list(value)


class BiliConfig(BaseModel):
    uids: list[int] = Field(default_factory=lambda: [1310714247])
    storage: BiliStorageConfig = Field(default_factory=BiliStorageConfig)
    polling: BiliPollingConfig = Field(default_factory=BiliPollingConfig)
    push: BiliPushConfig = Field(default_factory=BiliPushConfig)
    filters: BiliFilterConfig = Field(default_factory=BiliFilterConfig)
    login_notice_cooldown_seconds: float = Field(
        default=DEFAULT_BILI_LOGIN_NOTICE_COOLDOWN_SECONDS,
        ge=0,
    )

    @field_validator("uids", mode="before")
    @classmethod
    def normalize_uids(cls, value: object) -> object:
        return int_list(value)


class BaseMessageAction(BaseModel):
    id: str = ""
    enabled: bool = True
    feature: str = "text"
    message: str

    @field_validator("feature")
    @classmethod
    def normalize_feature(cls, value: str) -> str:
        feature = value.strip()
        return feature or "text"

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("消息内容不能为空")
        return message


class CommandMessageAction(BaseMessageAction):
    commands: list[str] = Field(default_factory=list)

    @field_validator("commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)

    @model_validator(mode="after")
    def validate_enabled_command_action(self) -> Self:
        if self.enabled and not self.commands:
            raise ValueError(ENABLED_COMMANDS_REQUIRED_ERROR)
        return self


class ScheduledMessageAction(BaseMessageAction):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    day_of_week: str | None = None


class PrivateCommandMessageAction(CommandMessageAction):
    pass


class PrivateScheduledMessageAction(ScheduledMessageAction):
    feature: str = "text_push"


class GroupCommandMessageAction(CommandMessageAction):
    at_user_ids: list[int] = Field(default_factory=list)

    @field_validator("at_user_ids", mode="before")
    @classmethod
    def normalize_at_user_ids(cls, value: object) -> object:
        return int_list(value)


class GroupScheduledMessageAction(ScheduledMessageAction):
    feature: str = "text_push"
    at_user_ids: list[int] = Field(default_factory=list)

    @field_validator("at_user_ids", mode="before")
    @classmethod
    def normalize_at_user_ids(cls, value: object) -> object:
        return int_list(value)


class ReplyLineConfig(BaseModel):
    default_lines: int = Field(default=-1, ge=-1)
    min_lines: int = Field(default=5, ge=1)
    max_lines: int = Field(default=80, ge=1)
    limit_path: Path = Path("data/message_actions/reply_limits.sqlite")

    @model_validator(mode="after")
    def validate_line_range(self) -> Self:
        if self.min_lines > self.max_lines:
            msg = "reply.min_lines must be less than or equal to reply.max_lines"
            raise ValueError(msg)
        return self


class MessageActionsConfig(BaseModel):
    reply: ReplyLineConfig = Field(default_factory=ReplyLineConfig)
    private_commands: list[PrivateCommandMessageAction] = Field(default_factory=list)
    private_schedules: list[PrivateScheduledMessageAction] = Field(
        default_factory=list
    )
    group_commands: list[GroupCommandMessageAction] = Field(default_factory=list)
    group_schedules: list[GroupScheduledMessageAction] = Field(default_factory=list)


class PlayerQueryConfig(BaseModel):
    rate_limit_seconds: int = Field(default=60, ge=0)
    failure_rate_limit_seconds: int = Field(default=10, ge=0)
    timeout_seconds: float = Field(default=30, gt=0)
    detail_timeout_seconds: float = Field(default=90, gt=0)
    sections: list[str] = Field(default_factory=lambda: list(PLAYER_SECTION_KEYS))

    @field_validator("sections", mode="before")
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("sections")
    @classmethod
    def normalize_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(value, PLAYER_SECTION_KEYS)


class TeamQueryConfig(BaseModel):
    rate_limit_seconds: int = Field(default=60, ge=0)
    failure_rate_limit_seconds: int = Field(default=10, ge=0)
    timeout_seconds: float = Field(default=20, gt=0)
    sections: list[str] = Field(default_factory=lambda: list(TEAM_SECTION_KEYS))

    @field_validator("sections", mode="before")
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("sections")
    @classmethod
    def normalize_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(value, TEAM_SECTION_KEYS)


class RankQueryConfig(BaseModel):
    limit: int = Field(default=10000, ge=0)
    online_limit: int = Field(default=2000, ge=0)
    page_size: int = Field(default=100, ge=1)
    page_cache: bool = True
    page_cache_ttl_seconds: int = Field(default=3600, ge=0)
    allow_stale_cache: bool = True
    refresh_stale_cache: bool = True
    page_cache_path: Path = Path(
        "data/custom_get_seer_info/rank_page_cache.sqlite"
    )
    peak_subkey: int | None = Field(default=None, ge=0)

    @field_validator("peak_subkey", mode="before")
    @classmethod
    def empty_peak_subkey_as_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("page_cache_path")
    @classmethod
    def validate_sqlite_cache_path(cls, value: Path) -> Path:
        return _validate_sqlite_path(value)


class LocalRankConfig(BaseModel):
    enabled: bool = True
    max_players: int = Field(default=5000, ge=1)
    batch_limit: int = Field(default=100, ge=1)
    auto_refresh: bool = True
    refresh_hour: int = Field(default=3, ge=0, le=23)
    refresh_minute: int = Field(default=30, ge=0, le=59)
    refresh_limit: int = Field(default=300, ge=1)
    refresh_max_age_hours: int = Field(default=24, ge=0)
    refresh_interval_seconds: float = Field(default=0.5, ge=0)
    path: Path = Path("data/custom_get_seer_info/player_query_cache.sqlite")

    @field_validator("path")
    @classmethod
    def validate_sqlite_cache_path(cls, value: Path) -> Path:
        return _validate_sqlite_path(value)


class SeerQueryConfig(BaseModel):
    player: PlayerQueryConfig = Field(default_factory=PlayerQueryConfig)
    team: TeamQueryConfig = Field(default_factory=TeamQueryConfig)
    rank: RankQueryConfig = Field(default_factory=RankQueryConfig)
    local_rank: LocalRankConfig = Field(default_factory=LocalRankConfig)


class TeamConfig(BaseModel):
    commands: list[str] = Field(default_factory=lambda: ["战队"])
    resource_threshold: int = Field(default=1000, ge=0)
    query_timeout_seconds: int = Field(default=20, gt=0)
    resource_message: str = "出来买资源，别逼我求你😡"

    @field_validator("commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)


class MeetingConfig(BaseModel):
    number: str = ""
    template: str = (
        "腾讯会议\n"
        "腾讯会议号：{meeting_number}\n"
        "点击链接直接加入：{meeting_url}"
    )
    commands: list[str] = Field(default_factory=lambda: ["开播", "会议"])

    @field_validator("commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)


class StartupConfig(BaseModel):
    enabled: bool = True
    message: str = "机器人已开启。"
    delay: float = Field(default=0.0, ge=0)


class ServerStatusConfig(BaseModel):
    broadcast: bool = False
    broadcast_message: str = DEFAULT_BROADCAST_MESSAGE
    broadcast_cooldown_minutes: int = Field(default=1440, ge=0)

    @field_validator("broadcast_message")
    @classmethod
    def normalize_broadcast_message(cls, value: str) -> str:
        message = value.strip()
        return message or DEFAULT_BROADCAST_MESSAGE


class RestartConfig(BaseModel):
    enabled: bool = False
    times: str = "04:30"
    grace_seconds: float = Field(default=10.0, ge=0)
    signal_parent: bool = True

    @field_validator("times", mode="before")
    @classmethod
    def normalize_restart_times(cls, value: object) -> str:
        return normalized_daily_time_csv(
            value,
            error_message=INVALID_RESTART_TIME_ERROR,
        )

    @model_validator(mode="after")
    def validate_restart_times(self) -> Self:
        if self.enabled and not self.parsed_restart_times:
            raise ValueError(INVALID_RESTART_TIME_ERROR)
        return self

    @property
    def parsed_restart_times(self) -> list[str]:
        return normalized_daily_times(
            self.times,
            error_message=INVALID_RESTART_TIME_ERROR,
        )


class HeadlessNoticeConfig(BaseModel):
    login_notice: bool = True
    login_notice_message: str = (
        "无头米米号登录未成功。\n"
        "米米号：{user_id}\n"
        "状态：{reason}\n"
        "依赖米米号登录的功能可能不可用；请检查账号、MD5密码、网络或赛尔号服务器状态。"
    )
    state_notice: bool = True
    state_offline_message: str = (
        "无头米米号已掉线。\n"
        "米米号：{user_id}\n"
        "状态：{reason}\n"
        "来源：{source}"
    )
    state_online_message: str = (
        "无头米米号已恢复登录。\n"
        "米米号：{user_id}\n"
        "来源：{source}"
    )
    reconnect_check_times: str = "00:01,00:02"

    @field_validator("reconnect_check_times", mode="before")
    @classmethod
    def normalize_reconnect_times(cls, value: object) -> str:
        return normalized_daily_time_csv(
            value,
            error_message=INVALID_RECONNECT_TIME_ERROR,
        )

    @property
    def parsed_reconnect_check_times(self) -> list[str]:
        return normalized_daily_times(
            self.reconnect_check_times,
            error_message=INVALID_RECONNECT_TIME_ERROR,
        )


class HelpConfig(BaseModel):
    ignored_plugins: list[str] = Field(default_factory=list)

    @field_validator("ignored_plugins", mode="before")
    @classmethod
    def normalize_ignored_plugins(cls, value: object) -> object:
        return string_list(value)


class SuperuserPriorityConfig(BaseModel):
    enabled: bool = True
    wait_timeout_seconds: float = Field(default=300.0, ge=0)


class RenderConfig(BaseModel):
    cache_dir: Path | None = Path("render_cache")
    cache_max_size_mb: int = Field(default=200, gt=0)
    clear_on_startup: bool = True


class PicConfig(BaseModel):
    id: str
    backend: SendpicBackendType
    command: str
    aliases: set[str] = Field(default_factory=set)
    image_dir: str
    image_filename_template: str
    help_message: str | None = None
    message_template: str = DEFAULT_SENDPIC_MESSAGE_TEMPLATE

    @field_validator("id", "command", "image_dir", "image_filename_template")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        return string_list(value)


class SendpicConfig(BaseModel):
    cnb_token: str | None = None
    cnb_repo: str | None = None
    local_root: Path = Field(default_factory=_default_sendpic_local_root)
    configs: list[PicConfig] = Field(default_factory=list)
    enabled_ids: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("enabled_ids", mode="before")
    @classmethod
    def normalize_enabled_ids(cls, value: object) -> object:
        return string_list(value)

    @field_validator("configs")
    @classmethod
    def validate_pics(cls, value: list[PicConfig]) -> list[PicConfig]:
        seen: set[str] = set()
        for pic in value:
            if pic.id in seen:
                raise ValueError(f"图片类型【{pic.id}】重复")
            seen.add(pic.id)

        return value

    @model_validator(mode="after")
    def validate_configs(self) -> Self:
        for pic in self.configs:
            if pic.backend == "cnb" and (not self.cnb_token or not self.cnb_repo):
                raise ValueError(  # noqa: TRY003
                    f"CNB 相关配置未设置，而命令【{pic.command}】需要该配置"
                )
        return self


class ModulesConfig(BaseModel):
    ai: AiConfig = Field(default_factory=AiConfig)
    bilibili: BiliConfig = Field(default_factory=BiliConfig)
    message: MessageActionsConfig = Field(default_factory=MessageActionsConfig)
    seer: SeerQueryConfig = Field(default_factory=SeerQueryConfig)
    activity: ActivityConfig = Field(default_factory=ActivityConfig)
    team: TeamConfig = Field(default_factory=TeamConfig)
    meeting: MeetingConfig = Field(default_factory=MeetingConfig)
    startup: StartupConfig = Field(default_factory=StartupConfig)
    server_status: ServerStatusConfig = Field(default_factory=ServerStatusConfig)
    restart: RestartConfig = Field(default_factory=RestartConfig)
    headless_notice: HeadlessNoticeConfig = Field(default_factory=HeadlessNoticeConfig)
    help: HelpConfig = Field(default_factory=HelpConfig)
    priority: SuperuserPriorityConfig = Field(default_factory=SuperuserPriorityConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    sendpic: SendpicConfig = Field(default_factory=SendpicConfig)


class DataSourceConfig(BaseModel):
    url: str
    fingerprint_url: str = ""
    interval_minutes: int = Field(default=60, gt=0)
    local_path: str


class DataSyncConfig(BaseModel):
    on_startup: bool = False
    interval_enabled: bool = True
    sources: dict[str, DataSourceConfig] = Field(
        default_factory=lambda: {
            "seerapi": DataSourceConfig(
                url=f"{IRONS_DATA_RELEASE}/ironsbot-data-latest/ironsbot-data.sqlite",
                fingerprint_url=(
                    f"{IRONS_DATA_RELEASE}/ironsbot-data-latest/"
                    "ironsbot-data.sqlite.sha256"
                ),
                interval_minutes=60,
                local_path="data/ironsbot-data.sqlite",
            ),
            "aliases": DataSourceConfig(
                url=f"{IRONS_DATA_RELEASE}/alias-db-latest/aliases-data.sqlite",
                fingerprint_url=(
                    f"{IRONS_DATA_RELEASE}/alias-db-latest/"
                    "aliases-data.sqlite.sha256"
                ),
                interval_minutes=60,
                local_path="data/aliases-data.sqlite",
            ),
        }
    )


class FeaturePolicyConfig(BaseModel):
    group_aliases: dict[str, int] = Field(default_factory=dict)
    user_aliases: dict[str, int] = Field(default_factory=dict)
    feature_group_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_user_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_superuser_bypass: bool = True

    @field_validator("group_aliases", "user_aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        return _coerce_int_mapping(value)

    @field_validator("feature_group_policy", "feature_user_policy", mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> object:
        return _coerce_policy_mapping(value)


class Config(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ai_key: str = ""
    data_sync_config: DataSyncConfig = Field(default_factory=DataSyncConfig)
    headless_seer_login_server_addr: str = "https://seer-login-ip.61.com/unity-ip.txt"
    headless_seer_user_id: int | None = Field(
        default=None,
        description="米米号",
        ge=10001,
    )
    headless_seer_password: str | None = None
    headless_seer_heartbeat_interval: float = 300
    headless_seer_reconnect_retries: int = -1
    headless_seer_reconnect_delay: float = 5.0
    headless_seer_reconnect_delay_max: float = 120.0
    team_ids: list[int] = Field(default_factory=list)
    team_resource_users: list[int] = Field(default_factory=list)
    modules: ModulesConfig = Field(default_factory=ModulesConfig)
    group_aliases: dict[str, int] = Field(default_factory=dict)
    user_aliases: dict[str, int] = Field(default_factory=dict)
    feature_group_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_user_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_superuser_bypass: bool = True

    @field_validator("modules", mode="before")
    @classmethod
    def normalize_modules(cls, value: object) -> object:
        return nested_json_config(value, ModulesConfig, name="APP_CONFIG")

    @field_validator("data_sync_config", mode="before")
    @classmethod
    def normalize_data_sync_config(cls, value: object) -> object:
        return nested_json_config(
            value,
            DataSyncConfig,
            name="APP_CONFIG.runtime.data_sync",
        )

    @field_validator("team_ids", "team_resource_users", mode="before")
    @classmethod
    def normalize_int_ids(cls, value: object) -> object:
        return int_list(value)

    @field_validator("group_aliases", "user_aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        return _coerce_int_mapping(value)

    @field_validator("feature_group_policy", "feature_user_policy", mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> object:
        return _coerce_policy_mapping(value)

    @property
    def ai_config(self) -> AiConfig:
        return self.modules.ai

    @property
    def bili_config(self) -> BiliConfig:
        return self.modules.bilibili

    @property
    def msg_config(self) -> MessageActionsConfig:
        return self.modules.message

    @property
    def seer_query_config(self) -> SeerQueryConfig:
        return self.modules.seer

    @property
    def activity_config(self) -> ActivityConfig:
        return self.modules.activity

    @property
    def team_config(self) -> TeamConfig:
        return self.modules.team

    @property
    def meeting_config(self) -> MeetingConfig:
        return self.modules.meeting

    @property
    def startup_config(self) -> StartupConfig:
        return self.modules.startup

    @property
    def server_status_config(self) -> ServerStatusConfig:
        return self.modules.server_status

    @property
    def bot_restart_config(self) -> RestartConfig:
        return self.modules.restart

    @property
    def headless_notice_config(self) -> HeadlessNoticeConfig:
        return self.modules.headless_notice

    @property
    def help_ignored_plugins(self) -> list[str]:
        return self.modules.help.ignored_plugins

    @property
    def superuser_priority(self) -> bool:
        return self.modules.priority.enabled

    @property
    def superuser_priority_wait_timeout_seconds(self) -> float:
        return self.modules.priority.wait_timeout_seconds

    @property
    def render_config(self) -> RenderConfig:
        return self.modules.render

    @property
    def sendpic_config(self) -> SendpicConfig:
        return self.modules.sendpic

    @property
    def sendpic_cnb_token(self) -> str | None:
        return self.modules.sendpic.cnb_token

    @property
    def sendpic_cnb_repo(self) -> str | None:
        return self.modules.sendpic.cnb_repo

    @property
    def sendpic_local_root(self) -> Path:
        return self.modules.sendpic.local_root

    @property
    def sendpic_configs(self) -> list[PicConfig]:
        return self.modules.sendpic.configs

    @property
    def sendpic_enabled_ids(self) -> frozenset[str]:
        return self.modules.sendpic.enabled_ids

    @property
    def feature_policy(self) -> FeaturePolicyConfig:
        return FeaturePolicyConfig(
            group_aliases=self.group_aliases,
            user_aliases=self.user_aliases,
            feature_group_policy=self.feature_group_policy,
            feature_user_policy=self.feature_user_policy,
            feature_superuser_bypass=self.feature_superuser_bypass,
        )


def _merge_template(
    template: AiActionTemplate,
    action: AiIntentAction,
) -> dict[str, Any]:
    template_data = template.model_dump()
    action_data = action.model_dump(exclude_unset=True)
    template_data.update(action_data)
    return template_data


def resolve_configured_actions(config: AiConfig) -> list[AiIntentAction]:
    actions: list[AiIntentAction] = []
    for action in config.intent_actions:
        resolved_action = action
        if action.template:
            template = config.action_templates.get(action.template)
            if template is not None:
                resolved_action = AiIntentAction.model_validate(
                    _merge_template(template, action)
                )
        actions.append(resolved_action)
    return actions


def unique_ints(values: Iterable[int]) -> list[int]:
    return unique_items(values)
