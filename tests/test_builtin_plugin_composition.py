from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

from ironsbot.config.models.settings import Settings
from tests.helpers.plugin_registry import build_test_plugin_registry

FULL_CONTRIBUTION_COUNT = 27


def test_project_adapter_declaration_matches_the_transitional_onebot_host() -> None:
    document = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert document["tool"]["nonebot"]["adapters"]["nonebot-adapter-onebot"] == [
        {"name": "OneBot V11", "module_name": "nonebot.adapters.onebot.v11"}
    ]


@pytest.mark.parametrize("profile", ["full", "core"])
def test_profiles_compose_only_their_declared_contributions(profile: str) -> None:
    settings = Settings.model_validate({"bot": {"plugin_manifest": profile}})
    contributions = build_test_plugin_registry(settings)
    ids = tuple(item.id for item in contributions)
    assert len(set(ids)) == len(ids)
    core = ("seer_query", "about", "help", "poke_reply", "rank_help")
    if profile == "core":
        assert ids == core
        assert all(
            name not in {"messaging", "ai_chat", "ai_intent", "bilibili"}
            for name in ids
        )
    else:
        assert len(ids) == FULL_CONTRIBUTION_COUNT
        assert set(core) < set(ids)
        assert ids[:2] == ("clock_startup_check", "seer_query")


def test_core_factories_run_without_a_nonebot_import_or_host(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    script = r"""
import sys
from importlib.abc import MetaPathFinder
from types import SimpleNamespace

class NoFramework(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("nonebot"):
            raise AssertionError("business factory imported a framework: " + fullname)
sys.meta_path.insert(0, NoFramework())
from ironsbot.app.plugin_composition import build_builtin_contributions
from ironsbot.config.models.settings import Settings
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver

resources = SimpleNamespace(
    admin_notices=object(),
    player_id_resolver=PlayerIdResolver(lambda *_: None, lambda _: None),
    sendpic=SimpleNamespace(exact_command_texts=frozenset()),
    headless=object(), local_rank=object(), rank_page_refresh=object(),
)
settings = Settings.model_validate({"bot": {"plugin_manifest": "core"}})
contributions = build_builtin_contributions(settings, resources, object())
assert tuple(item.id for item in contributions) == (
    "seer_query", "about", "help", "poke_reply", "rank_help",
)
assert not any(name.startswith("nonebot") for name in sys.modules)
print("FACTORIES_WITHOUT_FRAMEWORK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=os.environ | {"PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "FACTORIES_WITHOUT_FRAMEWORK"
