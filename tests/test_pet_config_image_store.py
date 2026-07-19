from pathlib import Path

import pytest

from ironsbot.integrations.storage.pet_config_images import (
    FilePetConfigImageStore,
)


@pytest.mark.asyncio
async def test_store_creates_directory_and_prefers_png(tmp_path: Path) -> None:
    root = tmp_path / "pet_configs"
    store = FilePetConfigImageStore(root)
    (root / "4923.jpg").write_bytes(b"jpg")
    (root / "4923.png").write_bytes(b"png")

    assert root.is_dir()
    assert await store.load(4923) == b"png"


@pytest.mark.asyncio
async def test_store_returns_none_for_missing_or_invalid_pet_id(
    tmp_path: Path,
) -> None:
    store = FilePetConfigImageStore(tmp_path / "pet_configs")

    assert await store.load(4923) is None
    assert await store.load(0) is None
