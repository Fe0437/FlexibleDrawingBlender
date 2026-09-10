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

For a manual development run, install the packaged extension in an isolated
Blender profile. This also installs its declared wheels:

```sh
export BLENDER_USER_CONFIG="$PWD/build/debug/manual-blender-profile/config"
export BLENDER_USER_SCRIPTS="$PWD/build/debug/manual-blender-profile/scripts"
export BLENDER_USER_EXTENSIONS="$PWD/build/debug/manual-blender-profile/extensions"
export BLENDER_USER_DATAFILES="$PWD/build/debug/manual-blender-profile/datafiles"
/path/to/blender --background --factory-startup --command extension install-file \
  -r user_default -e build/debug/flexible_drawing-0.1.0-macos-arm64.zip
/path/to/blender
```

Open **Properties -> Scene -> Flexible Drawing**, create a document, open the
2D canvas, select the Flexible Drawing tool in the Image Editor, and drag.

Run `just debug-smoke` for the parent repository's fast native and Python
checks. Run `just generate-docs` after changing these pages.
