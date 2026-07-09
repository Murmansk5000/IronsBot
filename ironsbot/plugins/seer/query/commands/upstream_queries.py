# SPDX-License-Identifier: GPL-3.0-or-later
"""High-priority entry points for upstream Seer info queries.

Importing this module registers the upstream query matcher modules.
"""

from . import (
    upstream_data_queries,
    upstream_equipment_queries,
    upstream_mintmark_queries,
    upstream_peak_queries,
    upstream_pet_queries,
    upstream_type_queries,
)

__all__ = [
    "upstream_data_queries",
    "upstream_equipment_queries",
    "upstream_mintmark_queries",
    "upstream_peak_queries",
    "upstream_pet_queries",
    "upstream_type_queries",
]
