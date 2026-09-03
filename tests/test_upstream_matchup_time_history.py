from datetime import datetime, timezone

from seerapi_models.element_type import TypeCombinationORM

from ironsbot.core.time import TZ_CN
from ironsbot.services.seer.peak import normalize_peak_vote_time
from ironsbot.services.seer.type_calc import _calc_multiplier


def test_existing_local_time_keeps_naive_and_aware_comparable() -> None:
    local = normalize_peak_vote_time(datetime(2026, 9, 3, 20))  # noqa: DTZ001 - published naive input
    utc = normalize_peak_vote_time(datetime(2026, 9, 3, 12, tzinfo=timezone.utc))
    assert local == utc == datetime(2026, 9, 3, 20, tzinfo=TZ_CN)


def test_existing_shared_matchup_calculator_supports_mixed_and_immune_types() -> None:
    first = TypeCombinationORM(
        id=1, name="甲", name_en="first", primary_id=1, secondary_id=None
    )
    second = TypeCombinationORM(
        id=2, name="乙", name_en="second", primary_id=2, secondary_id=3
    )
    assert (_calc_multiplier({(1, 2): 2.0, (1, 3): 0.0}, first, second),) == (0.5,)
