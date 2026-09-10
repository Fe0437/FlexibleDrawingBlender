# Developer commands

Run these commands from the parent Flexible Drawing checkout.

Build an unpacked extension and a distributable archive:

```sh
just blender-package debug
```

The outputs are under `build/debug/blender-extension` and
`build/debug/flexible_drawing-0.1.0-macos-arm64.zip`.

Run validation, lifecycle checks, incompatible-runtime checks, and the
interactive paint path against a Blender executable:

```sh
just blender-test /path/to/blender debug
```

For a manual development run, place the unpacked extension on Python's path and
register it:

```sh
/path/to/blender --python-expr "
import sys; sys.path.insert(0, 'build/debug/blender-extension')
import flexible_drawing; flexible_drawing.register()
"
```

Open **Properties -> Scene -> Flexible Drawing**, create a document, open the
2D canvas, select the Flexible Drawing tool in the Image Editor, and drag.

Run `just debug-smoke` for the parent repository's fast native and Python
checks. Run `just generate-docs` after changing these pages.
