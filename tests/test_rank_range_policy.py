import pytest
from ironsbot.services.seer.rank_ranges import MAX_RANK_POSITION, RankRangeError, validate_rank_interval
from ironsbot.services.seer.rank_list_parsing import parse_rank_list_command

def test_historical_rank_bounds_are_not_search_budgets():
    validate_rank_interval(10001, 20000)
    validate_rank_interval(MAX_RANK_POSITION, MAX_RANK_POSITION)
    with pytest.raises(RankRangeError):
        validate_rank_interval(0, 1)
    with pytest.raises(RankRangeError):
        validate_rank_interval(2, 1)

def test_historical_range_keeps_original_end():
    command = parse_rank_list_command("成就榜10001-20000", max_limit=20)
    assert command is not None
    assert command.start_rank == 10001 and command.limit == 20
    assert command.requested_end_rank == 20000
