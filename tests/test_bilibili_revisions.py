import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ironsbot.integrations.storage.bilibili_revisions import SqliteBiliRevisionStore
from ironsbot.services.bilibili.revisions import (
    REVISION_META,
    REVISION_RETENTION,
    complete_revision,
    delivery_key,
    visible_signature,
)

NOW = 1_800_000_000
UID = 12345
DETAIL_BUDGET = 10


def item(text: str = "before", image: str = "old.jpg") -> dict:
    return {
        "id_str": "123456",
        "type": "DYNAMIC_TYPE_DRAW",
        "modules": {
            "module_author": {"mid": UID},
            "module_dynamic": {
                "desc": {"text": text},
                "major": {
                    "draw": {"items": [{"src": "https://i0.hdslb.com/" + image}]}
                },
            },
        },
    }


def test_visible_signature_ignores_cdn_and_counters_but_not_order() -> None:
    original = item()
    other = copy.deepcopy(original)
    other["modules"]["module_dynamic"]["major"]["draw"]["items"][0]["src"] = (
        "http://i2.hdslb.com/old.jpg?token=temporary"
    )
    other["modules"]["module_stat"] = {"like": {"count": 999}}
    assert visible_signature(original) == visible_signature(other)
    assert visible_signature(original) != visible_signature(item(image="new.png"))
    assert visible_signature(original) != visible_signature(item(text="after"))


def test_baseline_and_events_survive_restart_and_reversion(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite"
    store = SqliteBiliRevisionStore(path)
    assert store.observe(item(), NOW, UID, clock=NOW) is None
    key = store.observe(item("after"), NOW, UID, clock=NOW + 1)
    assert key == "123456:edit:1"
    store = SqliteBiliRevisionStore(path)
    assert store.observe(item("after"), NOW, UID, clock=NOW + 2) is None
    assert len(store.pending(clock=NOW + 2)) == 1
    event = store.pending(clock=NOW + 2)[0]
    assert event["id_str"] == "123456"
    assert delivery_key(event) == key
    assert event[REVISION_META]["before"] == item()
    store.acknowledge(key)
    assert store.pending(clock=NOW + 2) == []
    assert store.observe(item(), NOW, UID, clock=NOW + 3) == "123456:edit:2"


def test_startup_seeding_never_replays_prior_changes(tmp_path: Path) -> None:
    store = SqliteBiliRevisionStore(tmp_path / "ledger.sqlite")
    store.observe(item(), NOW, UID, clock=NOW, baseline_only=True)
    store.observe(item("cached"), NOW, UID, clock=NOW, baseline_only=True)
    assert store.pending(clock=NOW) == []
    store.observe(item("first online baseline"), NOW, UID, clock=NOW + 1)
    assert store.pending(clock=NOW + 1) == []
    store = SqliteBiliRevisionStore(store.path)
    store.observe(item("new"), NOW, UID, clock=NOW + 2)
    assert store.pending(clock=NOW + 2)[0][REVISION_META]["before"] == item(
        "first online baseline"
    )


def test_partial_foreign_or_expired_observation_does_not_advance(
    tmp_path: Path,
) -> None:
    store = SqliteBiliRevisionStore(tmp_path / "ledger.sqlite")
    store.observe(item(), NOW, UID, clock=NOW)
    assert store.observe({"id_str": "123456"}, NOW, UID, clock=NOW) is None
    assert store.observe({"modules": None}, NOW, UID, clock=NOW) is None
    partial = item("must not look like all pictures were removed")
    partial["modules"]["module_dynamic"]["major"] = {}
    assert store.observe(partial, NOW, UID, clock=NOW) is None
    partial["modules"]["module_dynamic"]["major"] = {"draw": {"items": [{}]}}
    assert store.observe(partial, NOW, UID, clock=NOW) is None
    assert store.observe(item("foreign"), NOW, UID + 1, clock=NOW) is None
    assert (
        store.observe(item("expired"), NOW, UID, clock=NOW + REVISION_RETENTION) is None
    )
    assert store.pending(clock=NOW + REVISION_RETENTION) == []
    store.prune(clock=NOW + REVISION_RETENTION)
    assert store.due(set(), clock=NOW + REVISION_RETENTION) == []


def test_concurrent_observation_registers_once(tmp_path: Path) -> None:
    store = SqliteBiliRevisionStore(tmp_path / "ledger.sqlite")
    store.observe(item(), NOW, UID, clock=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(
            pool.map(
                lambda _: store.observe(item("after"), NOW, UID, clock=NOW), range(2)
            )
        )
    assert result.count("123456:edit:1") == 1
    assert len(store.pending(clock=NOW)) == 1


def test_detail_budget_is_rotating_and_excludes_feed_ids(tmp_path: Path) -> None:
    store = SqliteBiliRevisionStore(tmp_path / "ledger.sqlite")
    for index in range(15):
        data = item()
        data["id_str"] = str(100 + index)
        store.observe(data, NOW, UID, clock=NOW)
    first = store.due({"100"}, clock=NOW + 1)
    assert len(first) == DETAIL_BUDGET
    assert all(key != "100" for key, _uid in first)
    second = store.due(set(), clock=NOW + 2)
    assert second[0][0] == "100"


def test_complete_empty_body_and_forward_are_not_confused_with_partial_data() -> None:
    assert complete_revision(item(text=""))
    partial = item()
    del partial["modules"]["module_dynamic"]["desc"]
    assert not complete_revision(partial)
    partial["modules"]["module_dynamic"]["major"] = {
        "opus": {
            "summary": {"text": ""},
            "pics": [{"url": "https://example.com/a.png"}],
        }
    }
    assert complete_revision(partial)
    forwarded = item()
    forwarded["type"] = "DYNAMIC_TYPE_FORWARD"
    del forwarded["modules"]["module_dynamic"]["major"]
    assert complete_revision(forwarded)
