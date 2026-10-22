# SPDX-License-Identifier: MIT
from setuptools import Extension, setup

setup(
    ext_modules=[Extension("ironsbot_litehtml.core", sources=[], py_limited_api=True)]
)
