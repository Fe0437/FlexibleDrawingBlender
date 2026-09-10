"""The Flexible Drawing profile of the Realtime Interaction Protocol, loaded for this extension.

The profile's Python modules belong to the protocol, not to Blender: the Realtime Plane's own tests
use the same files. The package carries them under `protocol/`, beside the TOML both ends read their
limits from, and this module loads them from there under the extension's own package name, so
nothing is added to `sys.path` and two extensions can never see each other's copy.

`FLEXIBLE_DRAWING_PROTOCOL_DIR` points at another profile directory, which is how the extension runs
from a source checkout before it is packaged.

```python
from flexible_drawing.realtime_plane.profile import Frames, Profile

action = Profile.ValueAction("presentation.tool_ui", "pressure_brush.set_hardness", 0.8)
settings = Profile.SETTINGS
frame = Frames.EncodeRecord(
    session, settings.Actions.Stream, 1, 0, settings.ValueActionPayload, Profile.EncodeValueAction(action)
)
```
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType

#: Where a source checkout keeps the profile; the package puts the same files beside this module.
PROTOCOL_DIRECTORY_VARIABLE = "FLEXIBLE_DRAWING_PROTOCOL_DIR"


def ProtocolDirectory() -> Path:
    """The directory holding `realtime_plane_protocol.toml` and its `python/` modules."""
    override = os.environ.get(PROTOCOL_DIRECTORY_VARIABLE)
    return Path(override) if override else Path(__file__).with_name("protocol")


def _load(name: str) -> ModuleType:
    path = ProtocolDirectory() / "python" / f"{name}.py"
    if not path.is_file():
        raise ImportError(f"the Realtime Plane profile is missing: {path}", path=str(path))
    qualified = f"{__package__}.{name}"
    spec = importlib.util.spec_from_file_location(qualified, path)
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs, as an import would: its named tuples look their module up by name.
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


#: Session, record and acknowledgement frames.
Frames = _load("realtime_interaction_frames")
#: Payloads, stream limits and the canvas mirror both ends agree on.
Profile = _load("realtime_plane_protocol")
