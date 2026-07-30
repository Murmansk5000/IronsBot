from dataclasses import dataclass

import pytest

from ironsbot.runtime.commands import (
    CommandAccess,
    CommandCatalog,
    CommandCatalogError,
    CommandContext,
    CommandDescriptor,
)
from ironsbot.runtime.plugins import PluginDefinition


@dataclass(slots=True)
class FakeFeatures:
    group_features: dict[int, set[str]]
    private_features: dict[int, set[str]]
    superusers: set[int]

    def is_group_feature_allowed(
        self,
        _user_id: int,
        group_id: int,
        feature: str,
    ) -> bool:
        return feature in self.group_features.get(group_id, set())

    def group_has_feature(self, group_id: int, feature: str) -> bool:
        return feature in self.group_features.get(group_id, set())

    def is_private_feature_allowed(self, user_id: int, feature: str) -> bool:
        return feature in self.private_features.get(user_id, set())

    def is_superuser(self, user_id: int) -> bool:
        return user_id in self.superusers


def _catalog(*commands: CommandDescriptor) -> CommandCatalog:
    catalog = CommandCatalog()
    catalog.load(
        (PluginDefinition(id="example", commands=commands),),
        known_features={"example_feature", "fallback_feature"},
    )
    return catalog


def test_catalog_filters_scope_feature_and_audience() -> None:
    catalog = _catalog(
        CommandDescriptor(
            id="regular",
            plugin_id="example",
            section="查询",
            examples=("查询",),
            description="查询资料",
            features_any=("example_feature",),
            show_in_poke=True,
        ),
        CommandDescriptor(
            id="manager",
            plugin_id="example",
            section="管理",
            examples=("/管理",),
            description="管理本群",
            features_any=("example_feature",),
            access=(CommandAccess("group", "group_manager"),),
            show_in_poke=True,
        ),
        CommandDescriptor(
            id="superuser",
            plugin_id="example",
            section="超级管理员",
            examples=("/更新",),
            description="更新数据",
            access=(CommandAccess(audience="superuser"),),
            show_in_poke=True,
        ),
    )
    features = FakeFeatures(
        group_features={100: {"example_feature"}},
        private_features={1: {"example_feature"}},
        superusers={3},
    )

    regular = catalog.available_for_context(
        CommandContext(user_id=1, group_id=100, group_role="member"),
        features,
    )
    manager = catalog.available_for_context(
        CommandContext(user_id=2, group_id=100, group_role="admin"),
        features,
    )
    superuser = catalog.available_for_context(
        CommandContext(user_id=3, group_id=100),
        features,
    )
    private = catalog.available_for_context(
        CommandContext(user_id=1, group_id=None),
        features,
    )

    assert [command.id for command in regular] == ["regular"]
    assert [command.id for command in manager] == ["regular", "manager"]
    assert [command.id for command in superuser] == [
        "regular",
        "manager",
        "superuser",
    ]
    assert [command.id for command in private] == ["regular"]


def test_catalog_supports_any_feature_and_multiple_access_rules() -> None:
    catalog = _catalog(
        CommandDescriptor(
            id="mixed",
            plugin_id="example",
            section="查询",
            examples=("查询",),
            description="私聊用户或群管理员可用",
            features_any=("example_feature", "fallback_feature"),
            access=(
                CommandAccess(scope="private"),
                CommandAccess("group", "group_manager"),
            ),
        )
    )
    features = FakeFeatures(
        group_features={100: {"fallback_feature"}},
        private_features={1: {"example_feature"}},
        superusers=set(),
    )

    assert [command.id for command in catalog.available_for_context(
        CommandContext(user_id=1, group_id=None), features
    )] == ["mixed"]
    assert [command.id for command in catalog.available_for_context(
        CommandContext(user_id=2, group_id=100, group_role="admin"), features
    )] == ["mixed"]
    assert not catalog.available_for_context(
        CommandContext(user_id=2, group_id=100, group_role="member"), features
    )


def test_catalog_binds_feature_conditions_to_the_matching_access_rule() -> None:
    catalog = _catalog(
        CommandDescriptor(
            id="combined",
            plugin_id="example",
            section="Query",
            examples=("query",),
            description="Two independently available modes",
            access=(
                CommandAccess(features_any=("example_feature",)),
                CommandAccess(
                    "group",
                    "group_manager",
                    ("fallback_feature",),
                ),
            ),
        )
    )
    features = FakeFeatures(
        group_features={100: {"fallback_feature"}},
        private_features={1: {"example_feature"}},
        superusers=set(),
    )

    assert not catalog.available_for_context(
        CommandContext(user_id=2, group_id=100, group_role="member"),
        features,
    )
    assert catalog.available_for_context(
        CommandContext(user_id=2, group_id=100, group_role="admin"),
        features,
    )
    assert catalog.available_for_context(
        CommandContext(user_id=1, group_id=None),
        features,
    )


def test_catalog_rejects_duplicate_ids_unknown_plugins_and_features() -> None:
    duplicate = CommandDescriptor(
        id="duplicate",
        plugin_id="example",
        section="查询",
        examples=("查询",),
        description="查询资料",
    )
    catalog = CommandCatalog()
    with pytest.raises(CommandCatalogError, match="duplicate"):
        catalog.load(
            (PluginDefinition(id="example", commands=(duplicate, duplicate)),),
        )

    unknown_plugin = CommandDescriptor(
        id="unknown_plugin",
        plugin_id="missing",
        section="查询",
        examples=("查询",),
        description="查询资料",
    )
    with pytest.raises(CommandCatalogError, match="unknown plugins"):
        catalog.load((PluginDefinition(id="example", commands=(unknown_plugin,)),))

    unknown_feature = CommandDescriptor(
        id="unknown_feature",
        plugin_id="example",
        section="查询",
        examples=("查询",),
        description="查询资料",
        features_any=("missing_feature",),
    )
    with pytest.raises(CommandCatalogError, match="unknown features"):
        catalog.load((PluginDefinition(id="example", commands=(unknown_feature,)),))


def test_group_manager_command_cannot_be_private_only() -> None:
    with pytest.raises(CommandCatalogError, match="cannot be private-only"):
        CommandDescriptor(
            id="invalid",
            plugin_id="example",
            section="管理",
            examples=("管理",),
            description="管理资料",
            access=(CommandAccess("private", "group_manager"),),
        )


def test_catalog_cannot_be_reloaded_after_validation() -> None:
    catalog = _catalog(
        CommandDescriptor(
            id="regular",
            plugin_id="example",
            section="查询",
            examples=("查询",),
            description="查询资料",
            features_any=("example_feature",),
        )
    )

    with pytest.raises(CommandCatalogError, match="already loaded"):
        catalog.load(())


def test_catalog_rejects_unknown_and_unregistered_direct_command_ids() -> None:
    catalog = _catalog(
        CommandDescriptor(
            id="documented",
            plugin_id="example",
            section="查询",
            examples=("查询",),
            description="查询资料",
        )
    )

    with pytest.raises(CommandCatalogError, match="unknown command descriptor"):
        catalog.validate_matcher_registrations(help_ids=("missing",))
    with pytest.raises(CommandCatalogError, match="no matcher registration"):
        catalog.validate_matcher_registrations(help_ids=())
    with pytest.raises(CommandCatalogError, match="no help ids"):
        catalog.validate_matcher_registrations(
            help_ids=("documented",),
            unclassified_labels=("unregistered_matcher",),
        )

    catalog.validate_matcher_registrations(help_ids=("documented",))
