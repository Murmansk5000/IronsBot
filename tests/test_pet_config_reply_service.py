from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ironsbot"
    / "plugins"
    / "seer"
    / "pet_config_reply"
    / "service.py"
)
_SPEC = spec_from_file_location("pet_config_reply_service_for_test", _SERVICE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SERVICE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SERVICE)
PET_CONFIG_UNSUPPORTED_MESSAGE = _SERVICE.PET_CONFIG_UNSUPPORTED_MESSAGE
should_reply_pet_config = _SERVICE.should_reply_pet_config


def test_pet_config_reply_requires_named_pet_match() -> None:
    assert not should_reply_pet_config("", [object()])
    assert not should_reply_pet_config("666", [object()])
    assert not should_reply_pet_config("坤坤咋给", [])
    assert should_reply_pet_config("坤坤咋给", [object()])


def test_pet_config_reply_message_mentions_help() -> None:
    assert "帮助" in PET_CONFIG_UNSUPPORTED_MESSAGE
