# Test strategy

The extension is tested at three boundaries.

## Python contract tests

Plain Python tests cover ABI table loading, value conversion, and behavior when
the native library is absent or incompatible. These tests must not require
`bpy`; that requirement keeps the ABI seam independently testable.

## Packaged extension tests

Blender validates the generated archive. Lifecycle tests repeatedly register
and unregister the extension with an isolated user profile. They catch stale
handlers, leaked callbacks, and import-order dependencies.

## Interactive host test

The paint interaction test runs through Blender's real event loop. It verifies
operator registration, editor events, receiver calls, and clean shutdown. It is
the required test for changes to UI, tools, windows, or Blender event handling.

Presentation tests also verify native toolbar, panel, property, resource,
layer, and node-editor projections against the shared semantic contract. A
Blender `NodeTree` edit is not considered active until the engine returns the
accepted graph revision. External Realtime Plane tests introduce slow and
disconnected peers and prove that UI state remains asynchronous and never
enters the pen-to-photon path.

The current Blender canvas provider acknowledges revisions but does not display
paint. Tests must not claim visible rendering until that provider is
implemented.

Use `just blender-test /path/to/blender debug` for the complete extension gate.
If Blender fails before loading the extension, report that host failure
separately from an extension failure.
