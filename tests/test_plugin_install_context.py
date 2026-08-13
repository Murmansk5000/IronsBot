from __future__ import annotations

import pytest
from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    PluginContribution,
    PluginExtensionContextError,
    PluginInstallContextError,
    current_plugin_install_context,
    scoped_plugin_install_context,
)


def test_install_context_collects_contributions_only_while_scoped() -> None:
    metadata = PluginMetadata(
        name="Example",
        description="Example plugin",
        usage="example",
        supported_adapters={"~onebot.v11"},
    )
    contribution = PluginContribution(id="example")

    with scoped_plugin_install_context(
        settings=object(),  # type: ignore[arg-type]
        resources=object(),  # type: ignore[arg-type]
        scheduler=object(),  # type: ignore[arg-type]
    ) as context:
        assert current_plugin_install_context() is context
        context.contribute(metadata, contribution)
        assert context.contributions == (contribution,)
        assert context.loaded_contributions[0].metadata is metadata

    with pytest.raises(PluginInstallContextError, match="only available"):
        current_plugin_install_context()


def test_nested_install_context_restores_the_outer_scope() -> None:
    with scoped_plugin_install_context(
        settings=object(),  # type: ignore[arg-type]
        resources=object(),  # type: ignore[arg-type]
        scheduler=object(),  # type: ignore[arg-type]
    ) as outer:
        with scoped_plugin_install_context(
            settings=object(),  # type: ignore[arg-type]
            resources=object(),  # type: ignore[arg-type]
            scheduler=object(),  # type: ignore[arg-type]
        ) as inner:
            assert current_plugin_install_context() is inner

        assert current_plugin_install_context() is outer


def test_install_context_exposes_only_declared_extension_contexts() -> None:
    extension_context = object()

    with scoped_plugin_install_context(
        settings=object(),  # type: ignore[arg-type]
        resources=object(),  # type: ignore[arg-type]
        scheduler=object(),  # type: ignore[arg-type]
        extension_contexts={"example": extension_context},
    ) as context:
        assert context.extension_context("example") is extension_context
        with pytest.raises(PluginExtensionContextError, match="unavailable: missing"):
            context.extension_context("missing")
