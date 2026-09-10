# Flexible Drawing for Blender

This extension lets Blender load and control the Flexible Drawing engine.
Blender supplies the user interface, pointer events, and host data. The native
engine owns drawing documents and processes strokes.

Use the [glossary](../../../docs/GLOSSARY.md) for the meaning of
*document*, *tool*, *stroke*, *brush*, *dab*, *canvas*, and *receiver*.

## What works today

The extension can:

- start and stop the native engine;
- open the canvas: start the Realtime Plane, the external window that reads the
  pen itself, or find the one already running, and stop it on request;
- show the engine's tool settings in **Properties → Scene**, change them, and
  mark each change as pending until the Realtime Plane reports it in effect;
- create a document and save its identity in a `.blend` file;
- as an optional in-process alternative, paint in a Blender Image Editor or 3D
  View window and report the canvas revision accepted by the receiver.

The Realtime Plane outlives Blender. Quitting Blender, or Blender crashing,
leaves it painting; the next Blender finds it again. Only **Stop Canvas** ends
it. A tool chosen in Blender takes effect when the pen next touches the canvas,
because a stroke keeps the tool it started with; until then it shows as pending.

The in-process canvas records changed tiles but does not create or display
pixels, and pointer input in the 3D View is not implemented.

## Build and open the extension

```sh
just debug
just blender-test /path/to/blender debug
```

For a manual run, install and enable the package in a dedicated profile:

```sh
just blender-package debug
export BLENDER_USER_CONFIG="$PWD/build/debug/manual-blender-profile/config"
export BLENDER_USER_SCRIPTS="$PWD/build/debug/manual-blender-profile/scripts"
export BLENDER_USER_EXTENSIONS="$PWD/build/debug/manual-blender-profile/extensions"
export BLENDER_USER_DATAFILES="$PWD/build/debug/manual-blender-profile/datafiles"
/path/to/blender --background --factory-startup --command extension install-file \
  -r user_default -e build/debug/flexible_drawing-0.1.0-macos-arm64.zip
/path/to/blender
```

In Blender, open **Properties → Scene → Flexible Drawing** and choose **Open
Canvas**. The Realtime Plane window opens; draw in it with the pen. Expand the
**Painting** panel inside **Flexible Drawing** to see the active tool, its effective settings and
any requested value that is still pending.

`just blender-package` puts the Realtime Plane, its libraries and shaders, and
the iceoryx2 wheels in the package. Blender's extension manager installs those
wheels when it installs the package. Manual and debugger sessions use that same
installation path.

To paint inside Blender instead, choose **Blender Image Editor (in-process)**,
then **Flexible Drawing** in the Image Editor toolbar, and drag. Tablet positions saved between Blender events are sent with the measured
position that follows them, so the extension crosses the native boundary once
for a group of samples rather than once for every position.

Blender creates sidebar tabs only after an editor has drawn once. A newly
opened window may therefore need a short moment before the Flexible Drawing tab
appears.

## Use a library from an existing build

During native development, point the extension at a built library:

```sh
export FLEXIBLE_DRAWING_ENGINE_LIBRARY=build/debug/src/host/abi/libflexible_drawing_engine.dylib
```

Other development switches:

| Setting | Effect |
| --- | --- |
| Preference **Realtime Plane executable** | Run this Realtime Plane instead of the bundled one. |
| `FLEXIBLE_DRAWING_REALTIME_PLANE_COMMAND` | Run this whole command line as the Realtime Plane, such as a test stand-in. |
| `FLEXIBLE_DRAWING_REALTIME_PLANE_SCOPE` | Use another Realtime Plane than the user's own: other service names and state file. |
| `FLEXIBLE_DRAWING_PROTOCOL_DIR` | Load the Realtime Plane profile from a source checkout instead of the package. |

## Call the engine from Python

The `abi/` package contains no `bpy` import, so it can also be used from a plain
Python process:

```python
from flexible_drawing.abi import EngineBridge, FD_RECEIVER_ORIGIN_MEASURED

with EngineBridge.Open(log=print) as engine:
    document = engine.Documents.Create("Untitled")

    receiver = engine.Receivers.Create(
        seed=42,
        tileExtent=64,
        maximumBatchSamples=64,
    )
    engine.Receivers.BeginContact(receiver.ReceiverId, contactId=1)

    batch = engine.Receivers.Batch()
    batch.Append(
        x=0.0,
        y=0.0,
        pressure=0.5,
        timeNanoseconds=1,
        sequence=1,
        origin=FD_RECEIVER_ORIGIN_MEASURED,
    )
    result = engine.Receivers.Submit(receiver.ReceiverId, 1, 1, batch)

    print(result.Revision, result.CommittedSequence)
    engine.Receivers.EndContact(receiver.ReceiverId, 1)
    engine.Documents.Close(document.DocumentId)
```

`EngineBridge.Open` finds the library, checks its version, starts an engine, and
connects its interfaces. Leaving the `with` block shuts the engine down.

Important rules:

- Do not call an interface after its engine has shut down.
- A failed call raises `EngineError`; `EngineError.Status` contains the native
  status code when the call reached the engine.
- Send input in batches. Reuse one batch and call `Clear` between submissions.
- Only `x` and `y` are required. Omitted pressure, time, sequence, and origin
  use the defaults documented by the C interface.
- `InputBatch.Borrowing` lets the engine read compatible buffers that the host
  already owns. The engine does not retain those buffers after the call.
- A receiver is one painting session, and a contact is one stroke within that
  session. Open and close both explicitly.
- A receiver cannot yet target a document or layer. Do not make persistent
  behavior depend on this temporary limitation.

## Drive the Realtime Plane from Python

The `realtime_plane/` package contains no `bpy` import either. A host holds one
link, calls `Advance` from a timer, and never waits:

```python
from pathlib import Path

from flexible_drawing.realtime_plane.link import RealtimePlaneLink
from flexible_drawing.realtime_plane.process import BundledProgram

# Where `just blender-package debug` unpacks the Realtime Plane the extension carries.
bundled = Path("build/debug/blender-extension/flexible_drawing/realtime_plane/bin")
link = RealtimePlaneLink(lambda: BundledProgram(bundled))
link.Open()  # finds the running Realtime Plane, or starts it
link.Request("presentation.tool_ui", "pressure_brush.set_hardness", 0.8)
while link.Pending("presentation.tool_ui", "pressure_brush.set_hardness") is not None:
    link.Advance()  # from the host's timer, in a real host
print(link.Effective("presentation.tool_ui", "pressure_brush.hardness"))  # 0.8
link.Detach()  # the Realtime Plane keeps running; link.Stop() would end it
```

Important rules:

- Send actions by the owner and identity the UI schema's bindings give. The
  extension never names a control itself.
- A request is pending until a tool state reports it applied. Show both values.
- Call `Advance` often. A session the Realtime Plane closes, or one that stops
  answering, is replaced by a new one on its own; requests not yet applied are
  dropped with it.
- `Detach` when the host stops; `Stop` only when a person asks.

## Package map

| Module | Responsibility |
| --- | --- |
| `__init__.py` | Starts and stops the extension, its single engine and its Realtime Plane link. |
| `presentation/document.py` | Canvas and document buttons and the Scene properties panel. |
| `presentation/realtime_plane.py` | Open and Stop Canvas, the preference, and the timer that follows the link. |
| `presentation/ui_projection.py` | Panels and properties made from the engine's UI schema. |
| `presentation/viewport.py` | Optional in-process viewport windows and sidebars. |
| `presentation/stroke.py` | Freehand operator and Image Editor toolbar tool. |
| `host/document_binding.py` | Stores engine document identity in Blender data. |
| `host/input.py` | Converts one Blender event to engine input values. |
| `host/input_source.py` | Collects and submits one contact in bounded batches. |
| `host/receiver_binding.py` | Owns the painting receiver associated with a scene. |
| `host/viewport.py` | Opens editor windows and converts 2D pointer coordinates. |
| `host/geometry.py` | Converts Blender geometry to and from plain buffers. |
| `host/geometry_sync.py` | Tracks changed geometry regions and revisions. |
| `host/usd.py` | Checks Blender's bundled OpenUSD installation. |
| `host/hydra.py` | Registers the Hydra renderers exposed by Blender. |
| `abi/` | Loads and calls the native C interface without importing Blender. |
| `realtime_plane/` | Starts, finds and talks to the Realtime Plane without importing Blender. |

## Geometry synchronization regions

A geometry synchronization region is a caller-chosen part of Blender geometry
that is captured and committed as one unit. It may be a whole object, one mesh
tile, or another stable subdivision. It is not required to be a rectangle or a
bounding box.

The caller gives each region a string key that remains stable while the region
is tracked. Keys must be unique within one `GeometrySyncState`. A committed
snapshot must contain all and only the content assigned to that key.

`RegionState.Id` identifies the region only inside its tracker. `Revision`
counts commits. `ContentHash` is present only when optional verification is
enabled.

The native interface is documented in
[The C interface](../../../src/host/abi/README.md).
