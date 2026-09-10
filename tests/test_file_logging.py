import logging
from pathlib import Path

from ironsbot.app.file_logging import FileLogging
from ironsbot.config.models.settings import LoggingConfig, PathsConfig


def test_rank_evidence_is_written_to_normal_and_error_files(tmp_path: Path) -> None:
    normal = tmp_path / "normal.log"
    errors = tmp_path / "error.log"
    source = logging.getLogger("ironsbot.services.seer.rank_diagnostics")
    wire = logging.getLogger("ironsbot.integrations.headless_seer.rank_wire")
    resource = FileLogging.create(
        LoggingConfig(file_enabled=True, error_file_enabled=True),
        PathsConfig(log_file=normal, error_log_file=errors),
    )
    try:
        source.info("rank query=%s entry=%s", "correlated", "player")
        wire.info("rank query=%s worker=%s raw_sha256=%s", "correlated", 123456, "abc")
        source.error("rank query=%s inverted=True", "correlated")
        logging.getLogger("ironsbot.services.seer.unrelated").warning(
            "unrelated-marker"
        )
        logging.getLogger("httpx").warning("http-secret-marker")
    finally:
        resource.close()
    normal_text = normal.read_text(encoding="utf-8")
    error_text = errors.read_text(encoding="utf-8")
    assert "query=correlated entry=player" in normal_text
    assert "query=correlated worker=123456 raw_sha256=abc" in normal_text
    assert "query=correlated inverted=True" in normal_text
    assert "query=correlated inverted=True" in error_text
    assert "entry=player" not in error_text
    assert "unrelated-marker" not in normal_text
    assert "http-secret-marker" not in normal_text


def test_file_logging_registers_file_sink(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "ironsbot.log"
    resource = FileLogging.create(
        LoggingConfig(file_enabled=True),
        PathsConfig(log_file=log_path),
    )

    try:
        assert len(resource.sink_ids) == 1
        assert log_path.parent.exists()
    finally:
        resource.close()

    assert resource.sink_ids == []


def test_file_logging_registers_error_file_sink(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "ironsbot.log"
    error_log_path = tmp_path / "logs" / "ironsbot.error.log"
    resource = FileLogging.create(
        LoggingConfig(file_enabled=True, error_file_enabled=True),
        PathsConfig(log_file=log_path, error_log_file=error_log_path),
    )

    try:
        assert len(resource.sink_ids) == len((log_path, error_log_path))
        assert log_path.parent.exists()
        assert error_log_path.parent.exists()
    finally:
        resource.close()
