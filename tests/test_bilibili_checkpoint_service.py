from typing import Any

from ironsbot.services.bilibili.checkpoints import (
    InitializedCheckpoint,
    initialize_missing_checkpoints,
    latest_seen_by_uid,
    mark_checkpoint,
)

FIRST_UID = 1310714247
SECOND_UID = 375750254
OLD_TS = 100
MID_TS = 120
NEW_TS = 150


def _item(uid: int, *, name: str = "赛尔号") -> dict[str, Any]:
    return {
        "id_str": f"dynamic-{uid}",
        "modules": {
            "module_author": {
                "mid": uid,
                "name": name,
                "pub_ts": OLD_TS,
            }
        },
    }


def test_latest_seen_by_uid_keeps_newest_item_per_author() -> None:
    first_old = _item(FIRST_UID)
    first_new = _item(FIRST_UID, name="赛尔号新动态")
    second = _item(SECOND_UID)

    latest = latest_seen_by_uid(
        [
            (OLD_TS, first_old),
            (NEW_TS, first_new),
            (MID_TS, second),
        ]
    )

    assert latest[FIRST_UID] == (NEW_TS, first_new)
    assert latest[SECOND_UID] == (MID_TS, second)


def test_initialize_missing_checkpoints_skips_existing_uids() -> None:
    checkpoints = {FIRST_UID: OLD_TS}
    second = _item(SECOND_UID, name="第二账号")

    initialized = initialize_missing_checkpoints(
        checkpoints,
        [
            (NEW_TS, _item(FIRST_UID)),
            (MID_TS, second),
        ],
    )

    assert checkpoints == {
        FIRST_UID: OLD_TS,
        SECOND_UID: MID_TS,
    }
    assert initialized == [
        InitializedCheckpoint(
            author_mid=SECOND_UID,
            pub_ts=MID_TS,
            author_name="第二账号",
        )
    ]


def test_mark_checkpoint_only_moves_forward() -> None:
    checkpoints = {FIRST_UID: OLD_TS}

    assert mark_checkpoint(checkpoints, FIRST_UID, NEW_TS)
    assert checkpoints[FIRST_UID] == NEW_TS

    assert not mark_checkpoint(checkpoints, FIRST_UID, MID_TS)
    assert checkpoints[FIRST_UID] == NEW_TS
