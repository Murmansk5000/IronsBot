from collections.abc import Mapping
from dataclasses import dataclass

from ironsbot.core.bilibili import BiliPushMode
from ironsbot.core.platform import ConversationRef


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


@dataclass(frozen=True, slots=True)
class BiliConfiguredTargets:
    """Platform-resolved push-target rules consumed by Bili services."""

    group_rules: Mapping[ConversationRef, BiliTargetRule]
    private_rules: Mapping[ConversationRef, BiliTargetRule]
