"""The host-neutral client of the Realtime Plane, the external canvas with its own window and pen.

A host holds one `RealtimePlaneLink`. It starts or finds the process, keeps a session open with it,
sends the actions the shared UI schema names, and keeps the tool state and canvas it reports. The
host never sends pen input: the Realtime Plane reads the pen itself.

    link         the process and a session that keeps coming back; what a host holds
      ├── session     one session: actions out, tool state and tile results in, never waiting
      ├── channels    the iceoryx2 ports a session talks through
      ├── process     start, find and stop the process, with a state file that outlives the host
      └── profile     the protocol's own Python modules, loaded from beside this package

Nothing here imports `bpy`, so the same code serves any Python host and is tested without Blender.
"""
