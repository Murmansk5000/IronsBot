# SPDX-License-Identifier: GPL-3.0-or-later
"""Text alternatives from the same detached facts used by image templates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.services.seer.peak import (
        PeakPetRankRenderInput,
        PeakPoolRenderSnapshot,
        PeakVotePoolInput,
    )
    from ironsbot.services.seer.type_calc import TypeMatchup


def peak_pool_text(snapshot: PeakPoolRenderSnapshot, title: str) -> str:
    return (
        title
        + "\n"
        + "\n".join(
            f"{pool.count}：" + "、".join(pet.name for pet in pool.pets)
            for pool in snapshot.pools
        )
    )


def peak_vote_text(pools: tuple[PeakVotePoolInput, ...], generated_at: str) -> str:
    return (
        generated_at
        + "\n"
        + "\n".join(
            pool.title
            + "："
            + "、".join(f"{item.name} {item.score}" for item in pool.items)
            for pool in pools
        )
    )


def peak_pet_rank_text(result: PeakPetRankRenderInput) -> str:
    return (
        result.title
        + "\n"
        + "\n".join(
            f"ID {item.id}：出场{item.count}，胜场{item.win}"
            for item in result.pick_items
        )
    )


def type_matchup_text(matchup: TypeMatchup) -> str:
    return f"属性：{matchup.target.name}。克制表图片暂不可用。"
