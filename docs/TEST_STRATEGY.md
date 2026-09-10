# Test strategy

The extension is tested at three boundaries.

## Python contract tests

Plain Python tests cover ABI table loading, value conversion, and behavior when
the native library is absent or incompatible. These tests must not require
`bpy`; that requirement keeps the ABI seam independently testable.

The Realtime Plane client is tested the same way. Its session rules run against
scripted channels: records of a replaced session are dropped, records out of
order and a Realtime Plane that stops answering end the session, requests stay
within the actions window, and a request made again before it was sent replaces
it. The whole link then runs against a Realtime Plane that paints with a fake
pen and needs no window (the Realtime Plane's host-session peer behind the
Realtime Plane's command line): repeated open and close, a crashed Realtime
Plane, a crashed host, a replaced session, pending and effective values, and a
slow host following a long stroke.

The projected UI is tested with a fake Blender and a fake binding target: a
widget for every control role, a panel for every surface and section, actions
requested through their bindings, pending beside effective values, and the
labels that tell the external canvas from the optional in-process one. A
dependency audit reads every import: `abi/` and `realtime_plane/` never import
`bpy`, nothing imports LightRHI, and nothing on the Realtime Plane's path
touches Blender's pointer input.

## Packaged extension tests

Blender validates the generated archive. Lifecycle tests repeatedly register
and unregister the extension with an isolated user profile. They catch stale
handlers, leaked callbacks, and import-order dependencies.

When binary Python wheels are supplied, the package test verifies that the
archive contains the wheels and their licence notices, declares the wheels in
its manifest, and passes Blender's extension validator.

The Realtime Plane session test packages the extension, installs it into a
throwaway Blender profile, and drives it in background Blender against the
same fake-pen Realtime Plane: Open Canvas, a setting changed through the
property Blender made from the schema, a tool change, the add-on disabled and
enabled again reattaching to the same process, and Stop Canvas ending it.

## Interactive host test

The paint interaction test runs through Blender's real event loop. It verifies
operator registration, editor events, receiver calls, and clean shutdown. It is
the required test for changes to UI, tools, windows, or Blender event handling.

The Realtime Plane launch test runs the same Blender script with a window and
the real Realtime Plane the package carries. A tool choice stays pending there,
because no pen touches the canvas and a tool is adopted when the next stroke
begins.

Presentation tests also verify native toolbar, panel, property, resource,
layer, and node-editor projections against the shared semantic contract. A
Blender `NodeTree` edit is not considered active until the engine returns the
accepted graph revision. The Realtime Plane repository owns transport and
external-process tests.

The current Blender canvas provider acknowledges revisions but does not display
paint. Tests must not claim visible rendering until that provider is
implemented.

Use `just blender-test /path/to/blender debug` for the complete extension gate.
If Blender fails before loading the extension, report that host failure
separately from an extension failure.
