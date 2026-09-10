# Blender extension

This application lets Blender create and use Flexible Drawing documents. It
loads the native engine, connects Blender input and document state to it, and
registers the user interface shown inside Blender.

Today the extension can start and stop the engine, create and inspect a
document, save its identity in a `.blend` file, open an Image Editor or 3D View
window, and submit a stroke. The current canvas reports changed tiles but does
not display paint yet.

The Python package is arranged by job:

- `extension/__init__.py` starts and stops the extension;
- `extension/host/` reads input and document data from Blender;
- `extension/presentation/` is the native Blender frontend: operators,
  workspace toolbar tools, dockable panels/properties, resource/layer views,
  and the future custom node-editor projection;
- `extension/abi/` calls the native engine and never imports Blender;
- `fd_plugin/` owns the native Blender-specific integration boundaries.

The planned Realtime Plane is a separate process. It reads pen input and
presents its own canvas. Blender controls it with asynchronous revisioned
actions and observes state updates, but does not import its private source or
enter its per-sample drawing path. The Realtime Plane applies tool changes in
the input-owning runtime and acknowledges the effective revision.

Blender UI projects the platform-independent UI schema through native widgets.
The schema references state, actions, and capabilities owned elsewhere. A
Blender `NodeTree` edits the engine's authored graph data but does not replace
it as the source of truth.

## Licence and distribution

The official Blender extension and its Python bridge are distributed under
`GPL-3.0-or-later`. The full licence text is in [`LICENSE`](LICENSE). The native
engine loaded into Blender is supplied by the parent Flexible Drawing project
under its GPL distribution terms.

Distributed binaries must be accompanied by the corresponding source as
required by the GPL. Paid builds, support, training, and commissioned work do
not change those terms. The parent project's `LICENSING.md` is authoritative
for distributions that combine this extension with its native engine.

Start with [`docs/INDEX.md`](docs/INDEX.md) for the application boundary and
build, manual-use, and test instructions.
