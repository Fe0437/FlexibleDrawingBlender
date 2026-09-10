"""Track region-scoped Blender geometry synchronization.

Blender's dependency graph reports which datablocks changed and whether the change was to geometry
or only to a transform. `GeometrySyncState` records that signal so callers only capture geometry
that moved.

A **region** in this module is one caller-defined synchronization partition of Blender geometry.
It is the smallest piece the caller can mark dirty, capture as one `GeometrySnapshot`, and commit
atomically. A region may be a whole Blender object, one mesh tile, or another stable subdivision.
The tracker does not infer its bounds or membership.

The caller names each region with an opaque string key. The key must stay stable for as long as the
same partition is tracked and must be unique within one `GeometrySyncState`. When one tracker covers
several Blender objects, the key must include enough stable object and subdivision identity to avoid
collisions. The caller also owns the mapping from that key to the Blender data captured on commit.

This host synchronization region is not `core.region.RectI` or `core.region.Box3d`. Those types
describe spatial bounds. A synchronization region describes update granularity and may later carry
one of those bounds as metadata, but no spatial extent is represented here today.

```python
sync = GeometrySyncState()

def OnDepsgraphUpdate(scene, depsgraph):
    for update in depsgraph.updates:
        if update.is_updated_geometry:
            sync.MarkChanged(RegionOf(update.id))

for region in sync.ChangedRegions():
    snapshot = SnapshotObject(ObjectOf(region))
    sync.Commit(region, snapshot)
```

A region keeps the same tracker-local `Id` across commits and advances its `Revision` once per
commit. Set
`FLEXIBLE_DRAWING_VERIFY_GEOMETRY=1` to hash committed snapshots and warn when Blender's change
signal is too broad or misses a content change. Verification is off by default because hashing the
geometry would add the cost this tracking avoids.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os

from .geometry import GeometrySnapshot

_logger = logging.getLogger("flexible_drawing")

# Hashing every vertex on every commit is the cost this tracking exists to avoid, so it is off
# unless someone asks for it while working on the tracking itself.
VERIFY_GEOMETRY = os.environ.get("FLEXIBLE_DRAWING_VERIFY_GEOMETRY") == "1"


def _digest(snapshot: GeometrySnapshot) -> str:
    """Return a stable content hash used only when verification is enabled."""
    running = hashlib.sha256(f"{snapshot.Kind}/{snapshot.SourceCapability}".encode())
    running.update(memoryview(snapshot.Vertices).cast("B"))
    running.update(memoryview(snapshot.Triangles).cast("B"))
    return running.hexdigest()


@dataclass(frozen=True)
class RegionState:
    """Recorded synchronization state for one caller-defined geometry partition.

    The region itself is identified to `GeometrySyncState` by the caller's string key. This record
    does not contain that key or any geometric bounds. It only contains the tracker-assigned state
    returned after a commit.

    `Id` is unique within one `GeometrySyncState` and stable until that tracker is discarded. It is
    not persistent and must not be stored as document or Blender identity. `Revision` starts at one
    and advances on every commit, even when verification finds identical content. `ContentHash` is
    a SHA-256 digest only when verification is enabled; otherwise it is the empty string and must
    not be used as content identity.
    """

    Id: int  #: Tracker-local identity assigned on the first commit.
    Revision: int  #: Number of snapshots committed for this region key.
    ContentHash: str  #: Verification digest, or an empty string when verification is disabled.


class GeometrySyncState:
    """Track dirty and committed state for caller-defined geometry partitions.

    String keys are opaque to this class. A key names exactly one partition for the lifetime of the
    tracker, and the snapshot passed to `Commit` must contain that partition's complete content.
    """

    def __init__(self, verify: bool | None = None) -> None:
        self._regions: dict[str, RegionState] = {}
        self._changed: set[str] = set()
        self._nextId = 1
        self._verify = VERIFY_GEOMETRY if verify is None else verify

    def MarkChanged(self, regionKey: str) -> None:
        """Mark the partition named by `regionKey` for recapture.

        Repeating the same key is idempotent. This method records only the signal; the caller still
        owns the mapping from the key to the Blender geometry that must be captured.
        """
        self._changed.add(regionKey)

    def ChangedRegions(self) -> tuple[str, ...]:
        """Return dirty region keys sorted so processing order is deterministic."""
        return tuple(sorted(self._changed))

    def Changed(self, regionKey: str) -> bool:
        """Return whether the named partition needs capture.

        A key never committed returns true because no snapshot exists for that partition yet.
        """
        return regionKey in self._changed or regionKey not in self._regions

    def Commit(self, regionKey: str, snapshot: GeometrySnapshot) -> RegionState:
        """Commit the complete snapshot of one partition and return its new state.

        `snapshot` must contain only and all content assigned to `regionKey`. A successful commit
        clears that key's dirty mark and advances its revision.
        """
        previous = self._regions.get(regionKey)
        digest = _digest(snapshot) if self._verify else ""
        if self._verify:
            self._reportTracking(regionKey, previous, digest)
        state = RegionState(
            Id=previous.Id if previous is not None else self._nextId,
            Revision=previous.Revision + 1 if previous is not None else 1,
            ContentHash=digest,
        )
        if previous is None:
            self._nextId += 1
        self._regions[regionKey] = state
        self._changed.discard(regionKey)
        return state

    def Region(self, regionKey: str) -> RegionState:
        """Return the last committed state for the named partition.

        Raises `KeyError` when `regionKey` has never been committed.
        """
        return self._regions[regionKey]

    def _reportTracking(self, regionKey: str, previous: RegionState | None, digest: str) -> None:
        """Warn when the change signal and captured geometry disagree."""
        if previous is None:
            return
        if previous.ContentHash == digest and regionKey in self._changed:
            _logger.warning(
                "[geometry] region '%s' was marked changed but its contents are identical; "
                "the change signal is too broad and this read was not needed",
                regionKey,
            )
        elif previous.ContentHash != digest and regionKey not in self._changed:
            _logger.warning(
                "[geometry] region '%s' changed without being marked; the change signal missed it "
                "and a host relying on it would have shown stale geometry",
                regionKey,
            )
