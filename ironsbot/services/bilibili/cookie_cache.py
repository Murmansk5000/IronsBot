from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BiliCookieStore:
    path: Path

    def load(self) -> str:
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8").strip()

    def save(self, cookie: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(cookie, encoding="utf-8")
