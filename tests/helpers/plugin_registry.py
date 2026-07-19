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
from ironsbot.services.operations.docker_update import DockerUpdateService
from ironsbot.services.operations.headless import HeadlessService
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from ironsbot.app.composition import ApplicationResources
    from ironsbot.runtime.plugins import PluginDefinition


async def _noop_startup(_scheduler: object) -> None:
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
) -> tuple[PluginDefinition, ...]:
    config = settings or Settings()
    runtime = build_test_runtime(
        feature_config=config.features,
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
            priority=runtime.priority,
            subscriptions=object(),
            bilibili=SimpleNamespace(
                targets=object(),
            ),
            bilibili_login=SimpleNamespace(
                notify_required=_noop_bili_login_notice,
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
            seer=SimpleNamespace(
                data_queries=SimpleNamespace(
                    weekly_preview=_noop_query,
                    data_version=_noop_query,
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
                    binding_offer=lambda _pending: "",
                    unbind=lambda _user_id: "",
                    create_detail_task=lambda _pending: None,
                    spawn_task=lambda _coroutine, **_kwargs: None,
                    shortcut=_noop_query,
                    format_error=lambda _player_id, error: str(error),
                ),
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
            startup_notice=object(),
            help_hint=object(),
        ),
    )
    return build_plugin_registry(
        settings=config,
        resources=resources,
        scheduler=SchedulerFacade(),
    )
