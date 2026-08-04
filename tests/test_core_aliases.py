# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.core.aliases import AliasError, AliasIndex


def _normalize(value: str) -> str:
    return "".join(value.split()).casefold()


def test_alias_index_returns_unique_value_for_normalized_alias() -> None:
    index = AliasIndex.from_pairs(
        (("Alpha Name", 1),),
        normalizer=_normalize,
    )

    resolution = index.resolve_alias(" alpha   name ")

    assert resolution.is_unique is True
    assert resolution.is_ambiguous is False
    assert resolution.unique_value == 1
    assert resolution.matches[0].alias == "Alpha Name"


def test_alias_index_preserves_ambiguous_matches_for_the_domain_to_handle() -> None:
    index = AliasIndex.from_pairs(
        (("same", 1), ("same", 2)),
        normalizer=_normalize,
    )

    resolution = index.resolve_alias("SAME")

    assert resolution.is_ambiguous is True
    assert resolution.unique_value is None
    assert [match.value for match in resolution.matches] == [1, 2]


def test_alias_index_rejects_empty_configured_aliases() -> None:
    index = AliasIndex[int](_normalize)

    with pytest.raises(AliasError, match="nonempty"):
        index.add("   ", 1)


def test_alias_index_treats_empty_user_input_as_no_match() -> None:
    index = AliasIndex.from_pairs((("alpha", 1),), normalizer=_normalize)

    resolution = index.resolve_alias("   ")

    assert resolution.is_empty is True
    assert resolution.unique_value is None
