from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pytest import MonkeyPatch

from ironsbot.app.application import Application
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.plugin_install import PluginContribution, PluginContributionCatalog
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.integrations.onebot.notice_ingress import OneBotNoticeIngress
from ironsbot.integrations.onebot.received_messages import OneBotReceivedMessages
from ironsbot.integrations.onebot.self_commands import SelfCommandAdapter


def test_application_installs_one_shared_router_after_passive_plugins(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "ironsbot.integrations.onebot.command_ingress.install_command_ingress",
        lambda *_args: calls.append("portable_router"),
    )

    class Matchers:
        def validate_command_catalog(self, catalog: CommandCatalog) -> None:
            calls.append("validate")
            assert catalog is commands

        def install_postprocessor(self) -> None:
            calls.append("postprocessor")

        def install_queued_conversation_router(self) -> None:
            calls.append("queued_router")

    class Driver:
        config = SimpleNamespace(nickname=frozenset())

        def register_adapter(self, adapter: type, **options: Any) -> None:
            calls.append("adapter")
            assert adapter is SelfCommandAdapter
            received = options["received"].__self__
            assert isinstance(received, OneBotReceivedMessages)
            assert received.admission is application.resources.onebot_ingress.admission
            assert received.router is router
            assert received.messenger is application.resources.onebot_messenger
            assert received.red_packets is None
            notices = options["notices"].__self__
            assert isinstance(notices, OneBotNoticeIngress)
            assert notices.admission is received.admission
            assert notices.messenger is received.messenger
            assert notices.poke is notices.audit is notices.red_packets is None
            assert options["spawn"] == application.task_owner.create

        def on_startup(self, _callback: Any) -> None:
            calls.append("lifecycle")

        def on_shutdown(self, _callback: Any) -> None:
            pass

        def on_bot_connect(self, _callback: Any) -> None:
            pass

        def on_bot_disconnect(self, _callback: Any) -> None:
            pass

    def install_plugin(_matchers: Any) -> None:
        calls.append("plugin")

    commands = CommandCatalog()
    contributions = (PluginContribution(id="example", install=install_plugin),)
    application = Application(
        settings=cast(
            "Any",
            SimpleNamespace(
                bot=SimpleNamespace(
                    matcher_priority=SimpleNamespace(red_packet_notice=0)
                )
            ),
        ),
        driver=cast("Any", Driver()),
        asgi=cast("Any", object()),
        scheduler=cast("Any", object()),
        file_logging=cast("Any", object()),
        http_clients=cast("Any", object()),
        databases=cast("Any", object()),
        resources=cast(
            "Any",
            SimpleNamespace(
                commands=commands,
                query_sessions=object(),
                features=object(),
                contribution_catalog=PluginContributionCatalog(),
                onebot_messenger=object(),
                onebot_ingress=SimpleNamespace(admission=object()),
                onebot_connections=OneBotConnections(),
            ),
        ),
        matcher_factory=cast("Any", Matchers()),
        extension_contexts={},
        task_owner=TaskOwner(),
        known_features=(),
        required_plugin_features=frozenset(),
        contributions=(),
    )

    application.configure(contributions)
    router = cast("Any", object())
    application.install(router)
    application.install(router)

    assert calls == [
        "adapter",
        "plugin",
        "portable_router",
        "lifecycle",
    ]
