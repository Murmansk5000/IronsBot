from ironsbot.services.bilibili.storage import cookie_cache_file


def get_saved_cookie() -> str:
    cache_file = cookie_cache_file()
    if not cache_file.exists():
        return ""

    return cache_file.read_text(encoding="utf-8").strip()


def save_new_cookie(cookie_str: str) -> None:
    cache_file = cookie_cache_file()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(cookie_str, encoding="utf-8")
