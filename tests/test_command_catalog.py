from dataclasses import dataclass

import pytest

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandCatalog,
    CommandCatalogError,
    CommandContext,
    CommandContract,
    parsed_command_input_matcher,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution


@dataclass(slots=True)
class FakeFeatures:
    group_features: dict[int, set[str]]
    private_features: dict[int, set[str]]
    superusers: set[int]

    def is_actor_superuser(self, actor: ActorRef) -> bool:
        return int(actor.id) in self.superusers

    def conversation_has_feature(
        self,
        conversation: ConversationRef,
        feature: str,
    ) -> bool:
        return (
            conversation.platform is Platform.ONEBOT
            and conversation.kind == "group"
            and feature in self.group_features.get(int(conversation.id), set())
        )

    def is_feature_allowed(
        self,
        actor: ActorRef,
        conversation: ConversationRef,
        feature: str,
    ) -> bool:
        if conversation.kind == "group":
            return self.conversation_has_feature(conversation, feature)
        return feature in self.private_features.get(int(actor.id), set())

    def is_actor_feature_allowed(self, actor: ActorRef, feature: str) -> bool:
        return feature in self.private_features.get(int(actor.id), set())


def _context(
    user_id: int,
    *,
    group_id: int | None = None,
    group_role: str | None = None,
) -> CommandContext:
    actor = ActorRef(Platform.ONEBOT, str(user_id))
    return CommandContext(
        actor=actor,
        conversation=ConversationRef(
            Platform.ONEBOT,
            "group" if group_id is not None else "private",
            str(group_id if group_id is not None else user_id),
        ),
        group_role=group_role,
    )


def _catalog(*commands: CommandContract) -> CommandCatalog:
    catalog = CommandCatalog()
    catalog.load(
        (PluginContribution(id="example", commands=commands),),
        known_features={"example_feature", "fallback_feature"},
    )
    return catalog


def test_catalog_filters_scope_feature_and_audience() -> None:
    catalog = _catalog(
        CommandContract(
            id="regular",
            plugin_id="example",
            section="查询",
            examples=("查询",),
            description="查询资料",
            features_any=("example_feature",),
            show_in_poke=True,
        ),
        CommandContract(
            id="manager",
            plugin_id="example",
            section="管理",
            examples=("/管理",),
            description="群管理",
            features_any=("example_feature",),
            access=(CommandAccess("group", "group_manager"),),
            show_in_poke=True,
        ),
        CommandContract(
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
        _context(1, group_id=100, group_role="member"),
        features,
    )
    manager = catalog.available_for_context(
        _context(2, group_id=100, group_role="admin"),
        features,
    )
    superuser = catalog.available_for_context(
        _context(3, group_id=100),
        features,
    )
    private = catalog.available_for_context(
        _context(1),
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
        CommandContract(
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

    assert [
        command.id for command in catalog.available_for_context(_context(1), features)
    ] == ["mixed"]
    assert [
        command.id
        for command in catalog.available_for_context(
            _context(2, group_id=100, group_role="admin"), features
        )
    ] == ["mixed"]
    assert not catalog.available_for_context(
        _context(2, group_id=100, group_role="member"), features
    )


def test_catalog_requires_all_declared_features() -> None:
    catalog = _catalog(
        CommandContract(
            id="new_pet",
            plugin_id="example",
            section="新增内容",
            examples=("新增精灵",),
            description="查看新增精灵",
            features_all=("example_feature", "fallback_feature"),
        )
    )
    features = FakeFeatures(
        group_features={
            100: {"example_feature"},
            101: {"example_feature", "fallback_feature"},
        },
        private_features={1: {"example_feature", "fallback_feature"}},
        superusers=set(),
    )

    assert not catalog.available_for_context(_context(1, group_id=100), features)
    assert catalog.available_for_context(
        _context(1, group_id=101),
        features,
    )
    assert catalog.available_for_context(
        _context(1),
        features,
    )


def test_catalog_claims_available_direct_inputs_and_parameterized_inputs() -> None:
    catalog = _catalog(
        CommandContract(
            id="help",
            plugin_id="example",
            section="基础",
            examples=("帮助",),
            description="打开帮助",
        ),
        CommandContract(
            id="refresh",
            plugin_id="example",
            section="管理",
            examples=("/动态刷新",),
            routing_aliases=("动态更新", "刷新动态", "更新动态"),
            description="刷新动态",
            access=(CommandAccess(audience="superuser"),),
        ),
        CommandContract(
            id="parameterized",
            plugin_id="example",
            section="查询",
            examples=("米米号<号码>",),
            description="查询玩家",
            routing_matcher=lambda text, _context: (
                text.startswith("米米号") and text[3:].isdecimal()
            ),
        ),
        CommandContract(
            id="automatic",
            plugin_id="example",
            section="通知",
            examples=("活动",),
            description="自动推送",
            interaction="automatic",
        ),
    )
    features = FakeFeatures(
        group_features={},
        private_features={1: set()},
        superusers={1},
    )
    context = _context(1)

    assert catalog.claims_direct_input(context, features, "帮助")
    assert catalog.claims_direct_input(context, features, "/动态刷新")
    assert catalog.claims_direct_input(context, features, "动态更新")
    assert catalog.claims_direct_input(context, features, "米米号123456")
    assert not catalog.claims_direct_input(context, features, "米米号示例玩家")
    assert not catalog.claims_direct_input(context, features, "活动")
    assert not catalog.claims_direct_input(context, features, "动态刷新")
    assert not catalog.claims_direct_input(context, features, "//动态刷新")
    assert not catalog.claims_direct_input(context, features, "/帮助")


def test_parser_adapter_accepts_falsy_values_but_not_none() -> None:
    def parser(text: str) -> int | None:
        return int(text) if text.isdecimal() else None

    accepts_zero = parsed_command_input_matcher(parser)
    positive_only = parsed_command_input_matcher(
        parser, accepts=lambda value: value > 0
    )
    context = _context(1)
    assert accepts_zero("0", context)
    assert accepts_zero("1", context)
    assert not accepts_zero("unknown", context)
    assert not positive_only("0", context)
    assert positive_only("1", context)


def test_catalog_binds_feature_conditions_to_the_matching_access_rule() -> None:
    catalog = _catalog(
        CommandContract(
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
        _context(2, group_id=100, group_role="member"),
        features,
    )
    assert catalog.available_for_context(
        _context(2, group_id=100, group_role="admin"),
        features,
    )
    assert catalog.available_for_context(
        _context(1),
        features,
    )


def test_catalog_rejects_duplicate_ids_unknown_plugins_and_features() -> None:
    duplicate = CommandContract(
        id="duplicate",
        plugin_id="example",
        section="查询",
        examples=("查询",),
        description="查询资料",
    )
    catalog = CommandCatalog()
    with pytest.raises(CommandCatalogError, match="duplicate"):
        catalog.load(
            (PluginContribution(id="example", commands=(duplicate, duplicate)),),
        )

    unknown_plugin = CommandContract(
        id="unknown_plugin",
        plugin_id="missing",
        section="查询",
        examples=("查询",),
        description="查询资料",
    )
    with pytest.raises(CommandCatalogError, match="unknown plugins"):
        catalog.load((PluginContribution(id="example", commands=(unknown_plugin,)),))

    unknown_feature = CommandContract(
        id="unknown_feature",
        plugin_id="example",
        section="查询",
        examples=("查询",),
        description="查询资料",
        features_any=("missing_feature",),
    )
    with pytest.raises(CommandCatalogError, match="unknown features"):
        catalog.load((PluginContribution(id="example", commands=(unknown_feature,)),))


def test_group_manager_command_cannot_be_private_only() -> None:
    with pytest.raises(CommandCatalogError, match="cannot be private-only"):
        CommandContract(
            id="invalid",
            plugin_id="example",
            section="管理",
            examples=("管理",),
            description="管理资料",
            access=(CommandAccess("private", "group_manager"),),
        )


def test_catalog_cannot_be_reloaded_after_validation() -> None:
    catalog = _catalog(
        CommandContract(
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
        CommandContract(
            id="documented",
            plugin_id="example",
            section="查询",
            examples=("查询",),
            description="查询资料",
        )
    )

    with pytest.raises(CommandCatalogError, match="unknown command contract"):
        catalog.validate_matcher_registrations(help_ids=("missing",))
    with pytest.raises(CommandCatalogError, match="no matcher registration"):
        catalog.validate_matcher_registrations(help_ids=())
    with pytest.raises(CommandCatalogError, match="no help ids"):
        catalog.validate_matcher_registrations(
            help_ids=("documented",),
            unclassified_labels=("unregistered_matcher",),
        )

    catalog.validate_matcher_registrations(help_ids=("documented",))


def test_parser_rejection_cannot_be_bypassed_by_a_help_example_or_alias() -> None:
    command = CommandContract(
        id="parsed", plugin_id="example", section="query",
        examples=("reserved",), routing_aliases=("also reserved",),
        description="A parser owns admission, not its illustrative examples",
        routing_matcher=lambda text, _context: text == "accepted",
    )
    assert command.matches_direct_input(_context(1), "accepted")
    assert not command.matches_direct_input(_context(1), "reserved")
    assert not command.matches_direct_input(_context(1), "also reserved")
