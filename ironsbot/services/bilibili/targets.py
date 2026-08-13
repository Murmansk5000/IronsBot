from collections.abc import Mapping
from dataclasses import dataclass, field

from ironsbot.core.bilibili import (
    BiliAccountCategorySubscriptionConfig,
    BiliConfig,
    BiliPushMode,
    BiliPushTargetConfig,
)
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    private_conversation_for_actor,
)
from ironsbot.services.bilibili.accounts import (
    BiliAccountNames,
    configured_account_alias_lookup,
)
from ironsbot.services.bilibili.preferences import (
    BiliPushPreferenceStore,
    bili_category_submenu_key,
    bili_category_subscription_key,
    bili_push_subscription_key,
    bili_push_subscription_label,
    normalize_push_mode_text,
    push_mode_label,
)
from ironsbot.services.messaging.subscription_options import (
    build_push_subscription_menu,
)
from ironsbot.services.messaging.subscriptions import (
    PushSubscriptionOption,
    PushSubscriptionRepository,
)


def _unique_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(item for item in values if item > 0))


ACCOUNT_NAMES_UNAVAILABLE = (
    "❌ 暂时无法获取当前会话订阅账号的 B站公开昵称，请稍后重试。"
)


@dataclass(frozen=True, slots=True)
class BiliTargetRule:
    aliases: frozenset[str]
    uids: frozenset[int]
    default_mode: BiliPushMode
    target_mode: BiliPushMode | None
    modes: dict[int, BiliPushMode]

    def mode_for_uid(self, uid: int) -> BiliPushMode | None:
        if uid not in self.uids:
            return None
        return self.modes.get(uid, self.target_mode or self.default_mode)

    def configured_mode_for_uid(self, uid: int) -> BiliPushMode | None:
        if uid not in self.uids:
            return None
        configured_mode = self.modes.get(uid)
        return configured_mode if configured_mode is not None else self.target_mode


@dataclass(frozen=True, slots=True)
class BiliPushTargets:
    full_group_conversations: list[ConversationRef]
    link_group_conversations: list[ConversationRef]
    full_private_conversations: list[ConversationRef]
    link_private_conversations: list[ConversationRef]

    @property
    def has_targets(self) -> bool:
        return any(
            (
                self.full_group_conversations,
                self.link_group_conversations,
                self.full_private_conversations,
                self.link_private_conversations,
            )
        )


def _target_aliases(
    target_config: BiliPushTargetConfig,
    config: BiliConfig,
) -> frozenset[str]:
    return frozenset(
        [
            *config.push.accounts,
            *target_config.accounts,
        ]
    )


def _resolve_modes(
    modes: dict[str, BiliPushMode],
    config: BiliConfig,
) -> dict[int, BiliPushMode]:
    return {config.accounts[alias].uid: mode for alias, mode in modes.items()}


def build_bili_target_rule(
    target_config: BiliPushTargetConfig,
    config: BiliConfig,
) -> BiliTargetRule:
    aliases = _target_aliases(target_config, config)
    return BiliTargetRule(
        aliases=aliases,
        uids=frozenset(config.accounts[alias].uid for alias in aliases),
        default_mode=config.push.mode,
        target_mode=target_config.mode,
        modes={
            **_resolve_modes(config.push.modes, config),
            **_resolve_modes(target_config.modes, config),
        },
    )


def _default_rule(config: BiliConfig) -> BiliTargetRule:
    return build_bili_target_rule(BiliPushTargetConfig(), config)


def merge_bili_target_rules(
    old_rule: BiliTargetRule,
    new_rule: BiliTargetRule,
) -> BiliTargetRule:
    return BiliTargetRule(
        aliases=old_rule.aliases | new_rule.aliases,
        uids=old_rule.uids | new_rule.uids,
        default_mode=new_rule.default_mode,
        target_mode=new_rule.target_mode,
        modes={**old_rule.modes, **new_rule.modes},
    )


@dataclass(frozen=True, slots=True)
class BiliConfiguredTargets:
    """Platform-resolved push-target rules consumed by Bili services."""

    group_rules: Mapping[ConversationRef, BiliTargetRule]
    private_rules: Mapping[ConversationRef, BiliTargetRule]


@dataclass(frozen=True, slots=True)
class BiliTargetService:
    config: BiliConfig
    features: FeatureService
    configured_targets: BiliConfiguredTargets
    preferences: BiliPushPreferenceStore
    unsubscribe_store: PushSubscriptionRepository
    account_names: BiliAccountNames = field(default_factory=BiliAccountNames)

    def configured_group_rules(self) -> dict[ConversationRef, BiliTargetRule]:
        return dict(self.configured_targets.group_rules)

    def configured_user_rules(self) -> dict[ConversationRef, BiliTargetRule]:
        return dict(self.configured_targets.private_rules)

    def push_group_rules(self) -> dict[ConversationRef, BiliTargetRule]:
        default_rule = _default_rule(self.config)
        configured = self.configured_group_rules()
        return {
            conversation: configured.get(conversation, default_rule)
            for conversation in self.features.conversations_for_feature("bili_push")
        }

    def push_user_rules(self) -> dict[ConversationRef, BiliTargetRule]:
        default_rule = _default_rule(self.config)
        configured = self.configured_user_rules()
        return {
            conversation: configured.get(conversation, default_rule)
            for conversation in (
                private_conversation_for_actor(actor)
                for actor in self.features.actors_for_feature("bili_push")
            )
        }

    def monitored_uids(self) -> list[int]:
        uids = set(_default_rule(self.config).uids)
        for rule in [
            *self.configured_group_rules().values(),
            *self.configured_user_rules().values(),
        ]:
            uids.update(rule.uids)
        return _unique_ints(sorted(uids))

    def query_uids(
        self,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> list[int]:
        """Resolve readable Bilibili accounts for one platform conversation.

        Current TOML account-target mappings are resolved to typed OneBot
        references at the feature-configuration boundary. Other platforms
        fail closed until they provide their own configuration adapter.
        """

        private_superuser_query = (
            conversation.kind == "private" and self.features.is_actor_superuser(actor)
        )
        if not (
            self.features.is_feature_allowed(actor, conversation, "bili_query")
            or private_superuser_query
        ):
            return []

        if conversation.kind == "group":
            return self._query_group_uids(conversation)
        if conversation.kind == "private":
            return self._query_private_uids(actor)
        return []

    def _query_group_uids(self, conversation: ConversationRef) -> list[int]:
        rule = self.configured_group_rules().get(conversation)
        return sorted((rule or _default_rule(self.config)).uids)

    def _query_private_uids(self, actor: ActorRef) -> list[int]:
        rule = self.configured_user_rules().get(private_conversation_for_actor(actor))
        if rule is not None:
            return sorted(rule.uids)
        return self.monitored_uids() if self.features.is_actor_superuser(actor) else []

    def can_conversation_query_history(self, conversation: ConversationRef) -> bool:
        """Whether recipients of a push can use the ``动态`` history command."""

        if conversation.kind == "group":
            return self.features.conversation_has_feature(conversation, "bili_query")
        if conversation.kind == "private":
            return self.features.is_actor_feature_allowed(
                ActorRef(conversation.platform, conversation.id),
                "bili_query",
            )
        return False

    def _rules_for_conversation(
        self,
        conversation: ConversationRef,
    ) -> dict[ConversationRef, BiliTargetRule] | None:
        if conversation.kind == "group":
            return self.push_group_rules()
        if conversation.kind == "private":
            return self.push_user_rules()
        return None

    def mode_for_uid(
        self,
        conversation: ConversationRef,
        uid: int,
    ) -> BiliPushMode | None:
        rules = self._rules_for_conversation(conversation)
        if rules is None:
            return None
        rule = rules.get(conversation)
        if rule is None or uid not in rule.uids:
            return None
        return (
            self.preferences.get_mode(conversation, uid)
            or rule.mode_for_uid(uid)
            or rule.default_mode
        )

    def mode_display_for_uid(
        self,
        conversation: ConversationRef,
        uid: int,
    ) -> str | None:
        rule = self.target_rule(conversation)
        if rule is None or uid not in rule.uids:
            return None
        runtime_mode = self.preferences.get_mode(conversation, uid)
        if runtime_mode is not None:
            return f"已自定义（{push_mode_label(runtime_mode)}）"
        configured_mode = rule.configured_mode_for_uid(uid)
        if configured_mode is not None:
            return f"配置（{push_mode_label(configured_mode)}）"
        return f"默认（{push_mode_label(rule.default_mode)}）"

    def target_rule(
        self,
        conversation: ConversationRef,
    ) -> BiliTargetRule | None:
        rules = self._rules_for_conversation(conversation)
        return None if rules is None else rules.get(conversation)

    def subscription_options(
        self,
        conversation: ConversationRef,
    ) -> list[PushSubscriptionOption]:
        rule = self.target_rule(conversation)
        if rule is None:
            return []

        unsubscribed = self.unsubscribe_store.unsubscribed_keys(conversation)
        return [
            PushSubscriptionOption(
                key=(key := bili_push_subscription_key(uid)),
                label=self._subscription_label(uid),
                feature="bili_push",
                unsubscribed=key in unsubscribed,
                submenu_key=(
                    bili_category_submenu_key(uid)
                    if self.category_config_for_uid(uid) is not None
                    else None
                ),
            )
            for uid in sorted(rule.uids)
        ]

    def subscription_submenu(
        self,
        conversation: ConversationRef,
        option: PushSubscriptionOption,
        *,
        read_only: bool,
    ) -> tuple[list[PushSubscriptionOption], str] | None:
        if option.submenu_key is None:
            return None
        uid = _subscription_uid(option.submenu_key)
        config = None if uid is None else self.category_config_for_uid(uid)
        if config is None:
            return None
        options = [
            PushSubscriptionOption(
                key=bili_push_subscription_key(uid),
                label="全部动态",
                feature="bili_push",
                unsubscribed=self.unsubscribe_store.is_unsubscribed(
                    conversation,
                    bili_push_subscription_key(uid),
                ),
            ),
            *[
                PushSubscriptionOption(
                    key=bili_category_subscription_key(uid, category),
                    label=definition.label,
                    feature="bili_push",
                    unsubscribed=self._category_muted(conversation, uid, category),
                )
                for category, definition in config.categories.items()
            ],
        ]
        return options, build_push_subscription_menu(
            title=f"📺【{config.label} 分类订阅】",
            options=options,
            read_only=read_only,
        )

    def toggle_subscription(
        self,
        conversation: ConversationRef,
        option: PushSubscriptionOption,
    ) -> str | None:
        parsed = _category_subscription(option.key)
        if parsed is None:
            return None
        uid, category = parsed
        config = self.category_config_for_uid(uid)
        if config is None or category not in config.categories:
            return None
        muted = not self._category_muted(conversation, uid, category)
        self.preferences.set_category_muted(
            conversation,
            uid,
            category,
            muted=muted,
        )
        action = "退订" if muted else "恢复订阅"
        return f"已{action}：{config.categories[category].label}。"

    async def prepare_account_names(
        self,
        conversation: ConversationRef,
    ) -> str | None:
        rule = self.target_rule(conversation)
        if rule is None:
            return None
        if await self.account_names.refresh(rule.uids):
            return None
        return ACCOUNT_NAMES_UNAVAILABLE

    async def account_summary(
        self,
        conversation: ConversationRef,
    ) -> str:
        lines = ["📺【B站账号】"]
        rule = self.target_rule(conversation)
        if rule is None:
            lines.append("当前会话未开启 B站推送。")
            return "\n".join(lines)
        if error := await self.prepare_account_names(conversation):
            lines.append(error)
            return "\n".join(lines)

        unsubscribed = self.unsubscribe_store.unsubscribed_keys(conversation)
        scope = "当前群" if conversation.kind == "group" else "当前私聊"
        lines.append(f"{scope}订阅：")
        for uid in sorted(rule.uids):
            mode_display = self.mode_display_for_uid(conversation, uid)
            td_text = (
                "，已 TD" if bili_push_subscription_key(uid) in unsubscribed else ""
            )
            account_name = self.account_names.name_for_uid(uid)
            if account_name is None:
                return "\n".join([*lines, ACCOUNT_NAMES_UNAVAILABLE])
            lines.append(f"- {account_name}：{mode_display}{td_text}")
        manager = "群主/管理员可发送" if conversation.kind == "group" else "可发送"
        lines.append(f"{manager}：B站推送模式 <账号别名|公开昵称|UID> <内容|链接|默认>")
        return "\n".join(lines)

    async def update_push_mode(  # noqa: PLR0911 - command errors return directly
        self,
        conversation: ConversationRef,
        account_ref: str,
        raw_mode: str,
    ) -> str:
        if not account_ref.strip() or not raw_mode.strip():
            return _push_mode_usage()

        rule = self.target_rule(conversation)
        if rule is None:
            return "❌ 当前会话未开启 B站推送。"

        configured_aliases = configured_account_alias_lookup(
            self.config,
            rule.aliases,
        )
        uid = configured_aliases.resolve_alias(account_ref).unique_value
        if uid is None:
            uid = (
                self.account_names.public_name_alias_lookup(
                    rule.uids,
                )
                .resolve_alias(account_ref)
                .unique_value
            )
        if uid is None:
            if error := await self.prepare_account_names(conversation):
                return error
            uid = (
                self.account_names.public_name_alias_lookup(
                    rule.uids,
                )
                .resolve_alias(account_ref)
                .unique_value
            )
        if uid is None or self.mode_for_uid(conversation, uid) is None:
            return "❌ 当前会话没有订阅该 B站账号。\n可发送“B站账号”查看当前会话订阅。"

        try:
            mode = normalize_push_mode_text(raw_mode)
        except ValueError:
            return _push_mode_usage()

        if mode is None:
            self.preferences.clear_mode(conversation, uid)
        else:
            self.preferences.set_mode(conversation, uid, mode)

        effective_display = self.mode_display_for_uid(conversation, uid)
        scope = "当前群" if conversation.kind == "group" else "当前私聊"
        await self.account_names.refresh([uid])
        account_name = self.account_names.name_for_uid(uid)
        account_text = f"“{account_name}”" if account_name else ""
        if mode is None:
            return (
                f"已恢复{scope} B站账号{account_text}的默认推送方式。\n"
                f"当前生效模式：{effective_display}。"
            )
        return (
            f"已设置{scope} B站账号{account_text}的推送模式："
            f"{push_mode_label(mode)}。\n"
            f"当前生效模式：{effective_display}。"
        )

    def push_targets_for_uid(self, uid: int) -> BiliPushTargets:
        return self.push_targets_for_dynamic(uid)

    def push_targets_for_dynamic(
        self,
        uid: int,
        *,
        categories: tuple[str, ...] = (),
    ) -> BiliPushTargets:
        full_group_conversations: list[ConversationRef] = []
        link_group_conversations: list[ConversationRef] = []
        for conversation in self.push_group_rules():
            mode = self.mode_for_uid(conversation, uid)
            if not self._categories_allowed(conversation, uid, categories):
                continue
            if mode == "full":
                full_group_conversations.append(conversation)
            elif mode == "link":
                link_group_conversations.append(conversation)

        full_private_conversations: list[ConversationRef] = []
        link_private_conversations: list[ConversationRef] = []
        for conversation in self.push_user_rules():
            mode = self.mode_for_uid(conversation, uid)
            if not self._categories_allowed(conversation, uid, categories):
                continue
            if mode == "full":
                full_private_conversations.append(conversation)
            elif mode == "link":
                link_private_conversations.append(conversation)

        return BiliPushTargets(
            full_group_conversations=list(dict.fromkeys(full_group_conversations)),
            link_group_conversations=list(dict.fromkeys(link_group_conversations)),
            full_private_conversations=list(dict.fromkeys(full_private_conversations)),
            link_private_conversations=list(dict.fromkeys(link_private_conversations)),
        )

    def category_config_for_uid(
        self,
        uid: int,
    ) -> BiliAccountCategorySubscriptionConfig | None:
        """Return category rules for one configured account, if any."""
        if not self.config.category_subscriptions.enabled:
            return None
        for (
            alias,
            category_config,
        ) in self.config.category_subscriptions.accounts.items():
            account = self.config.accounts.get(alias)
            if account is not None and account.uid == uid:
                return category_config
        return None

    def suppress_patterns_for_uid(self, uid: int) -> list[str]:
        """Category-managed accounts decide delivery per category, not globally."""

        return [] if self.category_config_for_uid(uid) is not None else list(
            self.config.filters.suppress_push_patterns
        )

    def _categories_allowed(
        self,
        conversation: ConversationRef,
        uid: int,
        categories: tuple[str, ...],
    ) -> bool:
        config = self.category_config_for_uid(uid)
        if config is None or not categories:
            return True
        return any(
            not self._category_muted(conversation, uid, category)
            for category in categories
        )

    def _category_muted(
        self,
        conversation: ConversationRef,
        uid: int,
        category: str,
    ) -> bool:
        configured = self.category_config_for_uid(uid)
        if configured is None or category not in configured.categories:
            return False
        stored = self.preferences.category_muted(conversation, uid, category)
        if stored is not None:
            return stored
        return category in configured.default_muted_categories

    def _subscription_label(self, uid: int) -> str:
        configured = self.category_config_for_uid(uid)
        label = (
            configured.label
            if configured is not None
            else self.account_names.name_for_uid(uid)
        )
        return bili_push_subscription_label(uid, label)


def _push_mode_usage() -> str:
    return (
        "用法：B站推送模式 <账号别名|公开昵称|UID> <内容|链接|默认>\n"
        "例：B站推送模式 赛尔号官号 链接\n"
        "例：B站推送模式 赛尔号官号 内容\n"
        "例：B站推送模式 赛尔号官号 默认"
    )


def _subscription_uid(key: str) -> int | None:
    prefix = "bili_category:"
    if not key.startswith(prefix) or ":" in key.removeprefix(prefix):
        return None
    try:
        return int(key.removeprefix(prefix))
    except ValueError:
        return None


def _category_subscription(key: str) -> tuple[int, str] | None:
    prefix = "bili_category:"
    if not key.startswith(prefix):
        return None
    raw_uid, separator, category = key.removeprefix(prefix).partition(":")
    if not separator or not category:
        return None
    try:
        return int(raw_uid), category
    except ValueError:
        return None
