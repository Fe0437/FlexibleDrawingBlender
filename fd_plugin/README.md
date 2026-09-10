# Native Blender integration

This directory owns native code and package boundaries that exist only for the
Blender extension. Blender input, document binding, geometry conversion,
viewports, OpenUSD access, Hydra registration, and Blender canvas providers are
kept as separate responsibilities.

Python loads the native engine through the versioned C interface. Engine
identities and revisions may be stored in Blender data, but Blender objects and
pointers never enter engine schemas.

The in-process input provider reads Blender events only. It does not forward
events from the Realtime Plane, which owns its own input source.

The Python implementations are packaged under `extension/host/`. Blender UI
classes live under `extension/presentation/`. The
[package map](../../../docs/PACKAGE_MAP.md) gives the exact mapping.

## Public and private layout

Native files are divided by whether another target may include them:

- `public/` contains exported headers. It is empty today.
- `private/` contains internal headers and source files.

CMake exposes only `public/` to consumers.
