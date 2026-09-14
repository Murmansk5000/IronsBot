from __future__ import annotations

from functools import partial
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from ironsbot.config.models.settings import Settings
from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.messaging import PicConfig
from ironsbot.core.plugin_install import PluginContributionCatalog
from ironsbot.core.promotions import PromotionCatalog
from ironsbot.integrations.docker.client import DockerClient
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.integrations.process import terminate_bot_process
from ironsbot.integrations.scheduler.facade import SchedulerFacade
from ironsbot.plugins.onebot.about import (
    plugin_contribution as about_plugin_contribution,
)
from ironsbot.plugins.onebot.activity import (
    plugin_contribution as activity_plugin_contribution,
)
from ironsbot.plugins.onebot.ai import (
    plugin_contribution as ai_chat_plugin_contribution,
)
from ironsbot.plugins.onebot.ai.intent import (
    plugin_contribution as ai_intent_plugin_contribution,
)
from ironsbot.plugins.onebot.bilibili import (
    plugin_contribution as bilibili_plugin_contribution,
)
from ironsbot.plugins.onebot.fire_manual_ad import (
    plugin_contribution as fire_manual_ad_plugin_contribution,
)
from ironsbot.plugins.onebot.headless_seer_notice import (
    plugin_contribution as headless_notice_plugin_contribution,
)
from ironsbot.plugins.onebot.headless_seer_runtime import (
    plugin_contribution as headless_runtime_plugin_contribution,
)
from ironsbot.plugins.onebot.help import plugin_contribution as help_plugin_contribution
from ironsbot.plugins.onebot.help.hint import (
    plugin_contribution as help_hint_plugin_contribution,
)
from ironsbot.plugins.onebot.lucky_skin_window import (
    plugin_contribution as lucky_skin_window_plugin_contribution,
)
from ironsbot.plugins.onebot.messaging import (
    plugin_contribution as messaging_plugin_contribution,
)
from ironsbot.plugins.onebot.messaging.blacklist import (
    plugin_contribution as blacklist_plugin_contribution,
)
from ironsbot.plugins.onebot.messaging.meeting import (
    plugin_contribution as meeting_plugin_contribution,
)
from ironsbot.plugins.onebot.messaging.red_packet import (
    plugin_contribution as red_packet_plugin_contribution,
)
from ironsbot.plugins.onebot.operations.db_sync import (
    plugin_contribution as db_sync_plugin_contribution,
)
from ironsbot.plugins.onebot.operations.docker_update import (
    plugin_contribution as docker_update_plugin_contribution,
)
from ironsbot.plugins.onebot.operations.server_status import (
    plugin_contribution as server_status_plugin_contribution,
)
from ironsbot.plugins.onebot.pet_config import (
    plugin_contribution as pet_config_plugin_contribution,
)
from ironsbot.plugins.onebot.scheduled_restart import (
    plugin_contribution as scheduled_restart_plugin_contribution,
)
from ironsbot.plugins.onebot.scheduler import (
    plugin_contribution as scheduler_plugin_contribution,
)
from ironsbot.plugins.onebot.seer.query import (
    plugin_contribution as seer_query_plugin_contribution,
)
from ironsbot.plugins.onebot.seer.rank_help import (
    plugin_contribution as rank_help_plugin_contribution,
)
from ironsbot.plugins.onebot.sendpic import (
    plugin_contribution as sendpic_plugin_contribution,
)
from ironsbot.plugins.onebot.startup_notice import (
    plugin_contribution as startup_notice_plugin_contribution,
)
from ironsbot.plugins.onebot.team_audit import (
    plugin_contribution as team_audit_plugin_contribution,
)
from ironsbot.plugins.onebot.team_resource import (
    plugin_contribution as team_resource_plugin_contribution,
)
from ironsbot.services.about import AboutService
from ironsbot.services.operations.docker_update import DockerUpdateService
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.operations.scheduled_restart import ScheduledRestartService
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from ironsbot.app.composition import ApplicationResources
    from ironsbot.core.plugin_install import PluginContribution


async def _noop_startup(_scheduler: object) -> None:
    return


def _noop_startup_notice_add(*_args: object) -> None:
    return


async def _noop_refresh_push_time(
    _option: object,
    *,
    scheduler: object,
    activity_service: object,
) -> None:
    del scheduler, activity_service


async def _noop_bili_login_notice(
    _reason: str,
    **_kwargs: object,
) -> None:
    return None


async def _noop_bot_connect(
    _bot: object,
    *,
    scheduler: object,
) -> None:
    del scheduler


async def _noop_query() -> str:
    return ""


def build_test_plugin_registry(
    settings: Settings | None = None,
) -> tuple[PluginContribution, ...]:
    config = settings or Settings()
    runtime = build_test_runtime(
        feature_config=config.features,
        superuser_ids=tuple(config.superuser_ids),
        command_features=config.messaging.command_feature_keys,
        schedule_features=config.messaging.schedule_feature_keys,
    )
    headless = HeadlessService(
        ClientManager(runtime.tasks.create),
        config.operations.headless,
        config.operations.headless_notice,
        runtime.admin_notices,
    )
    docker_update = DockerUpdateService(
        config.operations.docker_update,
        DockerClient(),
        partial(
            terminate_bot_process,
            signal_parent=True,
            reason="admin requested bot restart",
        ),
    )
    scheduled_restart = ScheduledRestartService(
        restart_times=(
            tuple(config.operations.restart.parsed_restart_times)
            if config.operations.restart.enabled
            else ()
        ),
        grace_seconds=config.operations.restart.grace_seconds,
        restart_process=partial(
            terminate_bot_process,
            signal_parent=config.operations.restart.signal_parent,
            reason="scheduled bot restart",
        ),
    )
    resources = cast(
        "ApplicationResources",
        SimpleNamespace(
            about=AboutService("test"),
            query_sessions=PortableQuerySessions(),
            features=runtime.features,
            promotions=PromotionCatalog(config.promotions),
            admin_notices=runtime.admin_notices,
            activity=SimpleNamespace(register_jobs=lambda _scheduler: None),
            headless=headless,
            server_status=object(),
            subscriptions=object(),
            bilibili=SimpleNamespace(
                targets=SimpleNamespace(
                    can_conversation_query_history=lambda _conversation: False,
                ),
            ),
            bilibili_login=SimpleNamespace(
                notify_required=_noop_bili_login_notice,
            ),
            bilibili_monitor=SimpleNamespace(
                check_on_connect=_noop_startup,
                notify_auth_invalid=_noop_bili_login_notice,
                register_job=_noop_startup,
            ),
            lucky_skin_window=SimpleNamespace(
                enabled=False,
                is_eligible_actor=lambda _actor: False,
                account_for_actor=lambda _actor: None,
            ),
            messaging=SimpleNamespace(
                portable_command_actions=(),
                refresh_push_time_jobs=_noop_refresh_push_time,
                start=_noop_startup,
            ),
            sendpic=SimpleNamespace(
                commands=(
                    PicConfig(
                        id="example-image",
                        backend="local",
                        command="示例图片",
                        mode="single",
                        image_file="example.png",
                    ),
                ),
                exact_command_texts=frozenset({"示例图片"}),
            ),
            team_audit=SimpleNamespace(start=_noop_bot_connect),
            team_resource=SimpleNamespace(
                enabled=config.seer.team_resource.enabled,
                query_commands=tuple(config.seer.team_resource.commands),
                register_jobs=lambda _scheduler: None,
            ),
            local_rank=object(),
            rank_page_refresh=object(),
            player_id_resolver=PlayerIdResolver(
                lambda _reference, _conversation: None,
                lambda _actor: None,
            ),
            pet_config=SimpleNamespace(
                search=_noop_query,
                select=_noop_query,
            ),
            seer=SimpleNamespace(
                data_queries=SimpleNamespace(
                    weekly_preview=_noop_query,
                    data_version=_noop_query,
                    new_content_snapshot=lambda: None,
                    season_countdown=_noop_query,
                ),
                countermark_rank=SimpleNamespace(
                    query=lambda _command: "",
                ),
                autocard=SimpleNamespace(
                    search=lambda _arg: SimpleNamespace(
                        entry=None,
                        prompt_values=(),
                        prompt_text="",
                        message="",
                    ),
                    select=lambda _value: None,
                ),
                autocard_media=SimpleNamespace(outbound=_noop_query),
                autocard_sanctuary=SimpleNamespace(
                    search=_noop_query,
                    select=_noop_query,
                ),
                team_query=SimpleNamespace(
                    parse_team_ids=lambda _text: (),
                    query=_noop_query,
                ),
                equipment=SimpleNamespace(
                    search=_noop_query,
                    select=_noop_query,
                ),
                type_query=SimpleNamespace(
                    search=_noop_query,
                    select=_noop_query,
                ),
                battle_effect=SimpleNamespace(
                    search=_noop_query,
                    select=_noop_query,
                ),
                pet_query=SimpleNamespace(
                    search_image=_noop_query,
                    select_image=_noop_query,
                    search_info=_noop_query,
                    select_info=_noop_query,
                ),
                peak_query=SimpleNamespace(
                    pool=_noop_query,
                    vote=_noop_query,
                    item_rank=_noop_query,
                    pet_rank=_noop_query,
                ),
                mintmark=SimpleNamespace(
                    search_mintmark=_noop_query,
                    select_mintmark=_noop_query,
                    search_gem=_noop_query,
                    select_gem=_noop_query,
                ),
                player=SimpleNamespace(
                    default_player_id=lambda _user_id: None,
                    query=_noop_query,
                    bind_player=_noop_query,
                    save_binding_choice=lambda *_args, **_kwargs: "",
                    binding_offer=lambda _pending, **_kwargs: "",
                    unbind=lambda _user_id: "",
                    shortcut=_noop_query,
                    format_error=lambda _player_id, error: str(error),
                ),
                player_detail_extensions=PlayerDetailExtensionRegistry(),
                rank_queries=SimpleNamespace(
                    help_message=lambda: "",
                    default_limit=lambda _group_id: 10,
                    list=_noop_query,
                    score=_noop_query,
                    player=_noop_query,
                    set_display_limit=lambda **_kwargs: "",
                ),
                rank_admin=SimpleNamespace(
                    cache_batch=_noop_query,
                    page_status=lambda _command: "",
                    page_overview=lambda: "",
                    page_refresh=_noop_query,
                    cache_status=lambda _group_id: "",
                    cache_refresh=_noop_query,
                ),
            ),
            ai=object(),
            ai_startup_check=_noop_startup,
            data_sync=SimpleNamespace(startup=_noop_startup),
            docker_update=docker_update,
            startup_notice=SimpleNamespace(add=_noop_startup_notice_add),
            scheduled_restart=scheduled_restart,
            commands=CommandCatalog(),
            contribution_catalog=PluginContributionCatalog(),
            help_hint=object(),
            private_extensions=SimpleNamespace(load_plugins=lambda: ()),
        ),
    )
    return (
        scheduler_plugin_contribution(scheduler=SchedulerFacade()),
        seer_query_plugin_contribution(
            settings=config,
            resources=resources,
            scheduler=SchedulerFacade(),
        ),
        bilibili_plugin_contribution(
            service=resources.bilibili,
            features=runtime.features,
            monitor=resources.bilibili_monitor,
            scheduler=SchedulerFacade(),
            query_sessions=resources.query_sessions,
        ),
        messaging_plugin_contribution(
            config=config.messaging,
            features=runtime.features,
            references=config.onebot_references,
            service=resources.messaging,
            activity_service=resources.activity,
            scheduler=SchedulerFacade(),
            query_sessions=resources.query_sessions,
        ),
        ai_chat_plugin_contribution(
            settings=config,
            service=resources.ai,
            features=runtime.features,
            commands=resources.commands,
            startup_check=resources.ai_startup_check,
        ),
        ai_intent_plugin_contribution(
            settings=config,
            service=resources.ai,
            features=runtime.features,
            promotions=resources.promotions,
            team_resource=resources.team_resource,
        ),
        server_status_plugin_contribution(
            service=resources.server_status,
            features=runtime.features,
            commands=resources.commands,
        ),
        docker_update_plugin_contribution(
            service=resources.docker_update,
            features=runtime.features,
            startup_notice=resources.startup_notice,
            query_sessions=resources.query_sessions,
        ),
        db_sync_plugin_contribution(
            service=resources.data_sync,
            features=runtime.features,
            startup_notice=resources.startup_notice,
            scheduler=SchedulerFacade(),
            query_sessions=resources.query_sessions,
        ),
        about_plugin_contribution(resources.about),
        help_plugin_contribution(
            contribution_catalog=resources.contribution_catalog,
            features=runtime.features,
            commands=resources.commands,
            query_sessions=resources.query_sessions,
            ignored_plugins=tuple(config.features.help.ignored_plugins),
        ),
        sendpic_plugin_contribution(
            service=resources.sendpic,
            features=runtime.features,
        ),
        meeting_plugin_contribution(
            commands=tuple(config.messaging.meeting.commands),
            number=config.messaging.meeting.number,
            template=config.messaging.meeting.template,
            features=runtime.features,
        ),
        blacklist_plugin_contribution(features=runtime.features),
        red_packet_plugin_contribution(
            config=config.messaging.red_packet_notice,
            admin_notices=runtime.admin_notices,
        ),
        fire_manual_ad_plugin_contribution(),
        help_hint_plugin_contribution(service=resources.help_hint),
        rank_help_plugin_contribution(
            features=runtime.features,
            commands=resources.commands,
            player_id_resolver=resources.player_id_resolver,
        ),
        pet_config_plugin_contribution(
            service=resources.pet_config,
            features=runtime.features,
            config=config.pet_config,
            query_sessions=resources.query_sessions,
        ),
        lucky_skin_window_plugin_contribution(
            resources.lucky_skin_window,
            resources.seer.pet_query,
            runtime.features,
            SchedulerFacade(),
            resources.query_sessions,
        ),
        team_audit_plugin_contribution(
            scheduler=SchedulerFacade(),
            service=resources.team_audit,
        ),
        team_resource_plugin_contribution(
            config=config.seer.team_resource,
            features=runtime.features,
            scheduler=SchedulerFacade(),
            service=resources.team_resource,
        ),
        activity_plugin_contribution(
            service=resources.activity,
            features=runtime.features,
            scheduler=SchedulerFacade(),
        ),
        startup_notice_plugin_contribution(
            service=resources.startup_notice,
            config=config.operations.startup_notice,
        ),
        headless_notice_plugin_contribution(
            scheduler=SchedulerFacade(),
            service=headless,
        ),
        headless_runtime_plugin_contribution(service=headless),
        scheduled_restart_plugin_contribution(
            scheduler=SchedulerFacade(),
            service=resources.scheduled_restart,
        ),
    )
