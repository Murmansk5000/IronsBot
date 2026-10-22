from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("level", ["INFO", "ERROR", "CUSTOM"])
def test_application_logs_are_redacted_without_framework(
    tmp_path: Path, level: str
) -> None:
    script = r"""
import logging
import sys
from pathlib import Path

sys.modules["nonebot"] = None
from loguru import logger
from ironsbot.app.application_logging import configure_application_logging
from ironsbot.app.file_logging import FileLogging
from ironsbot.app.log_privacy import configure_log_privacy
from ironsbot.config.models.settings import LoggingConfig, PathsConfig

logger.remove()
messages = []
logger.add(messages.append, format="{message}", level=0, diagnose=False)
secret = "logging-test-secret"
identity = "8" * 10
configure_log_privacy({"TEST_SECRET": secret})
application = logging.getLogger("ironsbot")
for configured in ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"):
    configure_application_logging(configured)
    assert application.level == logger.level(configured).no
configure_application_logging("INFO")
configure_application_logging("INFO")
assert len(application.handlers) == 1
assert application.propagate is False
root_records = []

class RootHandler(logging.Handler):
    def emit(self, record):
        root_records.append(record)

logging.getLogger().addHandler(RootHandler())
logging.getLogger().setLevel(0)
path = Path(sys.argv[1])
resource = FileLogging.create(
    LoggingConfig(file_enabled=True, error_file_enabled=True),
    PathsConfig(log_file=path / "app.log", error_log_file=path / "error.log"),
)
source = logging.getLogger("ironsbot.acceptance")
if sys.argv[2] == "CUSTOM":
    severity = 35
    logging.addLevelName(severity, "APPLICATION_CUSTOM")
else:
    severity = getattr(logging, sys.argv[2])
try:
    raise RuntimeError(f"failed for {secret} actor={identity}")
except RuntimeError:
    source.log(severity, "request failed: %s actor=%s", secret, identity, exc_info=True)
source.debug("below-configured-level")
resource.close()
resource.close()
assert not resource.sink_ids
assert not root_records, "raw records escaped through root logging"
records = [message for message in messages if "request failed:" in str(message)]
assert len(records) == 1, records
assert records[0].record["name"] == "__main__", records[0].record
assert records[0].record["level"].no == severity
for text in (str(records[0]), (path / "app.log").read_text(encoding="utf-8")):
    assert secret not in text and identity not in text, "sensitive log output"
    assert "<secret:" in text and "<id:" in text
    assert "RuntimeError" in text
    assert "below-configured-level" not in text
errors = (path / "error.log").read_text(encoding="utf-8")
assert ("request failed:" in errors) == (severity >= logging.ERROR)
assert secret not in errors and identity not in errors
assert sys.modules["nonebot"] is None
assert "nonebot.log" not in sys.modules
print("APPLICATION_LOGGING_OK")
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), level],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "APPLICATION_LOGGING_OK"


def test_extension_import_and_factory_logs_share_private_sinks(tmp_path: Path) -> None:
    script = r"""
import logging, sys
from pathlib import Path
from importlib.metadata import EntryPoint
sys.modules["nonebot"] = None
from loguru import logger
from ironsbot.app.application_logging import configure_application_logging
from ironsbot.app.log_privacy import configure_log_privacy
from ironsbot.app.file_logging import FileLogging
from ironsbot.app.private_extensions import (
    PrivateExtensionCatalog, PrivateExtensionManifest,
)
from ironsbot.config.models.settings import LoggingConfig, PathsConfig
logger.remove()
messages = []
logger.add(messages.append, format="{message}", level=0, diagnose=False)
secret = "synthetic-extension-secret"
configure_log_privacy({"TEST_SECRET": secret})
configure_application_logging("INFO")
root_records = []
class RootHandler(logging.Handler):
    def emit(self, record):
        if record.name.startswith("ironsbot_private_logging_probe"):
            root_records.append(record)
logging.getLogger().addHandler(RootHandler())
path = Path(sys.argv[1])
package = path / "ironsbot_private_logging_probe"
package.mkdir()
(package / "__init__.py").write_text("", encoding="utf-8")
(package / "plugin.py").write_text(
    "import logging\n"
    "from ironsbot.core.plugin_install import PluginContribution\n"
    "logger = logging.getLogger(__name__)\n"
    "logger.warning('extension import %s', 'synthetic-extension-secret')\n"
    "def build(services):\n"
    "    try:\n"
    "        raise ValueError('synthetic-extension-secret')\n"
    "    except ValueError:\n"
    "        logger.exception('extension factory actor=%s', '8' * 10)\n"
    "    return PluginContribution(id='extension_logging_probe')\n",
    encoding="utf-8",
)
resource = FileLogging.create(
    LoggingConfig(file_enabled=True, error_file_enabled=True),
    PathsConfig(log_file=path / "app.log", error_log_file=path / "error.log"),
)
catalog = PrivateExtensionCatalog(path, PrivateExtensionManifest((EntryPoint(
    name="probe", value="ironsbot_private_logging_probe.plugin:build",
    group="ironsbot.extensions"
),)))
catalog.contributions(object())
catalog.contributions(object())
resource.close()
extension_messages = [
    message for message in messages
    if "extension import" in message or "extension factory" in message
]
assert len(extension_messages) == 3, "extension records bypassed or duplicated sinks"
assert not root_records, "unredacted extension record escaped to root"
namespace = logging.getLogger("ironsbot_private_logging_probe")
assert len(namespace.handlers) == 1 and namespace.propagate is False
for text in ("".join(messages), (path / "app.log").read_text(encoding="utf-8"),
             (path / "error.log").read_text(encoding="utf-8")):
    assert secret not in text and "8" * 10 not in text
    assert "<secret:" in text
assert "nonebot.log" not in sys.modules
print("EXTENSION_LOGGING_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "EXTENSION_LOGGING_OK"
