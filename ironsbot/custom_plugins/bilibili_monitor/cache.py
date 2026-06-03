import json
from pathlib import Path

from nonebot.log import logger

from .state import (
    BILI_UID,
    CACHE_FILE,
    CHECKPOINTS_FILE,
    COOKIE_CACHE_FILE,
    LEGACY_CACHE_FILE,
    LEGACY_COOKIE_CACHE_FILE,
)


def _migrate_legacy_cache_file(legacy_file: Path, cache_file: Path) -> None:
    if cache_file.exists() or not legacy_file.exists():
        return

    try:
        cache_file.write_text(
            legacy_file.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"failed to migrate Bilibili cache {legacy_file.name}: {e}")


def migrate_legacy_cache_files() -> None:
    _migrate_legacy_cache_file(LEGACY_CACHE_FILE, CACHE_FILE)
    _migrate_legacy_cache_file(LEGACY_COOKIE_CACHE_FILE, COOKIE_CACHE_FILE)


def _read_legacy_last_saved_time() -> int:
    if not CACHE_FILE.exists():
        return 0

    try:
        return int(CACHE_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def get_last_saved_times() -> dict[int, int]:
    if CHECKPOINTS_FILE.exists():
        try:
            data = json.loads(CHECKPOINTS_FILE.read_text(encoding="utf-8"))
            return {
                int(uid): int(pub_time)
                for uid, pub_time in data.items()
                if int(pub_time) > 0
            }
        except Exception as e:
            logger.warning(f"failed to read Bilibili checkpoints: {e}")

    legacy_time = _read_legacy_last_saved_time()
    if legacy_time > 0:
        return {BILI_UID: legacy_time}

    return {}


def save_last_saved_times(checkpoints: dict[int, int]) -> None:
    cleaned = {
        str(uid): int(pub_time)
        for uid, pub_time in sorted(checkpoints.items())
        if int(pub_time) > 0
    }
    CHECKPOINTS_FILE.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if cleaned:
        latest_time = max(cleaned.values())
        CACHE_FILE.write_text(str(latest_time), encoding="utf-8")


def get_last_saved_time(uid: int | None = None) -> int:
    checkpoints = get_last_saved_times()
    if uid is not None:
        return checkpoints.get(uid, 0)

    return max(checkpoints.values(), default=0)


def save_last_time(pub_time: int, uid: int | None = None) -> None:
    checkpoints = get_last_saved_times()
    checkpoints[uid or BILI_UID] = pub_time
    save_last_saved_times(checkpoints)


def get_saved_cookie() -> str:
    if not COOKIE_CACHE_FILE.exists():
        return ""

    return COOKIE_CACHE_FILE.read_text(encoding="utf-8").strip()


def save_new_cookie(cookie_str: str) -> None:
    COOKIE_CACHE_FILE.write_text(cookie_str, encoding="utf-8")
