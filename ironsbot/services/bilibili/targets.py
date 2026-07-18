from dataclasses import dataclass, field

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ironsbot.config.models.bilibili import (
    BiliConfig,
    BiliPushMode,
    BiliPushTargetConfig,
)
from ironsbot.services.bilibili.accounts import account_uid
from ironsbot.services.bilibili.preferences import (
    BiliPushPreferenceStore,
    bili_push_subscription_key,
    bili_push_subscription_label,
)
from ironsbot.shared.features import FeatureService
from ironsbot.shared.messaging.push_subscription_models import (
    PushSubscriptionOption,
    PushTargetType,
)
from ironsbot.shared.messaging.push_subscription_store import (
    PushUnsubscribeStore,
)


def _unique_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(item for item in values if item > 0))


@dataclass(frozen=True, slots=True)
class BiliTargetRule:
    accounts: frozenset[str]
    uids: frozenset[int]
    uid_accounts: dict[int, str]
    mode: BiliPushMode
    modes: dict[str, BiliPushMode]
    account_nicknames: dict[str, str] = field(default_factory=dict)

    def mode_for_uid(self, uid: int) -> BiliPushMode | None:
        if uid not in self.uids:
            return None
        account = self.account_for_uid(uid)
        if account is None:
            return self.mode
        return self.modes.get(account, self.mode)

    def account_for_uid(self, uid: int) -> str | None:
        return self.uid_accounts.get(uid)

    def label_for_uid(self, uid: int) -> str:
        account = self.account_for_uid(uid)
        if account is None:
            return str(int(uid))
        nickname = self.account_nicknames.get(account)
        if nickname:
            return f"{nickname}\uff08{int(uid)}\uff09"
        return f"{account}\uff08{int(uid)}\uff09"


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


def _target_accounts(
    target_config: BiliPushTargetConfig,
    config: BiliConfig,
) -> frozenset[str]:
    return frozenset(
        [
            *config.push.accounts,
            *target_config.accounts,
        ]
    )


def _resolve_rule(
    target_config: BiliPushTargetConfig,
    config: BiliConfig,
) -> BiliTargetRule:
    accounts = _target_accounts(target_config, config)
    account_to_uid = {
        account: config.accounts[account]
        for account in accounts
    }
    uid_accounts = {
        uid: account
        for account, uid in account_to_uid.items()
        if uid > 0
    }
    account_nicknames = {
        account: nickname
        for account in accounts
        if (nickname := config.account_nicknames.get(account))
    }
    return BiliTargetRule(
        accounts=accounts,
        uids=frozenset(uid for uid in account_to_uid.values() if uid > 0),
        uid_accounts=uid_accounts,
        account_nicknames=account_nicknames,
        mode=target_config.mode or config.push.mode,
        modes={**config.push.modes, **target_config.modes},
    )


def _default_rule(config: BiliConfig) -> BiliTargetRule:
    return _resolve_rule(BiliPushTargetConfig(), config)


def _merge_rules(old_rule: BiliTargetRule, new_rule: BiliTargetRule) -> BiliTargetRule:
    return BiliTargetRule(
        accounts=old_rule.accounts | new_rule.accounts,
        uids=old_rule.uids | new_rule.uids,
        uid_accounts={**old_rule.uid_accounts, **new_rule.uid_accounts},
        account_nicknames={
            **old_rule.account_nicknames,
            **new_rule.account_nicknames,
        },
        mode=new_rule.mode,
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
                _merge_rules(rules[group_id], rule)
                if group_id in rules
                else rule
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
                _merge_rules(rules[user_id], rule)
                if user_id in rules
                else rule
            )
    return rules


@dataclass(frozen=True, slots=True)
class BiliTargetService:
    config: BiliConfig
    features: FeatureService
    preferences: BiliPushPreferenceStore
    unsubscribe_store: PushUnsubscribeStore

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

    def query_uids_for_event(self, event: MessageEvent) -> list[int]:
        if isinstance(event, GroupMessageEvent):
            return self.query_uids_for_group(event.user_id, event.group_id)
        if isinstance(event, PrivateMessageEvent):
            return self.query_uids_for_private(event.user_id)
        return []

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
            or rule.mode
        )

    def mode_for_account(
        self,
        target_type: PushTargetType,
        target_id: int,
        account: str,
    ) -> BiliPushMode | None:
        uid = account_uid(account, self.config)
        return (
            self.mode_for_uid(target_type, target_id, uid)
            if uid is not None
            else None
        )

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
            PushSubscriptionOption(
                key=(key := bili_push_subscription_key(uid)),
                label=bili_push_subscription_label(uid, rule.label_for_uid(uid)),
                feature="bili_push",
                unsubscribed=key in unsubscribed,
            )
            for uid in sorted(rule.uids)
        ]

    def push_targets_for_uid(self, uid: int) -> BiliPushTargets:
        full_group_ids: list[int] = []
        link_group_ids: list[int] = []
        for group_id in self.push_group_rules():
            mode = self.mode_for_uid("group", group_id, uid)
            if mode == "full":
                full_group_ids.append(group_id)
            elif mode == "link":
                link_group_ids.append(group_id)

        full_user_ids: list[int] = []
        link_user_ids: list[int] = []
        for user_id in self.push_user_rules():
            mode = self.mode_for_uid("private", user_id, uid)
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
