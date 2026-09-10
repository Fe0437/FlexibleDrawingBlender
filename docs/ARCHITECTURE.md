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
`bpy`. `extension/realtime_plane` is the client of the external Realtime Plane:
it starts or finds the process, keeps a session with it over the shared profile,
and never imports `bpy` either. `fd_plugin` reserves native implementation
boundaries that belong only to this application.

The panels and properties for tool settings are not written by hand. The
engine describes its UI through the C interface, and `presentation` makes one
panel per surface and section and one widget per control role from that
description, so a control the engine adds appears in Blender unchanged. Each
widget requests the action its binding names from the binding target and shows
the state its binding names.

The Realtime Plane outlives Blender. Its process runs in a session of its own,
under service names fixed per user and a per-user state file that records it;
Blender attaches to it at startup when it is running, lets go of it when the
add-on is disabled or Blender quits, and ends it only when a person stops the
canvas.

A Blender `NodeTree` is an editor and projection of the engine's core-owned
authored graph data. Blender data blocks may retain binding identity and the
last observed revision, but they are not the authoritative graph. Node edits
invoke graph actions referenced by the UI schema; the projection updates from
the accepted graph revision and view state.

The in-process extension does not import the Realtime Plane's code, LightPHI,
or LightRHI; it speaks to the Realtime Plane only through the shared profile. Process control uses asynchronous revisioned actions and state
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
