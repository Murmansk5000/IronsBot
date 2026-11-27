import pytest

from ironsbot.integrations.seer_data.pet_display_data import _build_effect_views


@pytest.mark.parametrize(
    ("columns", "reference"),
    [
        ({}, ("sign_buff", "137")),
        ({"icon_key": "137_0"}, ("sign_buff", "137_0")),
        ({"icon_kind": None}, None),
        ({"icon_kind": "sign_buff"}, None),
        ({"icon_kind": "sign_buff", "icon_key": "137_0"}, ("sign_buff", "137_0")),
        ({"icon_kind": "abnormal", "icon_key": "137"}, ("abnormal", "137")),
        (
            {"icon_kind": "abnormal", "icon_key": None, "icon_asset_key": "39"},
            ("abnormal", "39"),
        ),
        (
            {"icon_kind": "sign_buff", "icon_key": "137", "icon_asset_key": "137_0"},
            ("sign_buff", "137_0"),
        ),
        ({"icon_kind": "sign_buff", "icon_key": "137", "icon_asset_key": None}, None),
        ({"icon_kind": "unknown", "icon_key": "137"}, None),
    ],
)
def test_effect_icon_contract(
    columns: dict[str, object], reference: tuple[str, str] | None
) -> None:
    facts = _build_effect_views(
        [
            {
                "effect_key": "s:137",
                "name": "英雄之诫",
                "description": "效果说明",
                "glossary_id": None,
                "status_id": 137,
                **columns,
            }
        ],
        {
            "s:137": [
                {
                    "source_kind": "pet_effect_panel",
                    "source_id": 1152,
                    "source_detail": '{"raw_heading":"英雄之诫（下场保留）"}',
                }
            ]
        },
    )
    assert facts[0].icon_reference == reference
    assert facts[0].sources == ("客户端效果面板",)


@pytest.mark.parametrize(
    ("source_kind", "label"),
    [
        ("client_status_display", "客户端条件显示"),
        ("client_status_variant", "客户端状态分支"),
    ],
)
def test_client_status_source_is_not_labelled_as_skill_or_ownership(
    source_kind: str, label: str
) -> None:
    facts = _build_effect_views(
        [
            {
                "effect_key": "s:161",
                "name": "群芳加护",
                "description": "效果说明",
                "glossary_id": None,
                "status_id": 161,
                "icon_kind": "sign_buff",
                "icon_key": "161",
            }
        ],
        {"s:161": [{"source_kind": source_kind, "source_id": 161}]},
    )
    assert facts[0].sources == (label,)
