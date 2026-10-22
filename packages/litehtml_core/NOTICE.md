# Native Renderer Distribution

This package redistributes only the unchanged litehtml binary built by
nonebot/plugin-htmlkit 0.1.0rc5 (Copyright 2025 NoneBot). It does not include or
import the upstream Python bot plugin. It declares no runtime dependencies.

`artifacts.json` records the exact upstream wheel URLs and SHA256 hashes. Build
selects a compatible published ABI, verifies the archive, and copies only its
single core binary. Unsupported platforms fail explicitly. No native binary
is checked into this repository, and no network access occurs at runtime.

The C++ binding is LGPL-3.0-or-later. LICENSE and LICENSE.GPL-3.0 preserve the
corresponding license texts; LICENSE.UPSTREAM preserves the wheel's notice.
The packaging code and empty Python namespace are MIT, as marked per file.

Corresponding source and upstream build instructions:
https://github.com/nonebot/plugin-htmlkit

Exact source archive (including native build files and submodule revisions):
https://files.pythonhosted.org/packages/29/79/7f0b60a19132e335cb2d6ec2902e330afc97e82462dc152ae033864acf25/nonebot_plugin_htmlkit-0.1.0rc5.tar.gz

Source SHA256:
`5c9fc3ed1d1cbf95711006761d19e7a1dc0d0e8b7989c2e806a2bff3aeff7b17`

The shared native core remains replaceable by an interface-compatible modified
build. To rebuild, use the source archive's setup.py/xmake.lua and locked
submodules; install the rebuilt core in ironsbot_litehtml. IronsBot's Python
callback ABI and rendering policy remain in its own integrations/litehtml code.
