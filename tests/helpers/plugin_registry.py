from __future__ import annotations

from functools import partial
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from ironsbot.app.registry import build_plugin_registry
from ironsbot.config.models.settings import Settings
from ironsbot.integrations.docker.client import DockerClient
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.integrations.process import terminate_bot_process
from ironsbot.integrations.scheduler.facade import SchedulerFacade
from ironsbot.plugins.about import plugin_contribution as about_plugin_contribution
from ironsbot.plugins.activity import (
    plugin_contribution as activity_plugin_contribution,
)
from ironsbot.plugins.bilibili import (
    plugin_contribution as bilibili_plugin_contribution,
)
from ironsbot.plugins.fire_manual_ad import (
    plugin_contribution as fire_manual_ad_plugin_contribution,
)
from ironsbot.plugins.headless_seer_notice import (
    plugin_contribution as headless_notice_plugin_contribution,
)
from ironsbot.plugins.headless_seer_runtime import (
    plugin_contribution as headless_runtime_plugin_contribution,
)
from ironsbot.plugins.help import plugin_contribution as help_plugin_contribution
from ironsbot.plugins.help.hint import (
    plugin_contribution as help_hint_plugin_contribution,
)
from ironsbot.plugins.messaging.blacklist import (
    plugin_contribution as blacklist_plugin_contribution,
)
from ironsbot.plugins.messaging.meeting import (
    plugin_contribution as meeting_plugin_contribution,
)
from ironsbot.plugins.messaging.red_packet import (
    plugin_contribution as red_packet_plugin_contribution,
)
from ironsbot.plugins.operations.db_sync import (
    plugin_contribution as db_sync_plugin_contribution,
)
from ironsbot.plugins.operations.docker_update import (
    plugin_contribution as docker_update_plugin_contribution,
)
from ironsbot.plugins.operations.server_status import (
    plugin_contribution as server_status_plugin_contribution,
)
from ironsbot.plugins.scheduled_restart import (
    plugin_contribution as scheduled_restart_plugin_contribution,
)
from ironsbot.plugins.seer.lucky_skin_window import (
    plugin_contribution as lucky_skin_window_plugin_contribution,
)
from ironsbot.plugins.seer.rank_help import (
    plugin_contribution as rank_help_plugin_contribution,
)
from ironsbot.plugins.sendpic import plugin_contribution as sendpic_plugin_contribution
from ironsbot.plugins.startup_notice import (
    plugin_contribution as startup_notice_plugin_contribution,
)
from ironsbot.plugins.team.resource import (
    plugin_contribution as team_resource_plugin_contribution,
)
from ironsbot.plugins.team_audit import (
    plugin_contribution as team_audit_plugin_contribution,
)
from ironsbot.runtime.commands import CommandCatalog
from ironsbot.runtime.plugins import PluginContributionCatalog
from ironsbot.services.operations.docker_update import DockerUpdateService
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from ironsbot.app.composition import ApplicationResources
    from ironsbot.runtime.plugins import PluginContribution


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
    resources = cast(
        "ApplicationResources",
        SimpleNamespace(
            features=runtime.features,
            outbound=object(),
            delivery=runtime.delivery,
            admin_notices=runtime.admin_notices,
            activity=SimpleNamespace(register_jobs=lambda _scheduler: None),
            headless=headless,
            server_status=object(),
            subscriptions=object(),
            bilibili=SimpleNamespace(
                targets=SimpleNamespace(
                    can_target_query_history=lambda _target: False,
                ),
            ),
            bilibili_login=SimpleNamespace(
                notify_required=_noop_bili_login_notice,
            ),
            lucky_skin_window=SimpleNamespace(
                enabled=False,
                is_eligible_user=lambda _user_id: False,
                account_for_user=lambda _user_id: None,
            ),
            messaging=SimpleNamespace(
                refresh_push_time_jobs=_noop_refresh_push_time,
                start=_noop_startup,
            ),
            sendpic=SimpleNamespace(commands=()),
            team_audit=SimpleNamespace(start=_noop_bot_connect),
            team_resource=SimpleNamespace(
                register_jobs=lambda _scheduler: None,
            ),
            local_rank=object(),
            rank_page_refresh=object(),
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
                    parse_command=lambda _text: None,
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
            data_sync=SimpleNamespace(startup=_noop_startup),
            docker_update=docker_update,
            startup_notice=SimpleNamespace(add=_noop_startup_notice_add),
            push_message_limiter=lambda message, _target: message,
            commands=CommandCatalog(),
            contribution_catalog=PluginContributionCatalog(),
            help_hint=object(),
            private_extensions=SimpleNamespace(
                load_plugin_contributions=lambda _runtime: ()
            ),
            private_extension_runtime=object(),
        ),
    )
    return (
        *build_plugin_registry(
            settings=config,
            resources=resources,
            scheduler=SchedulerFacade(),
        ),
        bilibili_plugin_contribution(
            service=resources.bilibili,
            login=resources.bilibili_login,
            features=runtime.features,
            config=config.bilibili,
            delivery=resources.delivery,
            subscriptions=resources.subscriptions,
            admin_notices=resources.admin_notices,
            message_limiter=resources.push_message_limiter,
            ai_service=resources.ai,
            scheduler=SchedulerFacade(),
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
        ),
        db_sync_plugin_contribution(
            service=resources.data_sync,
            features=runtime.features,
            startup_notice=resources.startup_notice,
            scheduler=SchedulerFacade(),
        ),
        about_plugin_contribution(),
        help_plugin_contribution(
            contribution_catalog=resources.contribution_catalog,
            features=runtime.features,
            commands=resources.commands,
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
        ),
        lucky_skin_window_plugin_contribution(
            resources.lucky_skin_window,
            runtime.features,
            resources.delivery,
            SchedulerFacade(),
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
            config=config.operations.restart,
            scheduler=SchedulerFacade(),
        ),
    )
