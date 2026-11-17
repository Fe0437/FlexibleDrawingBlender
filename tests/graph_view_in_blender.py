"""Check the graph view in a real, background Blender: trees built from the engine, read-only, never saved.

Run by tools/blender/run.py inside Blender with the packaged extension installed. A stand-in binding
target says which tool the pen draws with and records every request, so the test can change the active
tool and prove the view never asks anything of the engine. It prints the success marker last.
"""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import shutil
import sys

import bpy

parser = argparse.ArgumentParser()
parser.add_argument("--module", required=True)
parser.add_argument("--repeat-count", type=int, default=1)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
extension = importlib.import_module(args.module)
presentation = importlib.import_module(f"{args.module}.presentation")
graph_view = importlib.import_module(f"{args.module}.presentation.graph_view")

FIRST, SECOND = "freehand.pressure_brush", "freehand.smudge"


class StandIn:
    """Says which tool is active and offers two; records anything asked of it."""

    Label = "stand-in"
    Available = True
    UnavailableReason = ""

    def __init__(self) -> None:
        self.Active = FIRST
        self.Requests: list[tuple] = []

    def Effective(self, _owner: str, _state: str) -> object:
        return self.Active

    def Choices(self, _owner: str, _state: str) -> tuple[str, ...]:
        return (FIRST, SECOND)

    def Pending(self, _owner: str, _action: str) -> None:
        return None

    def Request(self, *request: object) -> bool:
        self.Requests.append(request)
        return False


def _registeredTreeType() -> object:
    return bpy.types.NodeTree.bl_rna_get_subclass_py(graph_view.TREE_TYPE)


def _matches(tree: object, layout: object) -> None:
    """The tree has one node per box with one socket per port, and one link per edge, as the engine says."""
    boxes = {graph_view._boxName(*graph_view.Identity(box.Box)): box for box in layout.Boxes}
    assert {node.name for node in tree.nodes} == set(boxes), tree.name
    for name, box in boxes.items():
        node = tree.nodes[name]
        ports = {(row.Port.Direction, row.Port.Name) for row in box.Rows if row.Port is not None}
        sockets = {("Output", socket.identifier) for socket in node.outputs} | {
            ("Input", socket.identifier) for socket in node.inputs
        }
        assert sockets == ports, (tree.name, name)
    edges = {
        (
            graph_view._endpointName(edge.Source),
            edge.Source.Port,
            graph_view._endpointName(edge.Destination),
            edge.Destination.Port,
        )
        for edge in layout.Edges
    }
    links = {
        (link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier)
        for link in tree.links
    }
    assert links == edges, tree.name


def _graphs(engine: object, tool: str) -> dict[str, str | None]:
    """Every graph the tool's trees show, the tool's own and each one a node runs, with the graph it is
    opened from."""
    found: dict[str, str | None] = {}
    pending: list[tuple[str, str | None]] = [(tool, None)]
    while pending:
        graph, parent = pending.pop(0)
        if graph in found:
            continue
        found[graph] = parent
        layout = engine.UiSchema.DescribeUiView(graph_view.VIEW, graph)
        pending += [(stage, graph) for _, stage in graph_view.Stages(layout)]
    return found


def _checkTool(engine: object, tool: str) -> None:
    graphs = _graphs(engine, tool)
    assert len(graphs) > 1, f"{tool} has stages"
    trees = {tree.name for tree in graph_view.OwnTrees()}
    assert trees == {graph_view.TreeName(graph) for graph in graphs}, (trees, graphs)
    for graph, parent in graphs.items():
        tree = bpy.data.node_groups[graph_view.TreeName(graph)]
        _matches(tree, engine.UiSchema.DescribeUiView(graph_view.VIEW, graph))
        assert tree.get(graph_view.PARENT_KEY) == parent, (graph, parent)


extension.unregister()
for _ in range(args.repeat_count):
    extension.register()
    assert _registeredTreeType() is not None, "the engine's UI has a graph view, so its tree type is registered"
    standIn = StandIn()
    presentation.SetRealtimePlane(standIn)
    engine = extension._engine

    # Two tools: the trees follow the active tool, node for node.
    graph_view.Update()
    _checkTool(engine, FIRST)
    standIn.Active = SECOND
    graph_view.Update()
    _checkTool(engine, SECOND)

    # A moved node goes back by moving it: the same node, never made again, so nothing Blender points at is freed.
    tree = bpy.data.node_groups[graph_view.TreeName(SECOND)]
    node = next(iter(tree.nodes))
    place, pointer = tuple(node.location), node.as_pointer()
    node.location = (node.location[0] + 500.0, node.location[1] - 300.0)
    assert not graph_view.Busy(), "no operator runs in a background Blender"
    graph_view.Update()
    assert tuple(tree.nodes[node.name].location) == place and tree.nodes[node.name].as_pointer() == pointer
    # A removed link and a deleted node come back as the engine describes them.
    tree.links.remove(tree.links[0])
    tree.nodes.remove(tree.nodes[-1])
    graph_view.Update()
    _checkTool(engine, SECOND)
    # Every stage of every shipped tool has its graph, the layer compositing ones included.
    standIn.Active = "freehand.marker"
    graph_view.Update()
    _checkTool(engine, "freehand.marker")
    standIn.Active = SECOND
    graph_view.Update()
    assert standIn.Requests == [], "the graph view never asks anything of the engine"

    # Saving keeps no tree in the file; the trees are back after the save.
    blend = Path(os.environ["FLEXIBLE_DRAWING_TEST_TMPDIR"]) / "graph_view.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(blend)) == {"FINISHED"}
    # Blender reads no library from the file it has open, so a copy is read.
    copy = blend.with_name("graph_view_copy.blend")
    shutil.copyfile(blend, copy)
    with bpy.data.libraries.load(str(copy)) as (stored, _):
        assert not any(name.startswith("FD Graph") for name in stored.node_groups), stored.node_groups
    _checkTool(engine, SECOND)

    # Reopening the file shows the trees again, made from the engine, not read from the file.
    assert bpy.ops.wm.open_mainfile(filepath=str(blend)) == {"FINISHED"}
    _checkTool(engine, SECOND)

    presentation.SetRealtimePlane(None)
    extension.unregister()
    assert _registeredTreeType() is None, "disabling the extension leaves no tree type registered"
    assert not any(tree.name.startswith("FD Graph") for tree in bpy.data.node_groups), "and no tree"

print("FLEXIBLE_DRAWING_GRAPH_VIEW_OK")
