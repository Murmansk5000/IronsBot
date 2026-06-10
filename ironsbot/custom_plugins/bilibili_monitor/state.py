import asyncio
from dataclasses import dataclass

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ironsbot.custom_plugins.feature_policy import (
    group_has_feature,
    is_private_feature_allowed,
    is_superuser,
    resolve_group_refs,
    resolve_user_refs,
)

from .config import BiliPushMode, BiliPushTargetConfig, plugin_config


def _unique_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(item for item in values if item > 0))


@dataclass(frozen=True, slots=True)
class BiliTargetRule:
    uids: frozenset[int]
    mode: BiliPushMode
    uid_modes: dict[int, BiliPushMode]

    def mode_for_uid(self, uid: int) -> BiliPushMode | None:
        if uid not in self.uids:
            return None
        return self.uid_modes.get(uid, self.mode)


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


BILI_CONFIG = plugin_config.bili_config


def _target_uids(target_config: BiliPushTargetConfig) -> frozenset[int]:
    uids = set(target_config.uids)
    uids.update(target_config.uid_modes)
    if not uids:
        uids.update(BILI_CONFIG.uids)
    return frozenset(uid for uid in uids if uid > 0)


def _resolve_rule(target_config: BiliPushTargetConfig) -> BiliTargetRule:
    return BiliTargetRule(
        uids=_target_uids(target_config),
        mode=target_config.mode or BILI_CONFIG.push.default_mode,
        uid_modes=dict(target_config.uid_modes),
    )


def _merge_rules(old_rule: BiliTargetRule, new_rule: BiliTargetRule) -> BiliTargetRule:
    return BiliTargetRule(
        uids=old_rule.uids | new_rule.uids,
        mode=new_rule.mode,
        uid_modes={**old_rule.uid_modes, **new_rule.uid_modes},
    )


def _resolve_group_rules() -> dict[int, BiliTargetRule]:
    rules: dict[int, BiliTargetRule] = {}
    for ref, target_config in BILI_CONFIG.push.groups.items():
        rule = _resolve_rule(target_config)
        for group_id in resolve_group_refs([ref]):
            rules[group_id] = (
                _merge_rules(rules[group_id], rule)
                if group_id in rules
                else rule
            )
    return rules


def _resolve_user_rules() -> dict[int, BiliTargetRule]:
    rules: dict[int, BiliTargetRule] = {}
    for ref, target_config in BILI_CONFIG.push.users.items():
        rule = _resolve_rule(target_config)
        for user_id in resolve_user_refs([ref]):
            rules[user_id] = (
                _merge_rules(rules[user_id], rule)
                if user_id in rules
                else rule
            )
    return rules


CONFIGURED_GROUP_RULES = _resolve_group_rules()
CONFIGURED_USER_RULES = _resolve_user_rules()

PUSH_GROUP_RULES = {
    group_id: rule
    for group_id, rule in CONFIGURED_GROUP_RULES.items()
    if group_has_feature(group_id, "bili_push")
}
PUSH_USER_RULES = {
    user_id: rule
    for user_id, rule in CONFIGURED_USER_RULES.items()
    if is_private_feature_allowed(user_id, "bili_push")
}

TARGET_GROUP_IDS = _unique_ints(list(PUSH_GROUP_RULES))
TARGET_USER_IDS = _unique_ints(list(PUSH_USER_RULES))


def _configured_monitor_uids() -> list[int]:
    uids = set(BILI_CONFIG.uids)
    for rule in [*CONFIGURED_GROUP_RULES.values(), *CONFIGURED_USER_RULES.values()]:
        uids.update(rule.uids)
    return _unique_ints(sorted(uids))


MONITORED_UIDS = _configured_monitor_uids()

BILI_STORAGE_DIR = BILI_CONFIG.storage.data_dir
BILI_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

DYNAMIC_HISTORY_DB_FILE = BILI_STORAGE_DIR / "dynamic_history.sqlite"
COOKIE_CACHE_FILE = BILI_STORAGE_DIR / "bili_cookie_cache.txt"

AUTH_INVALID_CODES = {-101, -401, -403, 412}
LOGIN_NOTICE_COOLDOWN_SECONDS = 5 * 60
LOGIN_QR_EXPIRE_SECONDS = 180
LOGIN_COOKIE_KEYS = {
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "sid",
}

check_lock = asyncio.Lock()


def query_uids_for_event(event: MessageEvent) -> list[int]:
    if isinstance(event, GroupMessageEvent):
        rule = CONFIGURED_GROUP_RULES.get(event.group_id)
        return sorted(rule.uids) if rule is not None else []

    if isinstance(event, PrivateMessageEvent):
        rule = CONFIGURED_USER_RULES.get(event.user_id)
        if rule is not None:
            return sorted(rule.uids)
        if is_superuser(event.user_id):
            return MONITORED_UIDS

    return []


def push_targets_for_uid(uid: int) -> BiliPushTargets:
    full_group_ids: list[int] = []
    link_group_ids: list[int] = []
    for group_id, rule in PUSH_GROUP_RULES.items():
        mode = rule.mode_for_uid(uid)
        if mode == "full":
            full_group_ids.append(group_id)
        elif mode == "link":
            link_group_ids.append(group_id)

    full_user_ids: list[int] = []
    link_user_ids: list[int] = []
    for user_id, rule in PUSH_USER_RULES.items():
        mode = rule.mode_for_uid(uid)
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
