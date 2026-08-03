import re
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from ironsbot.config.loader import CONFIG_ENV, ConfigFileNotFoundError, load_settings
from ironsbot.config.models.messaging import (
    BotRoutingConfig,
    CommandCooldownConfig,
    CommandCooldownWindowConfig,
    MessageCommandAction,
    MessageConfig,
    MessageScheduledAction,
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
    PushUnsubscribeConfig,
)
from ironsbot.config.models.operations import (
    DockerUpdateConfig,
)
from ironsbot.config.models.seer import (
    NEW_CONTENT_CATEGORY_KEYS,
    LuckySkinWindowConfig,
    NewContentMenuConfig,
    PlayerRequestProtectionConfig,
    RankPageRefreshConfig,
    TeamResourceConfig,
)
from ironsbot.config.models.settings import MatcherPriorityConfig, Settings
from ironsbot.core.bilibili import (
    DEFAULT_BILI_ACCOUNT_ALIAS,
    DEFAULT_BILI_ACCOUNT_UID,
)
from ironsbot.core.features import FeatureService

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AI_CHAT_PRIORITY = 200
HEADLESS_USER_ID = 12345678
ADDITIONAL_HEADLESS_USER_ID = 23456789
DEFAULT_OUTBOUND_MAX_MESSAGES = 10
DEFAULT_HELP_HINT_MAX_PER_WINDOW = 3
DEFAULT_RENDER_CACHE_MAX_SIZE_MB = 200
DEFAULT_DOCKER_UPDATE_TIMEOUT_SECONDS = 300.0
CUSTOM_PLAYER_BINDING_COOLDOWN_DAYS = 5
DEFAULT_PLAYER_BINDING_COOLDOWN_DAYS = 3
_REFRESH_TTL_SECONDS = 120.0
DEFAULT_RANK_DISPLAY_LIMIT = 10
DEFAULT_RANK_MAX_DISPLAY_LIMIT = 100
DEFAULT_RANK_STALE_AGE_WEIGHT = 0.08
DEFAULT_RANK_STALE_AGE_MAX_MULTIPLIER = 5.0
DEFAULT_RANK_REFRESH_PAGES_PER_RUN_MIN = 1
DEFAULT_RANK_REFRESH_INTERVAL_MINUTES = 15
DEFAULT_RANK_REFRESH_INTERVAL_OFFSET_MINUTES = 4
DEFAULT_RANK_REFRESH_SCHEDULE_JITTER_SECONDS = 240
DEFAULT_RANK_REFRESH_REQUEST_INTERVAL_SECONDS = 3.0
DEFAULT_RANK_REFRESH_REQUEST_JITTER_SECONDS = 3.0
DEFAULT_AUTOCARD_SCORE_CUTOFF = 1000
DEFAULT_TEAM_AUDIT_FOLLOWUP_HOURS = 24.0
DEFAULT_TEAM_AUDIT_FINAL_FOLLOWUP_HOURS = 48.0
DEFAULT_SEER_PLAYER_PRIORITY = 10
LUCKY_SKIN_WINDOW_OWNER_ID = 123456789
DEFAULT_PLAYER_REQUEST_MAX_QUEUED = 3
DEFAULT_PLAYER_REQUEST_INTERVAL_SECONDS = 1.2
DEFAULT_PLAYER_REQUEST_PAUSE_SECONDS = 60.0
DEFAULT_PLAYER_REQUEST_REPEAT_WINDOW_SECONDS = 600.0
DEFAULT_PLAYER_REQUEST_REPEAT_PAUSE_SECONDS = 300.0
CUSTOM_PLAYER_REQUEST_MAX_QUEUED = 5
CUSTOM_PLAYER_REQUEST_INTERVAL_SECONDS = 1.5
CUSTOM_PLAYER_REQUEST_PAUSE_SECONDS = 45.0
CUSTOM_PLAYER_REQUEST_REPEAT_WINDOW_SECONDS = 480.0
CUSTOM_PLAYER_REQUEST_REPEAT_PAUSE_SECONDS = 240.0
MAIN_BOT_ID = 111111111
DEFAULT_RED_PACKET_NOTICE_COOLDOWN = 60.0
TEAM_RESOURCE_THRESHOLD = 2000


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_default_push_unsubscribe(
    push_unsubscribe: PushUnsubscribeConfig,
) -> None:
    assert (
        push_unsubscribe.commands,
        push_unsubscribe.restore_commands,
    ) == (
        ["td", "退订"],
        ["订阅", "恢复订阅", "推送管理"],
    )
    assert "TD" in push_unsubscribe.hint
    assert "可查看本群推送订阅" in push_unsubscribe.group_hint


def _assert_default_docker_update(docker_update: DockerUpdateConfig) -> None:
    assert docker_update.check_on_startup
    assert docker_update.check_on_restart
    assert docker_update.image == "murmansk5000/ironsbot:latest"
    assert docker_update.container_name == "ironsbot"
    assert docker_update.docker_socket_path == "/var/run/docker.sock"
    assert docker_update.watchtower_image == "containrrr/watchtower:latest"
    assert docker_update.watchtower_docker_api_version == "1.40"
    assert docker_update.timeout_seconds == DEFAULT_DOCKER_UPDATE_TIMEOUT_SECONDS
    assert docker_update.registry_username == ""
    assert docker_update.registry_token == ""


def _assert_default_player_request_protection(
    protection: PlayerRequestProtectionConfig,
) -> None:
    assert protection.enabled
    assert protection.max_queued_queries == DEFAULT_PLAYER_REQUEST_MAX_QUEUED
    assert (
        protection.base_request_interval_seconds
        == DEFAULT_PLAYER_REQUEST_INTERVAL_SECONDS
    )
    assert protection.disconnect_pause_seconds == DEFAULT_PLAYER_REQUEST_PAUSE_SECONDS
    assert (
        protection.repeat_disconnect_window_seconds
        == DEFAULT_PLAYER_REQUEST_REPEAT_WINDOW_SECONDS
    )
    assert (
        protection.repeat_disconnect_pause_seconds
        == DEFAULT_PLAYER_REQUEST_REPEAT_PAUSE_SECONDS
    )
    assert protection.superuser_priority
    assert protection.superuser_bypass_pause


def _assert_default_file_logging(config: Settings) -> None:
    assert not config.bot.logging.file_enabled
    assert not config.bot.logging.error_file_enabled
    assert config.bot.logging.rotation == "00:00"
    assert config.bot.logging.retention == "30 days"
    assert config.bot.logging.compression is None


def _assert_example_bot_routing(config: Settings) -> None:
    routing = config.messaging.bot_routing
    assert not routing.enabled
    assert routing.default_bot == "main_bot"
    assert routing.bot_aliases == {
        "main_bot": MAIN_BOT_ID,
        "backup_bot": 222222222,
    }
    assert routing.groups == {
        "group_a": "main_bot",
        "group_b": "backup_bot",
    }
    assert routing.users == {
        "owner": "main_bot",
        "user_a": "backup_bot",
    }


def _assert_default_team_audit_welcome(config: Settings) -> None:
    team_audit = config.messaging.team_audit_welcome
    assert not team_audit.enabled
    assert "米米号" in team_audit.message
    assert team_audit.followup_enabled
    assert team_audit.followup_after_hours == DEFAULT_TEAM_AUDIT_FOLLOWUP_HOURS
    assert "退出本审核群" in team_audit.followup_message
    assert "还没有发送审核信息" not in team_audit.followup_message
    assert team_audit.final_followup_enabled
    assert (
        team_audit.final_followup_after_hours == DEFAULT_TEAM_AUDIT_FINAL_FOLLOWUP_HOURS
    )
    assert "仍然还在审核群" in team_audit.final_followup_message
    assert config.paths.runtime_state == Path("data/state/runtime_state.sqlite")


def _assert_default_matcher_priorities(
    matcher_priority: MatcherPriorityConfig,
) -> None:
    assert matcher_priority.seer_query < matcher_priority.ai_chat
    assert matcher_priority.ai_group_at < 0
    assert matcher_priority.ai_mention_guard < 0
    assert matcher_priority.ai_group_at < matcher_priority.ai_mention_guard
    assert matcher_priority.ai_chat == DEFAULT_AI_CHAT_PRIORITY
    assert matcher_priority.seer_player == DEFAULT_SEER_PLAYER_PRIORITY
    assert matcher_priority.sendpic < matcher_priority.seer_pet
    assert matcher_priority.sendpic < matcher_priority.seer_mintmark
    assert matcher_priority.seer_pet > matcher_priority.seer_rank
    assert matcher_priority.pet_config < matcher_priority.seer_pet
    assert matcher_priority.seer_mintmark > matcher_priority.seer_rank
    priorities = matcher_priority.model_dump()
    non_negative_priorities = [value for value in priorities.values() if value >= 0]
    assert len(non_negative_priorities) == len(set(non_negative_priorities))


def _assert_example_rank_page_refresh(config: RankPageRefreshConfig) -> None:
    assert "群星牌" in config.rank_keys
    assert "竞技段位" in config.rank_keys
    assert "狂野段位" in config.rank_keys
    assert "专家段位" in config.rank_keys
    assert config.target_limits == {}
    assert config.score_cutoffs["群星牌"] == DEFAULT_AUTOCARD_SCORE_CUTOFF
    assert config.stale_age_weight == DEFAULT_RANK_STALE_AGE_WEIGHT
    assert config.stale_age_max_multiplier == DEFAULT_RANK_STALE_AGE_MAX_MULTIPLIER
    assert config.pages_per_run_min == DEFAULT_RANK_REFRESH_PAGES_PER_RUN_MIN
    assert config.interval_minutes == DEFAULT_RANK_REFRESH_INTERVAL_MINUTES
    assert (
        config.interval_offset_minutes == DEFAULT_RANK_REFRESH_INTERVAL_OFFSET_MINUTES
    )
    assert (
        config.schedule_jitter_seconds == DEFAULT_RANK_REFRESH_SCHEDULE_JITTER_SECONDS
    )
    assert (
        config.request_interval_seconds == DEFAULT_RANK_REFRESH_REQUEST_INTERVAL_SECONDS
    )
    assert config.request_jitter_seconds == DEFAULT_RANK_REFRESH_REQUEST_JITTER_SECONDS
    assert config.active_start == "07:30"
    assert config.active_end == "01:30"
    assert config.times == []


def test_example_config_parses() -> None:
    config = load_settings(ROOT / "config.example.toml")

    assert config.features.superuser_bypass
    assert config.features.group_aliases == {
        "group_a": 987654321,
        "group_b": 876543210,
    }
    assert config.features.user_aliases == {
        "owner": 1234567890,
        "user_a": 2345678901,
        "qq_group_manager": 2854196310,
    }
    assert config.features.user_policy["qq_group_manager"] == ["blacklist"]
    assert config.ai.model == "deepseek-v4-pro"
    assert "fire_manual" in config.ai.intent_actions
    assert (
        config.bilibili.accounts[DEFAULT_BILI_ACCOUNT_ALIAS].uid
        == DEFAULT_BILI_ACCOUNT_UID
    )
    assert config.bilibili.push.mode == "full"
    assert config.bilibili.push.accounts == [DEFAULT_BILI_ACCOUNT_ALIAS]
    assert config.bilibili.push.modes == {}
    assert config.bilibili.polling.windows[0].start == "07:00"
    assert "恭喜" in config.bilibili.filters.suppress_push_patterns
    assert config.messaging.meeting.commands == ["开播", "会议"]
    _assert_default_push_unsubscribe(config.messaging.push_unsubscribe)
    assert config.messaging.red_packet_notice.enabled
    assert (
        config.messaging.red_packet_notice.cooldown_seconds
        == DEFAULT_RED_PACKET_NOTICE_COOLDOWN
    )
    _assert_default_team_audit_welcome(config)
    assert config.seer.team_resource.commands == ["战队"]
    assert config.seer.new_content.expanded_categories == []
    assert config.seer.lucky_skin_window == LuckySkinWindowConfig()
    assert config.paths.qq_state == Path("data/state/qq_state.sqlite")
    assert "autocard" in config.seer.player.sections
    assert config.seer.rank.display_limit == DEFAULT_RANK_DISPLAY_LIMIT
    assert config.seer.rank.max_display_limit == DEFAULT_RANK_MAX_DISPLAY_LIMIT
    assert config.seer.rank.display_limits == {}
    _assert_example_rank_page_refresh(config.seer.rank.page_refresh)
    assert config.seer.season.autocard_name == "群星牌赛季"
    assert config.seer.season.autocard_start_time is None
    assert config.seer.season.autocard_end_time is None
    assert config.operations.data_sync.on_startup
    _assert_example_bot_routing(config)
    assert not config.operations.data_sync.startup_trigger_remote_build
    assert config.operations.data_sync.sources["seerapi"].local_path
    assert config.operations.data_sync.sources["seerapi"].remote_build.enabled
    _assert_default_docker_update(config.operations.docker_update)
    assert config.paths.log_file == Path("logs/ironsbot.log")
    assert config.paths.error_log_file == Path("logs/ironsbot.error.log")
    _assert_default_file_logging(config)
    _assert_default_player_request_protection(config.seer.player.request_protection)
    _assert_default_matcher_priorities(config.bot.matcher_priority)
    remote_build_steps = config.operations.data_sync.sources[
        "seerapi"
    ].remote_build.steps
    assert [step.name for step in remote_build_steps] == [
        "refresh_official_sources",
        "refresh_unity_config",
        "sync_config_sources",
        "build_api_data",
        "build_ironsbot_data",
    ]
    assert remote_build_steps[-1].repository == "Murmansk-Seer/seerapi"
    assert remote_build_steps[-1].workflow_id == "build-seerapi-data-db.yml"
    assert remote_build_steps[0].inputs == {
        "force-update-assets": False,
        "force-update-config": False,
        "dispatch-api-data": False,
    }
    assert remote_build_steps[1].inputs == {}
    assert remote_build_steps[2].inputs == {"force": False}
    assert remote_build_steps[3].inputs == {
        "debug_enabled": False,
        "force": False,
    }
    assert remote_build_steps[4].inputs == {"force": False}


def test_example_config_pet_config_defaults() -> None:
    config = load_settings(ROOT / "config.example.toml")

    assert config.pet_config.enabled
    assert config.pet_config.image_dir == Path("data/pet_configs")
    assert config.features.help.ignored_plugins == []


def test_example_config_has_no_unknown_fields() -> None:
    assert isinstance(load_settings(ROOT / "config.example.toml", env={}), Settings)


def test_scheduled_push_requires_stable_id() -> None:
    with pytest.raises(ValidationError, match="定时推送必须配置非空 id"):
        MessageScheduledAction(
            message="私聊定时推送",
            hour=23,
        )

    with pytest.raises(ValidationError, match="只能包含英文字母"):
        MessageScheduledAction(
            id="每日 提醒",
            message="私聊定时推送",
            hour=23,
        )


def test_scheduled_push_ids_are_globally_unique() -> None:
    with pytest.raises(ValidationError, match="定时推送 id 必须全局唯一: daily"):
        MessageConfig(
            schedules=[
                MessageScheduledAction(
                    id="daily",
                    message="私聊定时推送",
                    hour=23,
                ),
                MessageScheduledAction(
                    id="daily",
                    message="群聊定时推送",
                    hour=23,
                ),
            ],
        )


def test_dynamic_message_commands_require_stable_ids() -> None:
    with pytest.raises(
        ValidationError,
        match="command message action requires a non-empty id",
    ):
        MessageCommandAction(
            commands=["hello"],
            message="world",
        )

    with pytest.raises(
        ValidationError,
        match="command message action id may only contain",
    ):
        MessageCommandAction(
            id="daily reminder",
            commands=["hello"],
            message="world",
        )


def test_outbound_rate_limit_requires_distinct_nonempty_windows() -> None:
    with pytest.raises(
        ValidationError,
        match=r"outbound_rate_limit\.windows must not be empty",
    ):
        OutboundRateLimitConfig(windows=[])

    window = OutboundRateLimitWindowConfig(
        window_seconds=60,
        max_messages=10,
    )
    with pytest.raises(
        ValidationError,
        match=r"contains duplicate window_seconds",
    ):
        OutboundRateLimitConfig(windows=[window, window])


def test_command_cooldown_rejects_unknown_message_placeholders() -> None:
    with pytest.raises(
        ValidationError,
        match=r"only supports \{remaining_seconds\}",
    ):
        CommandCooldownConfig(cooldown_message="{unknown}")


def test_command_cooldown_requires_distinct_default_windows() -> None:
    window = CommandCooldownWindowConfig(
        window_seconds=60,
        max_requests=3,
    )
    with pytest.raises(
        ValidationError,
        match=r"command_cooldown\.windows must not be empty",
    ):
        CommandCooldownConfig(windows=[])
    with pytest.raises(
        ValidationError,
        match=r"contains duplicate window_seconds",
    ):
        CommandCooldownConfig(windows=[window, window])


def test_bot_routing_config_accepts_aliases_and_numeric_bot_ids() -> None:
    config = BotRoutingConfig(
        enabled=True,
        default_bot="main_bot",
        bot_aliases={"main_bot": MAIN_BOT_ID},
        groups={"group_a": "main_bot", "987654321": MAIN_BOT_ID},
        users={"owner": "111111111"},
    )

    assert config.resolve_bot_reference("main_bot") == MAIN_BOT_ID
    assert config.resolve_bot_reference(str(MAIN_BOT_ID)) == MAIN_BOT_ID


def test_bot_routing_config_rejects_unknown_bot_alias() -> None:
    with pytest.raises(
        ValidationError,
        match=r"messaging\.bot_routing\.groups\.group_a",
    ):
        BotRoutingConfig(
            enabled=True,
            bot_aliases={"main_bot": MAIN_BOT_ID},
            groups={"group_a": "missing_bot"},
        )


def test_rank_page_refresh_interval_offset_must_be_smaller_than_interval() -> None:
    with pytest.raises(ValidationError):
        RankPageRefreshConfig(interval_minutes=10, interval_offset_minutes=10)


def test_rank_page_refresh_min_pages_must_not_exceed_max_pages() -> None:
    with pytest.raises(ValidationError):
        RankPageRefreshConfig(pages_per_run=2, pages_per_run_min=3)


def test_rank_page_refresh_active_window_requires_start_and_end() -> None:
    with pytest.raises(ValidationError):
        RankPageRefreshConfig(active_start="07:30")


def test_new_content_menu_config_validates_expanded_categories() -> None:
    assert NewContentMenuConfig(
        expanded_categories=["pet", "skill", "pet"]
    ).expanded_categories == ["pet", "skill"]
    all_categories = NewContentMenuConfig(expanded_categories=["all"])
    assert all_categories.expanded_categories == list(NEW_CONTENT_CATEGORY_KEYS)
    with pytest.raises(
        ValidationError,
        match=re.escape("seer.new_content.expanded_categories"),
    ):
        NewContentMenuConfig(expanded_categories=["unknown_category"])


def test_missing_app_config_fails_without_mutating_disk(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "ironsbot.toml"
    with pytest.raises(ConfigFileNotFoundError, match="未找到 IronsBot 配置文件"):
        load_settings(config_path, env={})
    assert not config_path.exists()


def test_missing_app_config_error_explains_expected_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "ironsbot.toml"

    with pytest.raises(ConfigFileNotFoundError) as exc_info:
        load_settings(config_path, env={})

    assert str(config_path) in str(exc_info.value)
    assert CONFIG_ENV in str(exc_info.value)
    assert "config.example.toml" in str(exc_info.value)


def test_config_path_is_selected_by_single_environment_variable() -> None:
    config = load_settings(env={CONFIG_ENV: str(ROOT / "config.example.toml")})
    assert config.ai.model == "deepseek-v4-pro"


def test_unknown_app_config_fields_are_ignored_and_reported(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
unknown_top_level = true

[seer.player]
old_player_setting = true

[[messaging.commands]]
id = "hello"
commands = ["hello"]
message = "world"
feature = "text_push"
unknown_command_field = true
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)
    output = capsys.readouterr().err

    assert config.messaging.commands[0].id == "hello"
    assert "IronsBot 配置含无法识别的字段，已忽略并继续启动" in output
    assert "unknown_top_level" in output
    assert "seer.player.old_player_setting" in output
    assert "messaging.commands[0].unknown_command_field" in output


def test_unknown_fields_do_not_hide_invalid_known_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[bot]
port = 0
old_bot_setting = true
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert exc_info.value.errors()[0]["loc"] == ("bot", "port")


def test_unified_message_actions_parse_as_toml_arrays_of_tables(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[[messaging.commands]]
id = "activity_link"
commands = ["activity"]
message = "activity link"
feature = "web_activity_link"
at_user_ids = [123456789]

[[messaging.schedules]]
id = "daily_reminder"
name = "Daily reminder"
hour = 23
minute = 0
message = "daily message"
feature = "text_push"
at_user_ids = [123456789]
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)
    assert config.messaging.commands[0].id == "activity_link"
    assert config.messaging.commands[0].at_user_ids == [123456789]
    assert config.messaging.schedules[0].id == "daily_reminder"
    assert config.messaging.schedules[0].at_user_ids == [123456789]



def test_message_command_feature_registers_for_bundle_and_group_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[features.group_aliases]
main = 123456789

[features.bundles]
standard = ["seerinfo_link"]

[features.group_policy]
main = ["standard"]

[[messaging.commands]]
id = "seerinfo_page"
commands = ["xm", "xrym"]
message = "https://seerinfo.yuyuqaq.cn/"
feature = "seerinfo_link"
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)
    features = FeatureService(
        config.features,
        frozenset(),
        command_features=config.messaging.command_feature_keys,
        schedule_features=config.messaging.schedule_feature_keys,
    )

    assert config.messaging.command_feature_keys == frozenset({"seerinfo_link"})
    assert features.is_group_feature_allowed(
        999,
        123456789,
        "seerinfo_link",
    )


def test_message_schedule_feature_registers_for_user_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[features.user_aliases]
owner = 123456789

[features.user_policy]
owner = ["custom_reminder"]

[[messaging.schedules]]
id = "custom_reminder"
hour = 23
message = "remember"
feature = "custom_reminder"
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)

    assert config.messaging.schedule_feature_keys == frozenset({"custom_reminder"})


def test_blacklist_feature_loads_user_and_group_aliases(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[features.group_aliases]
blocked_group = 987654321

[features.user_aliases]
blocked_user = 123456789

[features.group_policy]
blocked_group = ["blacklist"]

[features.user_policy]
blocked_user = ["blacklist"]
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)

    features = FeatureService(config.features, config.superuser_ids)
    assert features.is_conversation_blocked(123456789)
    assert features.is_conversation_blocked(1, 987654321)


def test_all_bundle_declares_custom_extension_feature(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[features.group_aliases]
main = 123456789

[features.bundles]
all = ["private_extension"]

[features.group_policy]
main = ["all"]
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)
    features = FeatureService(config.features, config.superuser_ids)

    assert features.is_group_feature_allowed(1, 123456789, "private_extension")


def test_onebot_config_references_accept_aliases_and_numeric_ids(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[bot]
superusers = ["owner", "300"]

[features.group_aliases]
main_group = 100

[features.user_aliases]
owner = 200
at_user = 201

[features.bundles]
all = ["private_extension"]

[features.group_policy]
main_group = ["all"]

[features.user_policy]
owner = ["blacklist"]

[features.help]
poke_replies = { main_group = "group reply" }
poke_user_replies = { owner = "user reply" }

[bilibili.push.groups.main_group]
accounts = []

[bilibili.push.users.owner]
accounts = []

[messaging.bot_routing]
bot_aliases = { primary = 400 }

[messaging.bot_routing.groups]
main_group = "primary"

[messaging.bot_routing.users]
owner = "primary"

[[messaging.commands]]
id = "custom_command"
commands = ["custom"]
message = "custom reply"
feature = "private_extension"
at_user_ids = ["at_user", "202"]

[[messaging.schedules]]
id = "custom_schedule"
hour = 12
minute = 0
message = "scheduled reply"
feature = "private_extension"
at_user_ids = ["at_user", 202]

[seer.rank]
display_limits = { main_group = 5 }

[seer.team_resource]
default_at_users = ["at_user", "202"]
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)

    assert config.superuser_ids == frozenset({200, 300})
    assert config.onebot_references.resolve_groups(
        ["main_group", "100"],
        location="test.groups",
    ) == [100]
    assert config.onebot_references.resolve_users(
        ["at_user", 202],
        location="test.users",
    ) == [201, 202]


@pytest.mark.parametrize(
    ("toml", "expected_path"),
    [
        (
            """
[features.group_policy]
unknown_group = ["seer"]
""",
            "features.group_policy.unknown_group",
        ),
        (
            """
[features.group_aliases]
"123" = 100
""",
            "features.group_aliases.123 must not use a numeric alias",
        ),
        (
            """
[[messaging.commands]]
id = "custom_command"
commands = ["custom"]
message = "custom reply"
feature = "text"
at_user_ids = ["unknown_user"]
""",
            "messaging.commands[0].at_user_ids[0]",
        ),
    ],
)
def test_invalid_onebot_config_reference_reports_exact_path(
    tmp_path: Path,
    toml: str,
    expected_path: str,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(toml.strip(), encoding="utf-8")

    with pytest.raises(ValidationError, match=re.escape(expected_path)):
        load_settings(config_path)


def test_unregistered_feature_policy_is_rejected_with_exact_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[features.group_policy]
main = ["seer_player", "rank"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert exc_info.value.errors()[0]["loc"] == ("features",)
    assert "features.group_policy.main[1]=rank" in str(exc_info.value)


def test_unknown_bilibili_account_is_rejected_with_exact_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[bilibili.push.groups.main]
accounts = ["missing_account"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert exc_info.value.errors()[0]["loc"] == ("bilibili",)
    assert "bilibili.push.groups.main.accounts[0]" in str(exc_info.value)


def test_unknown_seer_section_is_rejected_with_exact_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.player]
sections = ["basic", "unknown_section"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert exc_info.value.errors()[0]["loc"] == ("seer", "player", "sections")
    assert "seer.player.sections contains unknown section(s)" in str(exc_info.value)


def test_player_binding_uses_shared_qq_state_path(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[paths]
qq_state = "data/custom-player-state.sqlite"

[seer.player.binding]
change_cooldown_days = 5
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)

    assert config.paths.qq_state == Path("data/custom-player-state.sqlite")
    assert (
        config.seer.player.binding.change_cooldown_days
        == CUSTOM_PLAYER_BINDING_COOLDOWN_DAYS
    )


def test_cache_root_accepts_relative_and_absolute_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[paths]
cache_root = "runtime-cache"
""".strip(),
        encoding="utf-8",
    )

    assert load_settings(config_path).paths.cache_root == Path("runtime-cache")

    absolute_root = tmp_path / "absolute-cache"
    config_path.write_text(
        f"""
[paths]
cache_root = "{absolute_root.as_posix()}"
""".strip(),
        encoding="utf-8",
    )

    assert load_settings(config_path).paths.cache_root == absolute_root


def test_removed_player_binding_field_is_ignored(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.player.binding]
change_cooldown_hours = 72.0
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)
    output = capsys.readouterr().err

    assert (
        config.seer.player.binding.change_cooldown_days
        == DEFAULT_PLAYER_BINDING_COOLDOWN_DAYS
    )
    assert "seer.player.binding.change_cooldown_hours" in output


def test_player_background_refresh_loads(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.player.background_refresh]
enabled = true
cache_ttl_seconds = 120.0
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)

    assert config.seer.player.background_refresh.enabled
    assert (
        config.seer.player.background_refresh.cache_ttl_seconds == _REFRESH_TTL_SECONDS
    )


def test_player_background_refresh_defaults_disabled(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text("", encoding="utf-8")

    config = load_settings(config_path)

    assert not config.seer.player.background_refresh.enabled


def test_lucky_skin_window_resolves_user_alias_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[features.user_aliases]
owner = 123456789

[seer.lucky_skin_window]
enabled = true

[[seer.lucky_skin_window.accounts]]
user = "owner"
player_id = 105023264
watched_skin_ids = [1400538]
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path)
    assert config.seer.lucky_skin_window.enabled
    assert config.onebot_references.resolve_user(
        config.seer.lucky_skin_window.accounts[0].user,
        location="test",
    ) == LUCKY_SKIN_WINDOW_OWNER_ID

    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """

[[seer.lucky_skin_window.accounts]]
user = 123456789
player_id = 105023265
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="must not repeat a user"):
        load_settings(config_path)


def test_lucky_skin_window_rejects_duplicate_configured_player_id(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[features.user_aliases]
owner = 123456789
friend = 987654321

[seer.lucky_skin_window]
enabled = true

[[seer.lucky_skin_window.accounts]]
user = "owner"
player_id = 105023264

[[seer.lucky_skin_window.accounts]]
user = "friend"
player_id = 105023264
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="must not repeat a player_id"):
        load_settings(config_path)


def test_player_request_protection_loads(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.player.request_protection]
max_queued_queries = 5
base_request_interval_seconds = 1.5
disconnect_pause_seconds = 45.0
repeat_disconnect_window_seconds = 480.0
repeat_disconnect_pause_seconds = 240.0
superuser_priority = false
superuser_bypass_pause = false
""".strip(),
        encoding="utf-8",
    )

    config = load_settings(config_path).seer.player.request_protection

    assert config.enabled
    assert config.max_queued_queries == CUSTOM_PLAYER_REQUEST_MAX_QUEUED
    assert (
        config.base_request_interval_seconds == CUSTOM_PLAYER_REQUEST_INTERVAL_SECONDS
    )
    assert config.disconnect_pause_seconds == CUSTOM_PLAYER_REQUEST_PAUSE_SECONDS
    assert (
        config.repeat_disconnect_window_seconds
        == CUSTOM_PLAYER_REQUEST_REPEAT_WINDOW_SECONDS
    )
    assert (
        config.repeat_disconnect_pause_seconds
        == CUSTOM_PLAYER_REQUEST_REPEAT_PAUSE_SECONDS
    )
    assert not config.superuser_priority
    assert not config.superuser_bypass_pause


def test_player_request_protection_defaults_are_safe(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text("", encoding="utf-8")

    config = load_settings(config_path).seer.player.request_protection

    _assert_default_player_request_protection(config)


def test_incomplete_unknown_ai_action_is_rejected_with_exact_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[ai.intent_actions.custom_action]
enabled = true
message = "hello"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        load_settings(config_path)

    assert exc_info.value.errors()[0]["loc"] == ("ai",)
    assert "ai.intent_actions.custom_action:" in str(exc_info.value)
    assert "unknown AI intent action must configure" in str(exc_info.value)


def test_invalid_app_config_field_values_still_fail(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[seer.rank]
display_limit = "not an integer"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_settings(config_path)


def test_team_resource_config_accepts_runtime_subscription_defaults() -> None:
    config = TeamResourceConfig(
        times="08:30,23:00",  # type: ignore[arg-type]
        default_threshold=TEAM_RESOURCE_THRESHOLD,
        default_at_users="owner,1234567890",  # type: ignore[arg-type]
    )

    assert config.times == ["08:30", "23:00"]
    assert config.default_threshold == TEAM_RESOURCE_THRESHOLD
    assert config.default_at_users == ["owner", "1234567890"]


def test_environment_secrets_are_injected_into_single_settings_tree() -> None:
    env = {
        "ONEBOT_ACCESS_TOKEN": "token",
        "AI_KEY": "sk-test",
        "SENDPIC_CNB_TOKEN": "cnb-token",
        "GITHUB_WORKFLOW_TOKEN": "gh-token",
        "HEADLESS_SEER_USER_ID": str(HEADLESS_USER_ID),
        "HEADLESS_SEER_PASSWORD": "md5",
    }

    settings = load_settings(ROOT / "config.example.toml", env=env)

    assert settings.bot.onebot_token == "token"
    assert settings.ai.api_key == "sk-test"
    assert settings.messaging.sendpic.cnb_token == "cnb-token"
    assert settings.operations.data_sync.github_token == "gh-token"
    assert settings.operations.headless.user_id == HEADLESS_USER_ID
    assert settings.operations.headless.password == "md5"


def test_additional_headless_workers_resolve_environment_references(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[[operations.headless.workers]]
name = "worker_2"
user_id_env = "WORKER_2_USER_ID"
password_env = "WORKER_2_PASSWORD"
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(
        config_path,
        env={
            "WORKER_2_USER_ID": "23456789",
            "WORKER_2_PASSWORD": "md5-worker-2",
        },
    )

    worker = settings.operations.headless.workers[0]
    assert worker.name == "worker_2"
    assert worker.user_id == ADDITIONAL_HEADLESS_USER_ID
    assert worker.password == "md5-worker-2"


@pytest.mark.parametrize("missing_env", ["WORKER_2_USER_ID", "WORKER_2_PASSWORD"])
def test_additional_headless_worker_requires_referenced_environment(
    tmp_path: Path,
    missing_env: str,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[[operations.headless.workers]]
name = "worker_2"
user_id_env = "WORKER_2_USER_ID"
password_env = "WORKER_2_PASSWORD"
""".strip(),
        encoding="utf-8",
    )
    env = {
        "WORKER_2_USER_ID": "23456789",
        "WORKER_2_PASSWORD": "md5-worker-2",
    }
    env.pop(missing_env)

    with pytest.raises(ValueError, match=missing_env):
        load_settings(config_path, env=env)


def test_additional_headless_worker_rejects_inline_credentials(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[[operations.headless.workers]]
name = "worker_2"
user_id_env = "WORKER_2_USER_ID"
password_env = "WORKER_2_PASSWORD"
user_id = 23456789
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"operations\.headless\.workers\[0\]"):
        load_settings(
            config_path,
            env={
                "WORKER_2_USER_ID": "23456789",
                "WORKER_2_PASSWORD": "md5-worker-2",
            },
        )


def test_additional_headless_workers_require_unique_accounts(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[[operations.headless.workers]]
name = "worker_2"
user_id_env = "WORKER_2_USER_ID"
password_env = "WORKER_2_PASSWORD"

[[operations.headless.workers]]
name = "worker_3"
user_id_env = "WORKER_3_USER_ID"
password_env = "WORKER_3_PASSWORD"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="account IDs must be unique"):
        load_settings(
            config_path,
            env={
                "WORKER_2_USER_ID": "23456789",
                "WORKER_2_PASSWORD": "md5-worker-2",
                "WORKER_3_USER_ID": "23456789",
                "WORKER_3_PASSWORD": "md5-worker-3",
            },
        )


def test_docker_registry_token_must_be_set_in_environment(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[operations.docker_update]
registry_token = "registry-token"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="DOCKER_REGISTRY_TOKEN"):
        load_settings(config_path)


def test_docker_registry_credentials_read_from_environment(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[operations.docker_update]
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(
        config_path,
        env={
            "DOCKER_REGISTRY_USERNAME": "owner",
            "DOCKER_REGISTRY_TOKEN": "registry-token",
        },
    )

    docker_update = settings.operations.docker_update
    assert docker_update.registry_username == "owner"
    assert docker_update.registry_token == "registry-token"


def test_app_config_defaults_cover_runtime_services() -> None:
    app_config = load_settings(ROOT / "config.example.toml")

    assert app_config.ai.model == "deepseek-v4-pro"
    assert app_config.ai.intent_actions
    assert app_config.seer.team_resource.commands == ["战队"]
    assert (
        app_config.features.help.hint_max_per_window == DEFAULT_HELP_HINT_MAX_PER_WINDOW
    )
    assert app_config.activity.lead_hours == [11, 1]
    assert not app_config.messaging.command_cooldown.enabled
    assert not app_config.messaging.outbound_rate_limit.enabled
    assert "seerapi" in app_config.operations.data_sync.sources
    assert (
        app_config.messaging.outbound_rate_limit.windows[0].max_messages
        == DEFAULT_OUTBOUND_MAX_MESSAGES
    )
    assert app_config.messaging.meeting.commands == ["开播", "会议"]
    assert "aliases" in app_config.operations.data_sync.sources
    assert app_config.paths.cache_root == Path("cache")
    assert app_config.runtime.concurrency.render_max_concurrent == 1
    assert app_config.seer.render.cache_max_size_mb == DEFAULT_RENDER_CACHE_MAX_SIZE_MB
