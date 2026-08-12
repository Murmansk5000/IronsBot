from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from ironsbot.app.composition import Application
from ironsbot.runtime.commands import CommandCatalog
from ironsbot.runtime.plugins import PluginDefinition


def test_application_validates_the_catalog_after_matcher_registration() -> None:
    calls: list[str] = []

    class Matchers:
        def validate_command_catalog(self, catalog: CommandCatalog) -> None:
            calls.append("validate")
            assert catalog is commands

        def install_queued_conversation_router(self) -> None:
            calls.append("queued_router")

        def install_postprocessor(self) -> None:
            calls.append("postprocessor")

    class Lifecycle:
        def install(self) -> None:
            calls.append("lifecycle")

    def install_plugin(_matchers: Any) -> None:
        calls.append("plugin")

    commands = CommandCatalog()
    plugins = (PluginDefinition(id="example", install=install_plugin),)
    commands.load(plugins)
    application = Application(
        settings=cast("Any", object()),
        driver=cast("Any", object()),
        asgi=cast("Any", object()),
        scheduler=cast("Any", object()),
        file_logging=cast("Any", object()),
        http_clients=cast("Any", object()),
        databases=cast("Any", object()),
        prompt_sessions=cast("Any", object()),
        resources=cast("Any", SimpleNamespace(commands=commands)),
        plugins=plugins,
        matchers=cast("Any", Matchers()),
        lifecycle=cast("Any", Lifecycle()),
    )

    application.install()
    application.install()

    assert calls == [
        "plugin",
        "queued_router",
        "validate",
        "postprocessor",
        "lifecycle",
    ]
