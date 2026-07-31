"""Check the retired document and the README link forms used in this history."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _active_targets(text: str):
    text = re.sub(r"(?ms)^```[^\n]*\n.*?^```[ \t]*$", "", text)
    definition = r"(?m)^ {0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]+)>|([^\s]+))[^\n]*$"
    references = {
        " ".join(match[1].split()).casefold(): match[2] or match[3]
        for match in re.finditer(definition, text)
    }
    text = re.sub(definition, "", text)
    inline = (
        r"\[[^\]\n]*\]\([ \t]*(?:<([^>\n]+)>|([^\s)]+))"
        r"(?:[ \t]+[\"'][^\"']*[\"'])?[ \t]*\)"
    )
    targets = [match[1] or match[2] for match in re.finditer(inline, text)]
    text = re.sub(inline, "", text)
    for match in re.finditer(r"\[([^\]\n]+)\](?:[ \t]*\[([^\]\n]*)\])?", text):
        key = " ".join((match[2] or match[1]).split()).casefold()
        if key in references:
            targets.append(references[key])
    return targets


def _is_retired_document(target: str):
    target = re.split(r"[?#]", target, maxsplit=1)[0]
    return target.rstrip("/").rsplit("/", 1)[-1].casefold() == "readme.old.md"


def test_retired_readme_document_does_not_return() -> None:
    document = ROOT / "README.old.md"
    assert not document.exists() and not document.is_symlink()


def test_active_readme_links_do_not_target_retired_document() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert not [
        target for target in _active_targets(text) if _is_retired_document(target)
    ]
