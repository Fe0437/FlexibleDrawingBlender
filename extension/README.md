# Flexible Drawing for Blender

This extension lets Blender load and control the Flexible Drawing engine.
Blender supplies the user interface, pointer events, and host data. The native
engine owns drawing documents and processes strokes.

Use the [glossary](../../../docs/GLOSSARY.md) for the meaning of
*document*, *tool*, *stroke*, *brush*, *dab*, *canvas*, and *receiver*.

## What works today

The extension can:

- start and stop the native engine;
- create a document and save its identity in a `.blend` file;
- open an Image Editor or 3D View in a separate window;
- capture a freehand stroke in the Image Editor;
- send measured and coalesced input to the engine;
- report the canvas revision accepted by the receiver.

The current canvas records changed tiles but does not create or display pixels.
A stroke therefore changes the revision shown in the sidebar without drawing
paint under the pointer. Pointer input in the 3D View is also not implemented.

## Build and open the extension

```sh
just debug
just blender-test /path/to/blender debug
```

For a manual run:

```sh
just blender-package debug
/path/to/blender --python-expr "
import sys; sys.path.insert(0, 'build/debug/blender-extension')
import flexible_drawing; flexible_drawing.register()
"
```

In Blender, open **Properties → Scene → Flexible Drawing** and choose
**Create Flexible Drawing**. Then open the 2D canvas or 3D viewport.

To submit a stroke, choose **Flexible Drawing** in the Image Editor toolbar and
drag. Tablet positions saved between Blender events are sent with the measured
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

## Package map

| Module | Responsibility |
| --- | --- |
| `__init__.py` | Starts and stops the extension and its single engine. |
| `presentation/document.py` | Document buttons and the Scene properties panel. |
| `presentation/viewport.py` | Viewport window controls and sidebars. |
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
