"""Translate Blender geometry at the host edge.

`SnapshotObject` takes a mesh, curve, hair curves, or grease
pencil object and returns a `GeometrySnapshot`: plain numbers, with no Blender object left in it.
`ApplyMeshVertex` writes a change back.

The numbers are kept in flat buffers — three floats per vertex, one after another — and Blender
fills each buffer in a single call. On a 90k-vertex mesh that measured about fifty times faster than
reading the vertices one at a time, and the buffer can be handed to the engine as it is, with no
second copy to build. Region change tracking lives in `host.geometry_sync`.
"""

from __future__ import annotations

import array
from collections.abc import Iterable
from dataclasses import dataclass
import json

# Blender stores mesh coordinates as 32-bit floats and indices as 32-bit ints, so the buffers match
# it exactly and no conversion happens on the way in.
VERTEX_TYPE = "f"
INDEX_TYPE = "i"


@dataclass(frozen=True)
class GeometrySnapshot:
    """One piece of geometry copied out of Blender. It holds no Blender object.

    Coordinates and indices are kept as flat `array.array` buffers rather than as lists of tuples:
    three floats per vertex, three indices per triangle, one after another. Blender fills those
    buffers in one call, and a flat buffer can be handed straight to the engine without being
    rebuilt, so a mesh is copied once instead of three times.

    Use `VertexCount` and `TriangleCount` rather than `len`, which counts the numbers, not the
    vertices.
    """

    Kind: str
    SourceCapability: str
    #: Three float32 per vertex: x, y, z, x, y, z, ...
    Vertices: array.array
    #: Three int32 per triangle, each an index into Vertices.
    Triangles: array.array

    @property
    def VertexCount(self) -> int:
        """How many vertices this holds."""
        return len(self.Vertices) // 3

    @property
    def TriangleCount(self) -> int:
        """How many triangles this holds."""
        return len(self.Triangles) // 3


def EmptyVertices() -> array.array:
    """An empty vertex buffer, in the layout `GeometrySnapshot.Vertices` uses."""
    return array.array(VERTEX_TYPE)


def EmptyTriangles() -> array.array:
    """An empty triangle buffer, in the layout `GeometrySnapshot.Triangles` uses."""
    return array.array(INDEX_TYPE)


def CapabilityForObjectType(objectType: str) -> str | None:
    """Map a Blender object type to the geometry capability it offers, or None if unsupported."""
    return {"MESH": "MESH", "CURVE": "CURVE", "CURVES": "CURVES", "GREASEPENCIL": "GREASE_PENCIL"}.get(objectType)


def FromCapturedMesh(
    vertices: Iterable[Iterable[float]], triangles: Iterable[Iterable[int]], sourceCapability: str = "MESH"
) -> GeometrySnapshot:
    """Build a snapshot from vertices and triangles given as groups of three.

    For callers that already hold their numbers one at a time. Reading a Blender mesh does not go
    through here: `SnapshotObject` has Blender fill the buffers directly, which is far faster.
    """
    flatVertices = array.array(VERTEX_TYPE)
    for vertex in vertices:
        coordinates = tuple(vertex)
        if len(coordinates) != 3:
            raise ValueError("geometry vertices must contain exactly three coordinates")
        flatVertices.extend(coordinates)
    flatTriangles = array.array(INDEX_TYPE)
    for triangle in triangles:
        indices = tuple(triangle)
        if len(indices) != 3:
            raise ValueError("geometry triangles must contain exactly three indices")
        flatTriangles.extend(indices)
    return _checked(GeometrySnapshot("Mesh", sourceCapability, flatVertices, flatTriangles))


def _checked(snapshot: GeometrySnapshot) -> GeometrySnapshot:
    """Reject geometry the engine cannot represent, whichever way it was captured."""
    if len(snapshot.Vertices) % 3 or len(snapshot.Triangles) % 3:
        raise ValueError("geometry buffers must hold whole vertices and whole triangles")
    if snapshot.Triangles and (min(snapshot.Triangles) < 0 or max(snapshot.Triangles) >= snapshot.VertexCount):
        raise ValueError("geometry triangle index is out of range")
    return snapshot


def SnapshotObject(blenderObject: object) -> GeometrySnapshot:
    """Capture a Blender object as geometry, choosing the reader its type requires."""
    capability = CapabilityForObjectType(blenderObject.type)
    if capability == "MESH":
        mesh = blenderObject.data
        mesh.calc_loop_triangles()
        vertices = _read(mesh.vertices, "co", 3, VERTEX_TYPE)
        triangles = _read(mesh.loop_triangles, "vertices", 3, INDEX_TYPE)
        return _checked(GeometrySnapshot("Mesh", capability, vertices, triangles))
    if capability in {"CURVE", "CURVES"}:
        vertices = array.array(VERTEX_TYPE)
        for spline in blenderObject.data.splines:
            if spline.type == "BEZIER":
                vertices.extend(_read(spline.bezier_points, "co", 3, VERTEX_TYPE))
            else:
                # A non-bezier point carries a weight after its position; keep the first three.
                vertices.extend(_dropWeights(_read(spline.points, "co", 4, VERTEX_TYPE)))
        return _checked(GeometrySnapshot("Curve", capability, vertices, EmptyTriangles()))
    if capability == "GREASE_PENCIL":
        vertices = array.array(VERTEX_TYPE)
        for layer in blenderObject.data.layers:
            for frame in layer.frames:
                position = frame.drawing.attributes.get("position")
                if position is not None:
                    vertices.extend(_read(position.data, "vector", 3, VERTEX_TYPE))
        return _checked(GeometrySnapshot("Curve", capability, vertices, EmptyTriangles()))
    raise ValueError(f"unsupported Blender geometry capability: {blenderObject.type}")


def _read(collection: object, attribute: str, components: int, typecode: str) -> array.array:
    """Have Blender fill one flat buffer in a single call.

    `foreach_get` copies the whole collection at C speed. Reading the same data one element at a
    time builds a Python object per number, which on a 90k-vertex mesh measured about fifty times
    slower.
    """
    buffer = array.array(typecode, bytes(len(collection) * components * array.array(typecode).itemsize))
    collection.foreach_get(attribute, buffer)
    return buffer


def _dropWeights(points: array.array) -> array.array:
    """Turn x, y, z, w groups into x, y, z groups."""
    kept = array.array(VERTEX_TYPE)
    for start in range(0, len(points), 4):
        kept.extend(points[start : start + 3])
    return kept


def ApplyMeshVertex(blenderObject: object, index: int, position: Iterable[float]) -> None:
    """Write one vertex position back to a Blender mesh."""
    if CapabilityForObjectType(blenderObject.type) != "MESH":
        raise ValueError("only Blender mesh vertices can be updated")
    blenderObject.data.vertices[index].co = tuple(float(value) for value in position)
    blenderObject.data.update()


def CreateTileMesh(bpy: object, name: str, tileCount: int) -> object:
    """Build a quad per tile and link it into the scene, so engine output is visible in Blender."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for tile in range(tileCount):
        x = float(tile)
        base = len(vertices)
        vertices.extend(((x, 0.0, 0.0), (x + 1.0, 0.0, 0.0), (x + 1.0, 1.0, 0.0), (x, 1.0, 0.0)))
        faces.append((base, base + 1, base + 2, base + 3))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    geometryObject = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(geometryObject)
    return geometryObject


def TopologyProvenanceSummary(snapshot: GeometrySnapshot, regionCount: int) -> str:
    """Summarize which representation is authoritative, as stable JSON for comparison across runs."""
    return json.dumps(
        {
            "Authority": "Discrete",
            "Kind": snapshot.Kind,
            "RegionCount": regionCount,
            "TriangleCount": snapshot.TriangleCount,
            "VertexCount": snapshot.VertexCount,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
