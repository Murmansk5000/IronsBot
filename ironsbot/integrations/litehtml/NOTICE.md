# Native Renderer Provenance

This directory maintains only the framework-independent Python binding and
local resource readers required by IronsBot. Template and native argument
semantics derive from nonebot/plugin-htmlkit 0.1.0rc5 (Python: MIT, copyright
2025 NoneBot). The original notice is retained in LICENSE.

Source: https://github.com/nonebot/plugin-htmlkit

The native C++ litehtml renderer is not copied or rebuilt here. The repository's
packages/litehtml_core distribution extracts the original core binary (upstream C++
binding: LGPL-3.0-or-later). Its source, third-party native dependencies and build
instructions remain in the upstream repository and release source archive.
No wheel, DLL or shared library is committed to this repository.

The binding loads only that binary through Python's extension-file loader,
under this package's core namespace. It does not import or replace the upstream
NoneBot package, patch sys.modules, create a fake driver, or fall back to the
old Python API. A missing/ambiguous binary or different ABI version is an error.
The package and exact native version are intentionally fixed together.

The repository-local ironsbot-litehtml-core package has no runtime dependencies.
Its build verifies published wheel SHA256 hashes and keeps only the unchanged
native binary. Original wheel notices, LGPL/GPL license texts and corresponding
source locations are preserved under packages/litehtml_core. The bot plugin is
used only in development for counterfactual PNG tests, not runtime installation.
No new repository, package-index publication, engine or runtime fallback is used.

Application startup explicitly initializes fonts using FONTCONFIG/FC process
environment variables. HTTP image/CSS callbacks borrow the application's client;
standalone default callbacks read only local files and data URIs. Native options,
PNG output, template base URL and Jinja environment semantics are preserved.
