# Manual checks

Some checks draw in the real Realtime Plane window. Each one is a saved script
that takes `--input synthetic` or `--input person`:

- **synthetic** posts pointer events to the operating system, as a mouse
  would. It needs no one at the machine, so it runs with the other tests
  (`just debug-test`, or `ctest -L drawing`). It needs macOS, Accessibility
  permission for the terminal that runs it, and an unlocked screen; without
  them it is skipped, not failed. Before every stroke it brings the Realtime
  Plane window to the front and checks the stroke starts on that window, so
  it never draws in another one; leave the computer alone while it runs.
- **person** asks you to draw, and waits until you press Enter. Use it to check
  a real pen: pressure, tilt and a real hand are what synthetic events cannot
  give.

Both modes check the same things and report the same numbers.

## Canvas in Blender

It is the last step of `just blender-test`:

```sh
just blender-test /path/to/blender debug              # posted pointer events
just blender-test /path/to/blender debug person       # you draw
```

`just debug-test` runs its synthetic form too. It packages the extension with
the real Realtime Plane, installs it in a throwaway Blender profile, and runs
two Blender processes in the background.
The Realtime Plane window opens; draw in it when asked:

1. two short strokes;
2. one long stroke, about three seconds.

It then checks, with no further input:

- every tile of the Blender image holds exactly the pixels the Realtime Plane
  sent, and a render of the bound material matches the image;
- during the long stroke the image never waits more than 0.25 s between updates;
- a second Blender opens the saved file, finds the Realtime Plane still
  running, and rebuilds the image to the same hash without another stroke;
  then again after the image is deleted.

Each `just blender-test` run adds one line to
`.private/manual-checks/canvas-check-results.jsonl`.
It names the machine's input, so it stays private and is never committed.
`--keep DIR` on the script keeps the saved file and the render for a failure.

## Tools in Blender

`flexible_drawing.blender_tool_check` checks the packaged extension and real Realtime Plane:

1. Blender selects the marker. One continuous, self-crossing contact must have the same 0.5 alpha
   at its crossing and along both arms in Blender's image.
2. A mouse move without any button shows the tool's hover point in a screenshot of the Realtime
   Plane. Blender's image hash must stay the same.
3. Blender selects the pen. Without another pointer event, a new screenshot must show the old
   hover point gone, and Blender's image hash must still stay the same.

Configure with `BLENDER_PLUGIN_INTERACTIVE=ON`, a supported `BLENDER_PLUGIN_EXECUTABLE` and
`BLENDER_PLUGIN_WHEEL_DIR`, and build the Realtime Plane and host ABI library first. Only run with
someone present who has agreed to give the test the unlocked desktop and pointer:

```sh
ctest --test-dir /path/to/own/build -R '^flexible_drawing.blender_tool_check$' --output-on-failure
```

Grant Accessibility and Screen Recording to the terminal that starts the check in macOS System
Settings. The check never opens permission dialogs; missing permissions or a locked screen skip
with code 77. The system pointer is excluded from screenshots, so it cannot stand in for the
preview. The CTest result and `blender_tool_check_artifacts/exchange` under the test's build folder
keep the alpha samples, image hash, marker image, three screenshots and Blender stdout for review.
Reusing that artifact folder clears this check's old handshakes and evidence before launch.

`flexible_drawing.blender_tool_check_contract` checks the event sequence, permission skip and image
verdicts without opening any window or posting input. It runs without Blender installed.

## Latency

`apps/blender_plugin/tests/test_realtime_plane_latency.py` takes the same
`--input`. Its synthetic form is a performance test: `just perf-test` runs it,
with the other slow tests, on an optimized build with measurement compiled in.
