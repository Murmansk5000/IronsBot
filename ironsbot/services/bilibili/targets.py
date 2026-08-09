from dataclasses import dataclass, field

from ironsbot.core.bilibili import (
    SEER_DYNAMIC_CATEGORIES,
    BiliConfig,
    BiliPushMode,
    BiliPushTargetConfig,
    SeerDynamicCategory,
)
from ironsbot.core.features import FeatureService
from ironsbot.core.messaging import MessageTarget
from ironsbot.services.bilibili.accounts import (
    BiliAccountNames,
    account_uid,
    normalize_account_alias,
)
from ironsbot.services.bilibili.categories import (
    SEER_CATEGORY_LABELS,
    classify_seer_dynamic,
    parse_seer_category_option_key,
    seer_category_option_key,
    seer_category_submenu_key,
)
from ironsbot.services.bilibili.preferences import (
    BiliPushPreferenceStore,
    bili_push_subscription_key,
    bili_push_subscription_label,
    normalize_push_mode_text,
    push_mode_label,
)
from ironsbot.services.messaging.subscriptions import (
    PushSubscriptionOption,
    PushSubscriptionRepository,
    PushTargetType,
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
    full_group_ids: list[int]
    link_group_ids: list[int]
    full_user_ids: list[int]
    link_user_ids: list[int]

    @property
    def has_targets(self) -> bool:
        return any(
            (
                self.full_group_ids,
                self.link_group_ids,
                self.full_user_ids,
                self.link_user_ids,
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


def _resolve_rule(
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
    return _resolve_rule(BiliPushTargetConfig(), config)


def _merge_rules(old_rule: BiliTargetRule, new_rule: BiliTargetRule) -> BiliTargetRule:
    return BiliTargetRule(
        aliases=old_rule.aliases | new_rule.aliases,
        uids=old_rule.uids | new_rule.uids,
        default_mode=new_rule.default_mode,
        target_mode=new_rule.target_mode,
        modes={**old_rule.modes, **new_rule.modes},
    )


def _resolve_group_rules(
    features: FeatureService,
    config: BiliConfig,
) -> dict[int, BiliTargetRule]:
    rules: dict[int, BiliTargetRule] = {}
    for ref, target_config in config.push.groups.items():
        rule = _resolve_rule(target_config, config)
        for group_id in features.resolve_group_refs([ref]):
            rules[group_id] = (
                _merge_rules(rules[group_id], rule) if group_id in rules else rule
            )
    return rules


def _resolve_user_rules(
    features: FeatureService,
    config: BiliConfig,
) -> dict[int, BiliTargetRule]:
    rules: dict[int, BiliTargetRule] = {}
    for ref, target_config in config.push.users.items():
        rule = _resolve_rule(target_config, config)
        for user_id in features.resolve_user_refs([ref]):
            rules[user_id] = (
                _merge_rules(rules[user_id], rule) if user_id in rules else rule
            )
    return rules


@dataclass(frozen=True, slots=True)
class BiliTargetService:
    config: BiliConfig
    features: FeatureService
    preferences: BiliPushPreferenceStore
    unsubscribe_store: PushSubscriptionRepository
    account_names: BiliAccountNames = field(default_factory=BiliAccountNames)

    def configured_group_rules(self) -> dict[int, BiliTargetRule]:
        return _resolve_group_rules(self.features, self.config)

    def configured_user_rules(self) -> dict[int, BiliTargetRule]:
        return _resolve_user_rules(self.features, self.config)

    def push_group_rules(self) -> dict[int, BiliTargetRule]:
        default_rule = _default_rule(self.config)
        configured = self.configured_group_rules()
        return {
            group_id: configured.get(group_id, default_rule)
            for group_id in self.features.groups_for_feature("bili_push")
        }

    def push_user_rules(self) -> dict[int, BiliTargetRule]:
        default_rule = _default_rule(self.config)
        configured = self.configured_user_rules()
        return {
            user_id: configured.get(user_id, default_rule)
            for user_id in self.features.users_for_feature("bili_push")
        }

    def monitored_uids(self) -> list[int]:
        uids = set(_default_rule(self.config).uids)
        for rule in [
            *self.configured_group_rules().values(),
            *self.configured_user_rules().values(),
        ]:
            uids.update(rule.uids)
        return _unique_ints(sorted(uids))

    def query_uids_for_group(self, user_id: int, group_id: int) -> list[int]:
        if not self.features.is_group_feature_allowed(
            user_id,
            group_id,
            "bili_query",
        ):
            return []
        rule = self.configured_group_rules().get(group_id)
        return sorted((rule or _default_rule(self.config)).uids)

    def query_uids_for_private(self, user_id: int) -> list[int]:
        rule = self.configured_user_rules().get(user_id)
        if rule is not None:
            if self.features.is_private_feature_allowed(user_id, "bili_query"):
                return sorted(rule.uids)
            return []
        return self.monitored_uids() if self.features.is_superuser(user_id) else []

    def can_target_query_history(self, target: MessageTarget) -> bool:
        """Whether recipients of a push can use the ``动态`` history command."""

        if target.target_type == "group":
            return self.features.group_has_feature(target.target_id, "bili_query")
        return self.features.is_private_feature_allowed(
            target.target_id,
            "bili_query",
        )

    def _rules(self, target_type: PushTargetType) -> dict[int, BiliTargetRule]:
        return (
            self.push_group_rules()
            if target_type == "group"
            else self.push_user_rules()
        )

    def mode_for_uid(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
    ) -> BiliPushMode | None:
        rule = self._rules(target_type).get(target_id)
        if rule is None or uid not in rule.uids:
            return None
        return (
            self.preferences.get_mode(target_type, target_id, uid)
            or rule.mode_for_uid(uid)
            or rule.default_mode
        )

    def mode_display_for_uid(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
    ) -> str | None:
        rule = self._rules(target_type).get(target_id)
        if rule is None or uid not in rule.uids:
            return None
        runtime_mode = self.preferences.get_mode(target_type, target_id, uid)
        if runtime_mode is not None:
            return f"已自定义（{push_mode_label(runtime_mode)}）"
        configured_mode = rule.configured_mode_for_uid(uid)
        if configured_mode is not None:
            return f"配置（{push_mode_label(configured_mode)}）"
        return f"默认（{push_mode_label(rule.default_mode)}）"

    def target_rule(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> BiliTargetRule | None:
        return self._rules(target_type).get(target_id)

    def subscription_options(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> list[PushSubscriptionOption]:
        rule = self._rules(target_type).get(target_id)
        if rule is None:
            return []

        unsubscribed = self.unsubscribe_store.target_unsubscribed_keys(
            target_type,
            target_id,
        )
        return [
            self._subscription_option(uid, unsubscribed) for uid in sorted(rule.uids)
        ]

    def _subscription_option(
        self,
        uid: int,
        unsubscribed: set[str],
    ) -> PushSubscriptionOption:
        key = bili_push_subscription_key(uid)
        if self.is_seer_category_uid(uid):
            return PushSubscriptionOption(
                key=key,
                label="赛尔号 B站动态设置",
                feature="bili_push",
                unsubscribed=key in unsubscribed,
                submenu_key=seer_category_submenu_key(uid),
            )
        return PushSubscriptionOption(
            key=key,
            label=bili_push_subscription_label(
                uid,
                self.account_names.name_for_uid(uid),
            ),
            feature="bili_push",
            unsubscribed=key in unsubscribed,
        )

    def subscription_submenu(
        self,
        target_type: PushTargetType,
        target_id: int,
        option: PushSubscriptionOption,
        *,
        read_only: bool = False,
    ) -> tuple[list[PushSubscriptionOption], str] | None:
        uid = self._seer_category_uid()
        if (
            uid is None
            or option.submenu_key != seer_category_submenu_key(uid)
            or self.mode_for_uid(target_type, target_id, uid) is None
        ):
            return None

        unsubscribed = self.unsubscribe_store.is_target_unsubscribed(
            target_type,
            target_id,
            bili_push_subscription_key(uid),
        )
        options = [
            PushSubscriptionOption(
                key=bili_push_subscription_key(uid),
                label="赛尔号动态总开关",
                feature="bili_push",
                unsubscribed=unsubscribed,
            ),
            *(
                PushSubscriptionOption(
                    key=seer_category_option_key(uid, category),
                    label=SEER_CATEGORY_LABELS[category],
                    feature="bili_push",
                    unsubscribed=self.category_muted(
                        target_type,
                        target_id,
                        uid,
                        category,
                    ),
                )
                for category in SEER_DYNAMIC_CATEGORIES
            ),
        ]
        scope = "本群" if target_type == "group" else "当前私聊"
        title = (
            f"{scope}赛尔号动态订阅状态："
            if read_only
            else f"请选择要切换的{scope}赛尔号动态订阅："
        )
        lines = [title]
        for index, child in enumerate(options, start=1):
            state = "❌" if child.unsubscribed else "✅"
            lines.append(f"{index}. {state} {child.label}")
        lines.append("\n总开关为 ❌ 时，本群不接收任何赛尔号动态；分类开关设置会保留。")
        lines.append("✅ 已订阅 · ❌ 已 TD，输入序号切换；输入 0 返回推送订阅")
        return options, "\n".join(lines)

    def toggle_subscription_option(
        self,
        target_type: PushTargetType,
        target_id: int,
        option: PushSubscriptionOption,
    ) -> str | None:
        parsed = parse_seer_category_option_key(option.key)
        if parsed is None:
            return None
        uid, category = parsed
        if uid != self._seer_category_uid():
            return None
        muted = not self.category_muted(target_type, target_id, uid, category)
        self.preferences.set_category_muted(
            target_type,
            target_id,
            uid,
            category,
            muted=muted,
        )
        action = "已 TD" if muted else "已恢复订阅"
        return f"{action}：赛尔号动态 - {SEER_CATEGORY_LABELS[category]}。"

    def _seer_category_uid(self) -> int | None:
        categories = self.config.seer_categories
        account = self.config.accounts.get(categories.account)
        return account.uid if categories.enabled and account is not None else None

    def is_seer_category_uid(self, uid: int) -> bool:
        return uid == self._seer_category_uid()

    def classify_dynamic(
        self,
        uid: int,
        item: dict[str, object],
        pub_ts: int,
    ) -> tuple[SeerDynamicCategory, ...]:
        if not self.is_seer_category_uid(uid):
            return ()
        return classify_seer_dynamic(
            item,
            pub_ts=pub_ts,
            config=self.config.seer_categories,
        )

    def dynamic_link_tag(
        self,
        uid: int,
        categories: tuple[SeerDynamicCategory, ...],
    ) -> str | None:
        if not self.is_seer_category_uid(uid) or not categories:
            return None
        return "🏷️ 标签：" + " / ".join(
            SEER_CATEGORY_LABELS[category] for category in categories
        )

    def category_muted(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
        category: SeerDynamicCategory,
    ) -> bool:
        stored = self.preferences.category_muted(
            target_type,
            target_id,
            uid,
            category,
        )
        return (
            category in self.config.seer_categories.default_muted_categories
            if stored is None
            else stored
        )

    def _category_allowed(
        self,
        target_type: PushTargetType,
        target_id: int,
        uid: int,
        categories: tuple[SeerDynamicCategory, ...],
    ) -> bool:
        return not categories or any(
            not self.category_muted(target_type, target_id, uid, category)
            for category in categories
        )

    async def prepare_account_names(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> str | None:
        rule = self.target_rule(target_type, target_id)
        if rule is None:
            return None
        if await self.account_names.refresh(rule.uids):
            return None
        return ACCOUNT_NAMES_UNAVAILABLE

    async def account_summary(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> str:
        lines = ["📺【B站账号】"]
        rule = self.target_rule(target_type, target_id)
        if rule is None:
            lines.append("当前会话未开启 B站推送。")
            return "\n".join(lines)
        if error := await self.prepare_account_names(target_type, target_id):
            lines.append(error)
            return "\n".join(lines)

        unsubscribed = self.unsubscribe_store.target_unsubscribed_keys(
            target_type,
            target_id,
        )
        scope = "当前群" if target_type == "group" else "当前私聊"
        lines.append(f"{scope}订阅：")
        for uid in sorted(rule.uids):
            mode_display = self.mode_display_for_uid(target_type, target_id, uid)
            td_text = (
                "，已 TD" if bili_push_subscription_key(uid) in unsubscribed else ""
            )
            account_name = self.account_names.name_for_uid(uid)
            if account_name is None:
                return "\n".join([*lines, ACCOUNT_NAMES_UNAVAILABLE])
            lines.append(f"- {account_name}：{mode_display}{td_text}")
        manager = "群主/管理员可发送" if target_type == "group" else "可发送"
        lines.append(f"{manager}：B站推送模式 <账号别名|公开昵称|UID> <内容|链接|默认>")
        return "\n".join(lines)

    async def update_push_mode(  # noqa: PLR0911 - command errors return directly
        self,
        target_type: PushTargetType,
        target_id: int,
        account_ref: str,
        raw_mode: str,
    ) -> str:
        if not account_ref.strip() or not raw_mode.strip():
            return _push_mode_usage()

        rule = self.target_rule(target_type, target_id)
        if rule is None:
            return "❌ 当前会话未开启 B站推送。"

        alias = normalize_account_alias(account_ref)
        uid = account_uid(alias, self.config) if alias in rule.aliases else None
        if uid is None:
            uid = self.account_names.resolve(account_ref, rule.uids)
        if uid is None:
            if error := await self.prepare_account_names(
                target_type,
                target_id,
            ):
                return error
            uid = self.account_names.resolve(account_ref, rule.uids)
        if uid is None or self.mode_for_uid(target_type, target_id, uid) is None:
            return "❌ 当前会话没有订阅该 B站账号。\n可发送“B站账号”查看当前会话订阅。"

        try:
            mode = normalize_push_mode_text(raw_mode)
        except ValueError:
            return _push_mode_usage()

        if mode is None:
            self.preferences.clear_mode(target_type, target_id, uid)
        else:
            self.preferences.set_mode(target_type, target_id, uid, mode)

        effective_display = self.mode_display_for_uid(target_type, target_id, uid)
        scope = "当前群" if target_type == "group" else "当前私聊"
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

    def push_targets_for_uid(
        self,
        uid: int,
        *,
        categories: tuple[SeerDynamicCategory, ...] = (),
    ) -> BiliPushTargets:
        full_group_ids: list[int] = []
        link_group_ids: list[int] = []
        for group_id in self.push_group_rules():
            mode = self.mode_for_uid("group", group_id, uid)
            if not self._category_allowed("group", group_id, uid, categories):
                continue
            if mode == "full":
                full_group_ids.append(group_id)
            elif mode == "link":
                link_group_ids.append(group_id)

        full_user_ids: list[int] = []
        link_user_ids: list[int] = []
        for user_id in self.push_user_rules():
            mode = self.mode_for_uid("private", user_id, uid)
            if not self._category_allowed("private", user_id, uid, categories):
                continue
            if mode == "full":
                full_user_ids.append(user_id)
            elif mode == "link":
                link_user_ids.append(user_id)

        return BiliPushTargets(
            full_group_ids=_unique_ints(full_group_ids),
            link_group_ids=_unique_ints(link_group_ids),
            full_user_ids=_unique_ints(full_user_ids),
            link_user_ids=_unique_ints(link_user_ids),
        )


def _push_mode_usage() -> str:
    return (
        "用法：B站推送模式 <账号别名|公开昵称|UID> <内容|链接|默认>\n"
        "例：B站推送模式 赛尔号官号 链接\n"
        "例：B站推送模式 赛尔号官号 内容\n"
        "例：B站推送模式 赛尔号官号 默认"
    )
