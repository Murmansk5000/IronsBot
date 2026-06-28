from datetime import datetime
from types import SimpleNamespace
from typing import Any

from pytest import MonkeyPatch

from ironsbot.services.seer import season_countdown

CHINA_TZ = season_countdown.CHINA_TZ


class FakeSession:
    def __init__(self, season: object | None) -> None:
        self.season = season

    def get(self, _model: object, _key: int) -> object | None:
        return self.season


def test_format_season_countdown_uses_peak_season(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        season_countdown,
        "get_app_config",
        lambda: SimpleNamespace(
            seer=SimpleNamespace(
                season=SimpleNamespace(
                    autocard_name="群星牌赛季",
                    autocard_start_time=None,
                    autocard_end_time=None,
                )
            )
        ),
    )
    monkeypatch.setattr(
        season_countdown,
        "datetime",
        SimpleNamespace(
            now=lambda _tz: datetime(2026, 6, 28, 12, 0, 0, tzinfo=CHINA_TZ),
        ),
    )
    peak = SimpleNamespace(
        start_time=datetime(2026, 4, 17, 10, 0, 0, tzinfo=CHINA_TZ),
        end_time=datetime(2026, 7, 17, 10, 0, 0, tzinfo=CHINA_TZ),
    )

    message = season_countdown.format_season_countdown(FakeSession(peak))

    assert "巅峰圣战赛季：2026-04-17 10:00 ~ 2026-07-17 10:00" in message
    assert "状态：进行中，剩余 18天22小时0分钟" in message
    assert "群星牌赛季：未收录赛季结束时间" in message


def test_format_season_countdown_uses_configured_autocard_time(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        season_countdown,
        "get_app_config",
        lambda: SimpleNamespace(
            seer=SimpleNamespace(
                season=SimpleNamespace(
                    autocard_name="群星牌S1赛季",
                    autocard_start_time=datetime(
                        2026, 6, 20, 10, 0, 0, tzinfo=CHINA_TZ
                    ),
                    autocard_end_time=datetime(
                        2026, 7, 17, 10, 0, 0, tzinfo=CHINA_TZ
                    ),
                )
            )
        ),
    )
    monkeypatch.setattr(
        season_countdown,
        "datetime",
        SimpleNamespace(
            now=lambda _tz: datetime(2026, 6, 28, 12, 0, 0, tzinfo=CHINA_TZ),
        ),
    )

    message = season_countdown.format_season_countdown(FakeSession(None))

    assert "巅峰圣战赛季：未找到赛季数据" in message
    assert "群星牌S1赛季：2026-06-20 10:00 ~ 2026-07-17 10:00" in message
    assert "状态：进行中，剩余 18天22小时0分钟" in message


def test_load_peak_season_window_returns_none_without_model(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_import(name: str, *_args: Any, **_kwargs: Any) -> object:
        if name == "seerapi_models":
            raise ImportError
        return __import__(name, *_args, **_kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    assert season_countdown.load_peak_season_window(FakeSession(None)) is None
