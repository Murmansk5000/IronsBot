# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime


def datetime_to_sub_key(value: datetime) -> int:
    return int(value.strftime("%Y%m%d"))


def get_current_peak_sub_key(configured_peak_subkey: int | None) -> int | None:
    if configured_peak_subkey is not None:
        return configured_peak_subkey

    try:
        from seerapi_models import PeakSeasonORM

        from ironsbot.integrations.db_registry import db_manager
    except Exception:  # noqa: BLE001
        return None

    session_gen = db_manager.get_session("seerapi")
    if session_gen is None:
        return None

    try:
        session = next(session_gen)
        season = session.get(PeakSeasonORM, 1)
        if season is None:
            return None
        return datetime_to_sub_key(season.start_time)
    except Exception:  # noqa: BLE001
        return None
    finally:
        session_gen.close()


def build_peak_rating_score(rank: int, star: int) -> int | None:
    if rank <= 0 and star <= 0:
        return None
    return rank * 100000 + star


__all__ = [
    "build_peak_rating_score",
    "datetime_to_sub_key",
    "get_current_peak_sub_key",
]
