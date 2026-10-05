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
requested through their bindings, and pending beside effective values. A
dependency audit reads every import: `abi/` and `realtime_plane/` never import
`bpy`, and nothing imports LightRHI.

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

## Canvas image tests

`flexible_drawing.blender_image_projection` runs without Blender. Tiles go
through the real profile codec and `CanvasMirror` into the image projection:
pixels, colour and alpha land bottom row first as a Blender image keeps them, a
tile hanging over the edge is cut, only changed tiles are written, an older
revision never replaces a newer one, and another image size starts a new image
with every tile.

Inside Blender, the Realtime Plane session test waits until the canvas image
holds exactly the pixels the session received, checks that it is one float,
premultiplied, linear image of the canvas's size, and that reattaching and
disabling the add-on keep it one image and leave no timer running. It then
binds the canvas into a plane's material and checks the node feeds base colour
and alpha, binding twice adds no node, and the material keeps showing exactly
the received pixels while the mesh is edited, after the object is deleted,
after the image is deleted, and after the file is saved and reopened.

## Interactive host test

The Realtime Plane launch test runs Blender with a window and the real Realtime
Plane the package carries. A tool choice stays pending there,
because no pen touches the canvas and a tool is adopted when the next stroke
begins.

Presentation tests also verify native toolbar, panel, property, resource,
layer, and node-editor projections against the shared semantic contract. A
Blender `NodeTree` edit is not considered active until the engine returns the
accepted graph revision. The Realtime Plane repository owns transport and
external-process tests.

Use `just blender-test /path/to/blender debug` for the complete extension gate.
If Blender fails before loading the extension, report that host failure
separately from an extension failure.

## Realtime Plane latency comparison

`flexible_drawing.realtime_plane_latency` runs the same Realtime Plane build in
three ways, taking turns: on its own, launched and controlled by Blender, and
launched by a Blender that then stops taking host turns. Pointer events posted
to the operating system draw the same strokes in each. At exit the Realtime
Plane writes how long each local stage took (`--latency-report`); the test
merges every run and judges the result against
`tests/realtime_plane_latency_budget.json`, which was written before the
comparison it judges:

- equivalence: Blender's p50 may exceed the direct p50 by 5% plus 0.5 ms, and
  its p99 the direct p99 by 10% plus 1 ms. The relative part keeps the rule
  fair on a faster or slower path; the fixed part is far below a delay a person
  can feel while drawing, and covers the scheduler's own noise when the stage
  is very short;
- regression: on the hardware, display, presentation, input and build the
  budget names, the direct p50 and p99 may not exceed the largest value of any
  baseline run by more than 10%, rounded up;
- control to activation: Blender's request for a new brush hardness must be
  reported in effect within 34 ms at p99, two of Blender's 60 Hz host turns.

The `blender_stalled` way is the proof that Blender cannot stall the path: it
is judged by the same equivalence rule while Blender answers nothing. The
Realtime Plane's own provider-boundary test proves the other half, that no
transport or IPC code is compiled into the pen-to-photon sources.

It is a `performance` test: `just perf-test` runs it on the `profile` build. It
needs a process allowed to post events (macOS: Accessibility) and an unlocked
screen; otherwise it skips. Its numbers are kept in `realtime_plane_latency.json` in the build tree;
on other hardware, where the regression limits are not judged, that file is the
baseline to derive a new budget from. Only a build with `METRICS_ENABLED` compiles the measurement; the regression
limits were recorded on the `profile` build that `just perf-test` uses.

## Canvas in Blender

`flexible_drawing.blender_canvas_check` draws in the real Realtime Plane,
packaged with the extension, with posted pointer events, and runs two Blender
processes: the image and every tile of it must hold exactly the pixels
received, a render of the bound material must match the image, the image must
update during a long stroke without waiting more than 0.25 s, and a second
Blender, opening the saved file, must rebuild the image to the same hash from
the Realtime Plane still running, also after the image is deleted. It runs with
`just debug-test`, alone, and skips where posted events reach no window. The
same script draws with a person instead: see [Manual checks](MANUAL_CHECKS.md).
