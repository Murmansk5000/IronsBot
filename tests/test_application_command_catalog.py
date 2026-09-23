from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pytest import MonkeyPatch

from ironsbot.app.application import Application
from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.plugin_install import PluginContribution, PluginContributionCatalog


def test_application_validates_the_catalog_after_matcher_registration(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "ironsbot.integrations.onebot.portable_queries.install_portable_menu_router",
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
        settings=cast("Any", object()),
        driver=cast("Any", Driver()),
        asgi=cast("Any", object()),
        scheduler=cast("Any", object()),
        file_logging=cast("Any", object()),
        http_clients=cast("Any", object()),
        databases=cast("Any", object()),
        prompt_sessions=cast("Any", object()),
        resources=cast(
            "Any",
            SimpleNamespace(
                commands=commands,
                query_sessions=object(),
                features=object(),
                contribution_catalog=PluginContributionCatalog(),
            ),
        ),
        matcher_factory=cast("Any", Matchers()),
        extension_contexts={},
        task_owner=cast("Any", object()),
        known_features=(),
        required_plugin_features=frozenset(),
        contributions=(),
    )

    application.configure(contributions)
    application.install()
    application.install()

    assert calls == [
        "plugin",
        "portable_router",
        "queued_router",
        "validate",
        "postprocessor",
        "lifecycle",
    ]
