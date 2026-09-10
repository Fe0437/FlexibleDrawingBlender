# Package map

The extension is split by the boundary each package owns.

| Path | Responsibility | May depend on |
|---|---|---|
| `extension/presentation` (`presentation.blender`) | Native Blender toolbar, dockable panels/properties, resource/layer views, node-editor projection, operators, and registration | Shared UI schema, `extension/host`, `extension/abi`, Blender Python API |
| `extension/host` | Conversion between Blender events or data and host-neutral values | Plain Python data and Blender Python API |
| `extension/abi` | Loading and calling the versioned native C ABI | Python standard library and generated ABI descriptions |
| `fd_plugin` | Native composition and Blender-only implementation boundaries | Flexible Drawing application, presentation, host, and canvas contracts |
| `fd_plugin/usd` | Blender USD compatibility boundary | Blender host boundary and the shared USD compatibility contract |
| `fd_plugin/hydra` | Blender Hydra rendering boundary | Blender host boundary and the shared Hydra contract |

`extension/abi` must remain importable without `bpy`. The package is the seam
used by Python-only contract tests and by Blender at runtime.

The native targets under `fd_plugin` are prepared boundaries unless their
source directory contains an implementation. A target name is not evidence
that the feature is available.

LightPHI, LightRHI, SDL, and Realtime Plane packages are outside this
application. Do not add them to this dependency graph.

The node editor projects core-owned authored graph data. It sends semantic
actions and follows accepted revisions; a Blender `NodeTree` is never the
source of truth. Realtime Plane control is asynchronous state synchronization,
not an input or rendering dependency.
