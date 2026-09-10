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
- `extension/presentation/` defines Blender operators and panels;
- `extension/abi/` calls the native engine and never imports Blender;
- `fd_plugin/` owns the native Blender-specific integration boundaries.

The planned Realtime Plane is a separate process. It will read pen input and
present its own canvas. A later integration will define the public Blender-side
process-control contract. This repository does not import the private Realtime
Plane source or enter its per-sample drawing path.

## Licence and distribution

The official Blender extension and its Python bridge are distributed under
`GPL-3.0-or-later`. The full licence text is in [`LICENSE`](LICENSE). The native
engine loaded into Blender is supplied by the parent Flexible Drawing project
under its GPL distribution terms.

Distributed binaries must be accompanied by the corresponding source as
required by the GPL. Paid builds, support, training, and commissioned work do
not change those terms. The parent project's `LICENSING.md` is authoritative
for distributions that combine this extension with its native engine.
