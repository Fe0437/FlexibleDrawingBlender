# Architecture

The Blender extension is a composition root. Blender owns its windows, event
loop, data blocks, and UI. The native engine owns drawing documents and engine
workflows. They meet through the versioned plain C interface.

```text
Blender UI
    -> Blender host adapters
    -> Python ABI client
    -> Flexible Drawing C ABI
    -> engine application and core packages
```

`extension/presentation` is the `presentation.blender` frontend. It owns native
Blender operators, workspace toolbar tools, dockable panels, properties,
resource and layer views, and the custom node-editor projection. It renders the
platform-independent UI schema using Blender widgets; it does not own document
or graph rules. The schema binds to state, actions, and capabilities owned by
their existing packages.
`extension/host` translates Blender events and persistent data into host-neutral
values. `extension/abi` loads and calls the native library and never imports
`bpy`. `fd_plugin` reserves native implementation boundaries that belong only
to this application.

A Blender `NodeTree` is an editor and projection of the engine's core-owned
authored graph data. Blender data blocks may retain binding identity and the
last observed revision, but they are not the authoritative graph. Node edits
invoke graph actions referenced by the UI schema; the projection updates from
the accepted graph revision and view state.

The in-process extension does not import the Realtime Plane, LightPHI, or
LightRHI. Process control uses asynchronous revisioned actions and state
updates. Raw pen samples, prediction, active runtime snapshots, GPU canvas work,
tile residency/compositing, and canvas-local overlays remain in the Realtime
Plane. Blender never waits in that process's pen-to-photon path.

For a tool or parameter change, Blender may display pending intent. The context
that receives the input applies the change locally at a safe boundary and
publishes the effective revision. Blender updates the active state only from
that revision; a delayed or disconnected peer cannot stall drawing.

Document and receiver handles are engine-owned. Blender stores stable identity
values, not native pointers. A host must stop using every table and handle after
the engine shuts down.
