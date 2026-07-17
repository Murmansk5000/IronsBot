# SPDX-License-Identifier: GPL-3.0-or-later
from importlib import import_module

_COMMAND_MODULES = [
    "autocard",
    "countermark_stat_rank",
    "mintmark_queries",
    "pet_queries",
    "player",
    "rank_list",
    "team",
    "upstream_data_queries",
    "upstream_equipment_queries",
    "upstream_peak_queries",
    "upstream_type_queries",
]

for _module in _COMMAND_MODULES:
    import_module(f"{__name__}.{_module}")
