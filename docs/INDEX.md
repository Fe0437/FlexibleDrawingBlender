# Blender extension documentation

This repository owns the Blender application boundary for Flexible Drawing. It
contains the Python extension, Blender event and data adapters, Blender UI, and
the native packages that exist only for this host.

Read these pages in order:

- [Architecture](ARCHITECTURE.md) explains which responsibilities stay in
  Blender and which cross the engine ABI.
- [Package map](PACKAGE_MAP.md) lists the Python and native packages and their
  allowed dependencies.
- [API guidelines](API_GUIDELINES.md) defines rules for Blender-facing and ABI
  code.
- [Developer commands](DEVELOPER_COMMANDS.md) covers packaging and manual use.
- [Test strategy](TEST_STRATEGY.md) explains the checks that require Blender
  and the checks that do not.
- The repository's `extension/README.md` documents the Python bridge and its
  current operations.

The root Flexible Drawing documentation remains authoritative for drawing
terminology, engine packages, the public C ABI, and cross-project dependency
rules.

```{toctree}
:maxdepth: 2

ARCHITECTURE
PACKAGE_MAP
API_GUIDELINES
DEVELOPER_COMMANDS
TEST_STRATEGY
```
