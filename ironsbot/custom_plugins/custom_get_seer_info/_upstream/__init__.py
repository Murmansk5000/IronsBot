# SPDX-License-Identifier: GPL-3.0-or-later
"""Vendored upstream Seer query helpers used by custom entry points.

This package intentionally does not expose user-facing matchers. Custom plugins
import handler functions and renderers from here while registering their own
high-priority matchers.
"""

