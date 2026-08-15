# SPDX-License-Identifier: MIT
"""Seer data query and asset access helpers."""

from pathlib import Path

# Final-image cache versions must include every public adapter that can change
# assembled pixels, not only the corresponding presentation templates.
SEER_DATA_RENDERERS_PATH = Path(__file__).resolve().parent
