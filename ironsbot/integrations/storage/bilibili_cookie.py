from pathlib import Path


class FileBiliCookieStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> str:
        return (
            self._path.read_text(encoding="utf-8").strip()
            if self._path.exists()
            else ""
        )

    def save(self, cookie: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(cookie, encoding="utf-8")
