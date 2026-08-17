from dataclasses import replace
from typing import Any, cast

from jinja2 import Environment, FileSystemLoader

from ironsbot.integrations.seer_data.pet_display_data import _build_effect_views
from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.pet_info_presentation import present_pet_info
from tests.test_seer_pet_info_presentation import _assets, _snapshot


def test_precomputed_shared_parent_links_do_not_duplicate_effects() -> None:
    rows: list[dict[str, object]] = [
        {
            "effect_key": key,
            "glossary_id": identifier,
            "status_id": None,
            "name": key,
            "description": key,
        }
        for key, identifier in (("parent", 1), ("other", 2), ("child", 3))
    ]
    sources: dict[str, list[dict[str, object]]] = {
        "child": [
            {"source_kind": "glossary_link", "source_id": identifier}
            for identifier in (1, 2, 1, 3)
        ]
    }
    views = _build_effect_views(rows, sources)
    assert views[-1].parent_effect_keys == ("parent", "other")
    snapshot = _snapshot()
    document = present_pet_info(
        replace(snapshot, display=replace(snapshot.display, special_effects=views)),
        _assets(),
    )
    effects = cast("tuple[dict[str, Any], ...]", document.templates["special_effects"])
    assert [
        (effect["name"], effect["related"], effect["parents"]) for effect in effects
    ] == [
        ("parent", False, []),
        ("other", False, []),
        ("child", True, ["parent", "other"]),
    ]


def test_cyclic_edges_preserve_identity_without_duplicate_display() -> None:
    rows: list[dict[str, object]] = [
        {
            "effect_key": key,
            "glossary_id": identifier,
            "status_id": None,
            "name": "Same" if key in {"a", "b"} else "Child",
            "description": key,
        }
        for key, identifier in (("a", 10), ("b", 20), ("child", 30))
    ]
    sources: dict[str, list[dict[str, object]]] = {
        "a": [{"source_kind": "glossary_link", "source_id": 20}],
        "b": [{"source_kind": "glossary_link", "source_id": 10}],
        "child": [
            {"source_kind": "glossary_link", "source_id": identifier}
            for identifier in (10, 20, 10, 30)
        ]
        + [{"source_kind": "pet_glossary", "source_id": 30}],
    }
    views = _build_effect_views(rows, sources)
    assert [(effect.effect_key, effect.parent_effect_keys) for effect in views] == [
        ("a", ("b",)),
        ("b", ("a",)),
        ("child", ("a", "b")),
    ]
    snapshot = _snapshot()
    document = present_pet_info(
        replace(snapshot, display=replace(snapshot.display, special_effects=views)),
        _assets(),
    )
    effects = cast("tuple[dict[str, Any], ...]", document.templates["special_effects"])
    assert len(effects) == len(views)
    assert all(effect["related"] for effect in effects)
    html = (
        Environment(
            loader=FileSystemLoader(
                [CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH]
            )
        )
        .get_template(document.template_name)
        .render(document.templates)
    )
    section = html.split('<div class="sec-title">专属效果</div>', 1)[1]
    assert section.count(">Same</span>") == sum(view.name == "Same" for view in views)
    assert section.count(">Child</span>") == 1
