from pathlib import Path

from nonebot.log import logger

from ironsbot.app import file_logging
from ironsbot.config.models.runtime import LoggingConfig


def test_configure_file_logging_registers_file_sink(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "ironsbot.log"
    config = LoggingConfig(file_enabled=True, file_path=str(log_path))
    previous_sink_id = file_logging._FILE_LOG_SINK_ID
    file_logging._FILE_LOG_SINK_ID = None

    try:
        sink_id = file_logging.configure_file_logging(config)

        assert sink_id is not None
        assert log_path.parent.exists()
    finally:
        if sink_id is not None:
            logger.remove(sink_id)
        file_logging._FILE_LOG_SINK_ID = previous_sink_id
