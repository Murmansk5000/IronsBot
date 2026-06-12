from sqlalchemy.exc import SQLAlchemyError

from ironsbot.services.seer.weekly_preview import (
    DEFAULT_WEEKLY_PREVIEW_IMAGE_URL,
    DEFAULT_WEEKLY_PREVIEW_SOURCE_URL,
    load_weekly_preview_links,
    load_weekly_preview_metadata,
)


class _Rows:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str]]:
        return self._rows


class _Session:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows

    def execute(self, *_args: object, **_kwargs: object) -> _Rows:
        return _Rows(self.rows)


class _BrokenSession:
    def execute(self, *_args: object, **_kwargs: object) -> _Rows:
        raise SQLAlchemyError


def test_load_weekly_preview_metadata_reads_configured_rows() -> None:
    metadata = load_weekly_preview_metadata(
        _Session(
            [
                ("weekly_preview_image_url", "https://example.test/preview.png"),
                ("weekly_preview_source_url", "https://example.test/source"),
            ]
        )
    )

    assert metadata == {
        "weekly_preview_image_url": "https://example.test/preview.png",
        "weekly_preview_source_url": "https://example.test/source",
    }


def test_load_weekly_preview_metadata_falls_back_on_sql_errors() -> None:
    assert load_weekly_preview_metadata(_BrokenSession()) == {}


def test_load_weekly_preview_links_uses_defaults_when_metadata_is_missing() -> None:
    assert load_weekly_preview_links(_Session([])) == (
        DEFAULT_WEEKLY_PREVIEW_IMAGE_URL,
        DEFAULT_WEEKLY_PREVIEW_SOURCE_URL,
    )


def test_load_weekly_preview_links_uses_configured_values() -> None:
    assert load_weekly_preview_links(
        _Session(
            [
                ("weekly_preview_image_url", "https://example.test/preview.png"),
                ("weekly_preview_source_url", "https://example.test/source"),
            ]
        )
    ) == (
        "https://example.test/preview.png",
        "https://example.test/source",
    )
