from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NO_FRAMEWORK = """
import sys
from importlib.abc import MetaPathFinder
class RejectFramework(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "nonebot" or fullname.startswith("nonebot."):
            raise AssertionError("unexpected framework import: " + fullname)
sys.meta_path.insert(0, RejectFramework())
"""


def test_generator_bootstrap_uses_shared_ingress_without_native_registration(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "bootstrap.toml"
    config_path.write_text(
        (ROOT / "config.example.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    script = (
        NO_FRAMEWORK
        + """
import socket
import sys
from loguru import logger

def network_forbidden(*args, **kwargs):
    raise AssertionError("registration must not connect to the network")

socket.socket.connect = network_forbidden
socket.create_connection = network_forbidden
logger.remove()
from ironsbot.app.application import Application
import ironsbot.app.seer_composition as seer_composition
original_rendering = seer_composition.build_seer_rendering_components
render_resources_checked = False

def checked_rendering(clients, *args, **kwargs):
    global render_resources_checked
    result = original_rendering(clients, *args, **kwargs)
    renderer = result[1].renderer
    image_owner = renderer.keywords["img_fetch_fn"].__self__
    css_owner = renderer.keywords["css_fetch_fn"].__self__
    assert image_owner is css_owner
    assert image_owner.clients is clients
    render_resources_checked = True
    return result

seer_composition.build_seer_rendering_components = checked_rendering
original_install = Application.install
def checked_install(self, router):
    assert self.lifecycle.scheduler is self.scheduler
    assert 'nonebot_plugin_apscheduler' not in sys.modules
    assert 'nonebot_plugin_htmlkit' not in sys.modules
    assert router.ingress.claims.spawn == self.task_owner.create_draining
    assert self.resources.onebot_admission.features is self.resources.features
    assert self.resources.onebot_messenger._self_commands is (
        self.resources.onebot_admission.self_commands
    )
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.platform import ActorRef, ConversationRef, Platform
    features = self.resources.features
    assert isinstance(features.group_features, dict)
    assert isinstance(features.actor_features, dict)
    extension = self.extension_services.player_lineup
    for platform in Platform:
        account = "test-account" if platform is Platform.QQ_OFFICIAL else None
        actor = ActorRef(platform, "910001", account_id=account)
        group = ConversationRef(platform, "group", "920001", account_id=account)
        private = ConversationRef(platform, "private", actor.id, account_id=account)
        for conversation in (group, private):
            context = CommandContext(actor, conversation)
            assert not extension.is_feature_visible_in_help(
                context, "player_lineup_private"
            )
            if conversation.kind == "group":
                features.group_features[group] = frozenset({"player_lineup_private"})
            else:
                features.actor_features[actor] = frozenset({"player_lineup_private"})
            assert extension.is_feature_visible_in_help(
                context, "player_lineup_private"
            ), "configured extension help must accept the public command context"
    return original_install(self, router)
Application.install = checked_install
from scripts.generate_poke_command_introductions import _command_ids
assert _command_ids()
assert render_resources_checked
assert not any(name.startswith("nonebot.") for name in sys.modules)
print("SHARED_INGRESS_OK")
"""
    )
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(
            ("QQ_OFFICIAL_", "APP_ID_", "APP_SECRET_", "ONEBOT_", "AI_KEY")
        ):
            del environment[key]
    environment.update(APP_CONFIG_PATH=str(config_path), PYTHONPATH=str(ROOT))
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "SHARED_INGRESS_OK"


def test_application_bootstrap_smoke(tmp_path: Path) -> None:
    config = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    config = config.replace('environment = "prod"', 'environment = "test"', 1)
    config = config.replace(
        'qq_state = "data/state/qq_state.sqlite"',
        f'qq_state = "{(tmp_path / "qq_state.sqlite").as_posix()}"',
    )
    config_path = tmp_path / "bootstrap.toml"
    config_path.write_text(config, encoding="utf-8")
    script = (
        NO_FRAMEWORK
        + """
import os
import sys
from loguru import logger

logger.remove()

from ironsbot.app.bootstrap import bootstrap

state = bootstrap()
assert state.settings.bot.environment == "test"
assert os.environ["ENVIRONMENT"] == "outer"
messages = []
privacy_sink = logger.add(messages.append, format="{message}")
actor_id = "1" * 10
try:
    logger.info(
        "secret={} actor={}",
        os.environ["APP_SECRET_10001"],
        actor_id,
    )
finally:
    logger.remove(privacy_sink)
rendered = "".join(messages)
assert "test-secret" not in rendered
assert actor_id not in rendered
assert "<secret:" in rendered
assert "<id:" in rendered
assert state.lifecycle is not None
assert state.lifecycle.scheduler is state.scheduler
assert state.onebot_transport.accounts is state.resources.onebot_connections
assert state.onebot_transport.observer is state.lifecycle
assert state.onebot_transport is not None
assert state.lifecycle.shutdown_hooks[-1] == (
    "onebot_transport", state.onebot_transport.close
)
assert state.resources.onebot_messenger._router.connections is (
    state.resources.onebot_connections
)
assert 'nonebot_plugin_apscheduler' not in sys.modules
assert [name for name, _hook in state.lifecycle.resource_startup_hooks] == [
    "fontconfig",
    "push_tasks_recover",
    "identity_links",
    "data_sync",
    "qq_official",
    "onebot_transport",
]
from ironsbot.core.platform import Platform
assert state.lifecycle.startup_hooks[-1][0] == "push_recovery"
assert state.lifecycle.first_connection_platforms == frozenset({Platform.QQ_OFFICIAL})
assert state.resources.qq_official._connection_observer is state.lifecycle
assert state.resources.qq_official._spawn_connection_event == state.task_owner.create
assert {"seer.team.query", "seer.pet.avatar"}.issubset(
    state.resources.commands.qq_official_direct_command_ids
)
assert len(state.contributions) > 0
assert not state.onebot_message_handling_enabled
assert not any(name.startswith("nonebot.") for name in sys.modules)
assert state.resources.onebot_admission.errors is state.resources.command_errors
from ironsbot.integrations.storage.inbound_claims import SqliteInboundMessageClaims
assert state.resources.identity_observer is not None
assert isinstance(state.resources.identity_observer.claims, SqliteInboundMessageClaims)
assert state.resources.identity_observer.claims.spawn == (
    state.task_owner.create_draining
)
assert state.resources.identity_observer.store.spawn == state.task_owner.create_draining
mutations = state.resources.identity_linking.mutations
assert mutations.spawn == state.task_owner.create_draining
assert state.resources.identity_observer.mutations is mutations
assert state.resources.union_identity.mutations is mutations
assert state.resources.union_identity.on_link == (
    state.resources.union_identity.addresses.accept_link
)
assert state.resources.identity_observer.claims.path == (
    state.settings.paths.cache_root / "identity" / "observations.sqlite"
)
assert len({plugin.id for plugin in state.contributions}) == len(state.contributions)

print("BOOTSTRAP_OK")
"""
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if not key.startswith(
                    ("APP_SECRET_", "ONEBOT_", "AI_KEY", "QQ_OFFICIAL_")
                )
            },
            "PYTHONPATH": str(ROOT),
            "ENVIRONMENT": "outer",
            "APP_CONFIG_PATH": str(config_path),
            "APP_SECRET_10001": "test-secret",
            "ONEBOT_IDENTITY_VERIFICATION": "true",
            "ONEBOT_TRUSTED_OFFICIAL_BOT_EXAMPLE_BOT": "123456789",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "BOOTSTRAP_OK"


@pytest.mark.parametrize(
    ("onebot", "official"), [(True, False), (False, True), (True, True)]
)
def test_three_deployment_modes_compose_without_framework_or_network(
    tmp_path: Path, *, onebot: bool, official: bool
) -> None:
    config_path = tmp_path / "mode.toml"
    config = f"""
[bot]
environment = "test"
plugin_manifest = "core"
[bot.onebot]
enabled = {str(onebot).lower()}
"""
    if official:
        config += """
[bot.qq_official.accounts.test_bot]
app_id = "10001"
"""
    config_path.write_text(config, encoding="utf-8")
    script = (
        NO_FRAMEWORK
        + """
import socket
from loguru import logger
logger.remove()
def forbidden(*args, **kwargs):
    raise AssertionError("composition opened a network connection")
socket.socket.connect = forbidden
socket.create_connection = forbidden
from ironsbot.app.bootstrap import bootstrap
app = bootstrap()
onebot = sys.argv[1] == "True"
official = sys.argv[2] == "True"
assert (app.onebot_transport is not None) == onebot
assert len(app.asgi.routes) == (6 if onebot else 0)
assert (app.resources.qq_official is not None) == official
expected = "qq_official" if official else "onebot"
assert app.settings.outbound_platform_selection.platform.value == expected
assert app.onebot_message_handling_enabled == (onebot and not official)
assert app.lifecycle is not None
names = [name for name, _ in app.lifecycle.resource_startup_hooks]
assert ("onebot_transport" in names) == onebot
assert ("qq_official" in names) == official
assert not any(name.startswith("nonebot.") for name in sys.modules)
print("MODE_OK")
"""
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("QQ_OFFICIAL_", "APP_ID_", "APP_SECRET_", "ONEBOT_", "AI_KEY")
        )
    }
    environment.update(APP_CONFIG_PATH=str(config_path), PYTHONPATH=str(ROOT))
    if official:
        environment["APP_SECRET_10001"] = "mode-test-secret"
    result = subprocess.run(
        [sys.executable, "-c", script, str(onebot), str(official)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "MODE_OK"
