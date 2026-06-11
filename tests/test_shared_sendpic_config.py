from ironsbot.shared.config.config import PicConfig, SendpicConfig
from ironsbot.shared.config.sendpic import enabled_pic_configs, pic_id_is_enabled


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
