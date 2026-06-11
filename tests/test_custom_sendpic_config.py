from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "ironsbot"
    / "custom_plugins"
    / "custom_sendpic"
    / "config.py"
)
_SPEC = spec_from_file_location("custom_sendpic_config_for_test", _CONFIG_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_CONFIG = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CONFIG)
PicConfig = _CONFIG.PicConfig
SendpicConfig = _CONFIG.SendpicConfig
enabled_pic_configs = _CONFIG.enabled_pic_configs
pic_id_is_enabled = _CONFIG.pic_id_is_enabled


def _pic(pic_id: str) -> PicConfig:
    return PicConfig(
        id=pic_id,
        backend="local",
        command=pic_id,
        image_dir="images",
        image_filename_template="{index}.png",
    )


def test_pic_id_is_enabled_uses_config_enabled_ids() -> None:
    config = SendpicConfig(enabled_ids={"enabled"})

    assert pic_id_is_enabled(config, "enabled")
    assert not pic_id_is_enabled(config, "disabled")


def test_enabled_pic_configs_filters_by_enabled_ids() -> None:
    enabled = _pic("enabled")
    disabled = _pic("disabled")
    config = SendpicConfig(
        configs=[enabled, disabled],
        enabled_ids={"enabled"},
    )

    assert enabled_pic_configs(config) == [enabled]
