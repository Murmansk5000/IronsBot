from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.app.command_directory.seer import seer_query_commands
from ironsbot.services.seer.data_query_commands import MASTER_POOL_COMMANDS
from ironsbot.services.seer.master_pool import (
    MasterPoolUnavailableError,
    load_master_pools,
)
from ironsbot.services.seer.new_content import (
    NewContentItem,
    format_new_content_item_description,
)
from ironsbot.services.seer.rendering.new_content_pool_changes import (
    pool_change_preview,
)


def test_master_pool_database_reads_costs_and_official_resource_ids() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        session.execute(
            text(
                "CREATE TABLE peak_master_pool (id INTEGER, cost INTEGER, "
                "pet_ids_json TEXT, subkey_total INTEGER)"
            )
        )
        session.execute(
            text(
                "INSERT INTO peak_master_pool VALUES (1,35,'[5000]',20260904),"
                "(2,20,'[4354]',20260904),(3,0,'[]',20260904)"
            )
        )
        session.execute(
            text(
                "CREATE TABLE pet (id INTEGER, name TEXT, "
                "resource_id INTEGER, type_id INTEGER)"
            )
        )
        session.execute(text("INSERT INTO pet VALUES (5000,'圣灵谱尼',45000,2)"))
        pools = load_master_pools(session)
    engine.dispose()
    assert [pool.count for pool in pools] == [35, 20, 0]
    assert [pools[0].pets[0].resource_id, pools[1].pets[0].id] == [45000, 4354]
    assert pools[0].start_time.strftime("%Y-%m-%d") == "2026-09-04"
    assert pools[2].pets == ()


def test_old_database_has_explicit_master_pool_unavailable_error() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session, pytest.raises(MasterPoolUnavailableError):
        load_master_pools(session)
    engine.dispose()


@pytest.mark.parametrize(
    ("old", "new", "label"),
    [
        (20, 10, "20 点 → 10 点"),
        (None, 35, "未列入 → 35 点"),
        (6, None, "6 点 → 未列入"),
        (6, 0, "6 点 → 0 点"),
    ],
)
def test_master_pool_weekly_wording_and_preview(
    old: int | None,
    new: int | None,
    label: str,
) -> None:
    item = NewContentItem(
        "peak_master_pool",
        5000,
        "圣灵谱尼",
        5000,
        {"previous_limit": old, "current_limit": new},
        "modified",
    )
    assert label in format_new_content_item_description(item)
    preview = pool_change_preview("peak_master_pool", (item,))
    assert preview["kind"] == "master"
    assert preview["direction_rows"][0]["direction"] == label
    assert preview["matrix_rows"] == ()
    assert preview["other_rows"] == ()


def test_master_pool_catalog_reuses_aliases_and_peak_permission() -> None:
    command = next(
        item for item in seer_query_commands() if item.id == "seer.peak.master"
    )
    assert command.examples == MASTER_POOL_COMMANDS
    assert "大师池" in command.examples
    assert "每周大师池" in command.examples
    assert command.features_any == ("seer_peak",)
