# SPDX-License-Identifier: MIT
"""Configuration-backed promotion definitions shared by delivery adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from typing_extensions import Self

if TYPE_CHECKING:
    from collections.abc import Mapping


class PromotionConfig(BaseModel):
    """One optional text attachment governed by a feature policy."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool = True
    feature: str
    url: str = ""
    text: str
    append_to_push: bool = False

    @field_validator("feature", "text")
    @classmethod
    def require_nonempty(cls, value: str) -> str:
        if not value:
            raise ValueError("推广项 feature 和 text 不能为空")  # noqa: TRY003
        return value

    @model_validator(mode="after")
    def validate_text_template(self) -> Self:
        try:
            self.text.format(url=self.url)
        except (IndexError, KeyError, ValueError) as exc:
            raise ValueError(  # noqa: TRY003
                "推广项 text 只允许使用 {url} 占位符"
            ) from exc
        return self

    @property
    def message(self) -> str:
        return self.text.format(url=self.url)


@dataclass(frozen=True, slots=True)
class PromotionCatalog:
    """Read-only lookup for named promotion definitions."""

    _definitions: Mapping[str, PromotionConfig]

    def get(self, promotion_id: str) -> PromotionConfig | None:
        return self._definitions.get(promotion_id.strip())

    def require(self, promotion_id: str) -> PromotionConfig:
        promotion = self.get(promotion_id)
        if promotion is None:
            raise ValueError(f"未知推广项：{promotion_id}")
        return promotion

    @property
    def push_promotions(self) -> tuple[PromotionConfig, ...]:
        return tuple(
            promotion
            for promotion in self._definitions.values()
            if promotion.enabled and promotion.append_to_push
        )
