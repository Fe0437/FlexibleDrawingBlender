"""The engine's graph view, drawn as native Blender nodes: how a tool is made, read-only.

The engine's UI may hold an editor that shows the `graph` view, bound to one state: the tool it shows.
For each graph the engine describes a layout (`PaintingWorkspaceUiView.DescribeUiView("graph", name)`): boxes on a grid
of columns and rows, each with its rows of ports, and the edges between ports. This module turns that
layout into a node tree of its own type, one tree per graph: the tool's, and the graph each of its
stages runs, and so on inside those. Blender sizes the nodes and draws the links; only the grid places
come from the engine. Double-click or Tab on a node that runs a graph opens that graph's tree, and
Ctrl+Tab goes back, as with Blender's node groups.

The trees only show, and nothing is ever sent to the engine. They are changed only while Blender is
idle, never during an operator such as a drag, because Blender keeps pointers to the nodes an operator
works on. A moved node is put back by moving it; a tree whose nodes or links were changed is filled
again in place. They are removed before every save and made again after it, so no `.blend` keeps
them. Without such an editor in the engine's UI, nothing here is registered.
"""

from __future__ import annotations

import logging

import bpy

from ..abi import Alternative, EngineError, Record
from . import BindingTarget, Engine

_logger = logging.getLogger("flexible_drawing")

#: The view the engine's UI names, and the only one this module draws.
VIEW = "graph"
TREE_TYPE = "FlexibleDrawingGraphTree"
NODE_TYPE = "FlexibleDrawingGraphNode"
SOCKET_TYPE = "FlexibleDrawingGraphSocket"
#: The window-manager property holding which tool and graph are shown. Blender never saves it.
SETTINGS_PROPERTY = "flexible_drawing_graph_view"
#: The operator a host button runs to open the graph view.
OPEN_OPERATOR = "flexible_drawing.graph_view_open"
#: The operator that opens the graph a node runs, on a double-click.
ENTER_OPERATOR = "flexible_drawing.graph_view_enter"
#: The operator that goes back to the graph that holds the shown one.
BACK_OPERATOR = "flexible_drawing.graph_view_back"
#: The custom property naming the graph a tree shows; only trees with it are this module's.
GRAPH_KEY = "flexible_drawing_graph"
#: The custom property naming the graph a tree was opened from; absent for the tool's own tree.
PARENT_KEY = "flexible_drawing_parent"
#: The choice that follows whatever tool the pen draws with.
ACTIVE = "ACTIVE"
#: Grid units in Blender's node space: one row, the space between columns, and the narrowest node.
_ROW = 22.0
#: A node's header and the space around its rows, which a layout row does not count.
_NODE_FRAME = 36.0
#: Space between two nodes of one column, and between two columns.
_NODE_GAP = 40.0
_COLUMN_GAP = 80.0
_NODE_WIDTH = 140.0
_LETTER = 7.0
_PADDING = 40.0
_INTERVAL = 0.5  # seconds between checks that the trees still show what the engine describes

_KIND_NODE = "Node"
_KIND_INPUTS = "Inputs"
_KIND_OUTPUTS = "Outputs"
_DIRECTION_OUTPUT = "Output"

#: The editor's state binding, as (owner, state), or None when the engine's UI has no graph view.
_subject: tuple[str, str] | None = None
#: What each tree should look like, by tree name: node name to (location, width), and the links.
_expected: dict[str, tuple[dict[str, tuple[tuple[float, float], float]], frozenset]] = {}
#: The tool the trees were last built for.
_built: str | None = None
#: The keymap items this module added, to remove them again.
_keymapItems: list[tuple[object, object]] = []


def _boxName(kind: str, name: str) -> str:
    """The Blender name of a box's node: unique in its tree, whatever the graph calls its nodes."""
    return f"node {name}" if kind == _KIND_NODE else ("in" if kind == _KIND_INPUTS else "out")


def Identity(box: Record) -> tuple[str, str]:
    """A box's kind and node name: `Node` and the node's name, or `Inputs` or `Outputs` and no name."""
    alternative, value = Alternative(box)
    if alternative == "GraphLayoutNodeBox":
        return _KIND_NODE, value.Name
    return (_KIND_INPUTS if alternative == "GraphLayoutInputsBox" else _KIND_OUTPUTS), ""


def _endpointName(endpoint: Record) -> str:
    return _boxName(*Identity(endpoint.Box))


def _width(box: Record) -> float:
    """A width that fits the box's longest text, in Blender's node units."""
    texts = [Identity(box.Box)[1], *(row.Label for row in box.Rows)]
    if box.Archetype is not None:
        texts.append(_archetypeText(box.Archetype))
    return max(_NODE_WIDTH, max(len(text) for text in texts) * _LETTER + _PADDING)


def _archetypeText(archetype: Record) -> str:
    return f"{archetype.Name} is {archetype.Profile}" if archetype.Profile else archetype.Name


def ShownTool(windowManager: object) -> str | None:
    """The tool the trees show: the one chosen, or the one the pen draws with."""
    settings = getattr(windowManager, SETTINGS_PROPERTY, None)
    chosen = settings.Tool if settings is not None else ACTIVE
    if chosen != ACTIVE:
        return chosen
    target = BindingTarget()
    if target is None or _subject is None:
        return None
    effective = target.Effective(*_subject)
    return effective if isinstance(effective, str) and effective else None


def _describe(graph: str) -> Record | None:
    engine = Engine()
    if engine is None:
        return None
    try:
        return engine.UiSchema.DescribeUiView(VIEW, graph)
    except EngineError:
        _logger.warning("[blender] the engine has no graph view of %s", graph)
        return None


def Stages(layout: Record) -> tuple[tuple[str, str], ...]:
    """Each node of a layout that runs a graph, as (node name, the graph it runs), in the order the boxes come."""
    return tuple(
        (Identity(box.Box)[1], box.Archetype.Name)
        for box in layout.Boxes
        if box.Archetype is not None and box.Archetype.Profile
    )


def TreeName(graph: str) -> str:
    """The name of the tree showing a graph: a tool's, or one a stage runs."""
    return f"FD Graph {graph}"


def _height(box: Record) -> float:
    """How tall Blender draws a box's node: its frame, then one row for each line it shows."""
    lines = len(box.Rows) + (1 if box.Archetype is not None else 0)
    return _NODE_FRAME + lines * _ROW


def _tops(layout: Record) -> dict[int, float]:
    """How far down each box starts, by its index: at its preferred row, or lower when the box above it in its
    column, in its real height and the gap, reaches further down. The order and alignment are the layout's."""
    tops: dict[int, float] = {}
    bottoms: dict[int, float] = {}
    for index, box in sorted(enumerate(layout.Boxes), key=lambda entry: (entry[1].Column, entry[1].Order)):
        top = box.Row * _ROW
        if box.Column in bottoms:
            top = max(top, bottoms[box.Column] + _NODE_GAP)
        tops[index] = top
        bottoms[box.Column] = top + _height(box)
    return tops


def _fill(tree: object, layout: Record) -> None:
    """Make one node per box at its grid place and one link per edge, and remember what they should be."""
    tree.nodes.clear()
    columnWidths: dict[int, float] = {}
    for box in layout.Boxes:
        columnWidths[box.Column] = max(columnWidths.get(box.Column, 0.0), _width(box))
    left = {0: 0.0}
    for column in range(1, layout.Columns):
        left[column] = left[column - 1] + columnWidths.get(column - 1, _NODE_WIDTH) + _COLUMN_GAP
    # Blender looks at the origin when a tree opens, so the grid is centred there.
    lastColumn = layout.Columns - 1
    width = left.get(lastColumn, 0.0) + columnWidths.get(lastColumn, _NODE_WIDTH)
    tops = _tops(layout)
    height = max((tops[index] + _height(box) for index, box in enumerate(layout.Boxes)), default=0.0)
    left = {column: x - width / 2.0 for column, x in left.items()}
    places: dict[str, tuple[tuple[float, float], float]] = {}
    for index, box in enumerate(layout.Boxes):
        node = tree.nodes.new(NODE_TYPE)
        kind, name = Identity(box.Box)
        node.name = _boxName(kind, name)
        node.label = name if kind == _KIND_NODE else ("in" if kind == _KIND_INPUTS else "out")
        node.Archetype = _archetypeText(box.Archetype) if box.Archetype is not None else ""
        node.Graph = box.Archetype.Name if box.Archetype is not None and box.Archetype.Profile else ""
        node.Resources = "\n".join(row.Label for row in box.Rows if row.Port is None)
        for row in box.Rows:
            if row.Port is None:
                continue
            sockets = node.outputs if row.Port.Direction == _DIRECTION_OUTPUT else node.inputs
            sockets.new(SOCKET_TYPE, row.Label, identifier=row.Port.Name)
        node.select = False  # shown, never edited: nothing starts selected
        node.width = columnWidths[box.Column]
        node.location = (left[box.Column], height / 2.0 - tops[index])
        places[node.name] = (tuple(node.location), node.width)
    links = set()
    for edge in layout.Edges:
        source = tree.nodes[_endpointName(edge.Source)].outputs[edge.Source.Port]
        destination = tree.nodes[_endpointName(edge.Destination)].inputs[edge.Destination.Port]
        tree.links.new(source, destination)
        links.add(
            (_endpointName(edge.Source), edge.Source.Port, _endpointName(edge.Destination), edge.Destination.Port)
        )
    _expected[tree.name] = (places, frozenset(links))


def _tree(graph: str, parent: str | None) -> object:
    """The tree of `graph`, made when missing; an existing one is kept, so an editor showing it keeps it."""
    name = TreeName(graph)
    tree = bpy.data.node_groups.get(name)
    if tree is None or tree.bl_idname != TREE_TYPE:
        tree = bpy.data.node_groups.new(name, TREE_TYPE)
    tree[GRAPH_KEY] = graph
    if parent is None:
        tree.pop(PARENT_KEY, None)
    else:
        tree[PARENT_KEY] = parent
    return tree


def Build(tool: str) -> list[object]:
    """Make, or fill again, the trees of `tool`: its own graph, then each graph its nodes run, and so on
    inside those, each once. Trees of another tool are removed, after any editor showing one is moved to
    this tool's tree. Returns the trees, the tool's first."""
    global _built
    trees: list[object] = []
    pending: list[tuple[str, str | None]] = [(tool, None)]
    seen: set[str] = set()
    while pending:
        graph, parent = pending.pop(0)
        if graph in seen:
            continue
        seen.add(graph)
        layout = _describe(graph)
        if layout is None:
            continue
        tree = _tree(graph, parent)
        _fill(tree, layout)
        trees.append(tree)
        pending += [(stage, graph) for _, stage in Stages(layout)]
    if not trees:
        return []
    stale = [tree for tree in OwnTrees() if tree.get(GRAPH_KEY) not in seen]
    for space in _graphEditors():
        if space.node_tree in stale:
            space.node_tree = trees[0]
    for tree in stale:
        _expected.pop(tree.name, None)
        bpy.data.node_groups.remove(tree)
    _built = tool
    return trees


def _graphEditors() -> list[object]:
    """Every node editor space, in every window, that shows a graph view tree type."""
    windowManager = bpy.context.window_manager
    return [
        area.spaces.active
        for window in getattr(windowManager, "windows", ())
        for area in window.screen.areas
        if area.type == "NODE_EDITOR" and getattr(area.spaces.active, "tree_type", "") == TREE_TYPE
    ]


def OwnTrees() -> list[object]:
    """Every tree this module made and still exists."""
    return [tree for tree in bpy.data.node_groups if tree.get(GRAPH_KEY) is not None]


def RemoveTrees() -> None:
    """Remove every tree this module made."""
    for tree in OwnTrees():
        bpy.data.node_groups.remove(tree)
    _expected.clear()


def _sameStructure(tree: object) -> bool:
    """Whether `tree` still has exactly the nodes and links it was built with, wherever they are."""
    expected = _expected.get(tree.name)
    if expected is None:
        return False
    places, links = expected
    if {node.name for node in tree.nodes} != set(places):
        return False
    found = {
        (link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier)
        for link in tree.links
    }
    return found == links


def _putBack(tree: object) -> None:
    """Move every node of `tree` back to its place and width, without making or removing any."""
    places, _links = _expected[tree.name]
    for node in tree.nodes:
        location, width = places[node.name]
        if tuple(node.location) != location:
            node.location = location
        if node.width != width:
            node.width = width


def Busy() -> bool:
    """Whether an operator, such as a drag, is running in any window: the trees must not change then."""
    return any(len(window.modal_operators) for window in getattr(bpy.context.window_manager, "windows", ()))


def Update() -> None:
    """Make the trees show the shown tool again, while Blender is idle: build them when the tool changed or
    a node or link was changed, and put moved nodes back."""
    if _subject is None or Busy():
        return
    tool = ShownTool(bpy.context.window_manager)
    if tool is None:
        if OwnTrees():
            RemoveTrees()
        return
    trees = OwnTrees()
    if tool != _built or not trees or not all(_sameStructure(tree) for tree in trees):
        Build(tool)
        return
    for tree in trees:
        _putBack(tree)


def _tick() -> float | None:
    if _subject is None:
        return None
    Update()
    return _INTERVAL


@bpy.app.handlers.persistent
def _beforeSave(_file: object) -> None:
    RemoveTrees()


@bpy.app.handlers.persistent
def _afterSaveOrLoad(_file: object) -> None:
    global _built
    _built = None
    RemoveTrees()
    Update()


def _handlers() -> tuple[tuple[list, object], ...]:
    """Blender's handler lists and what this module adds to each."""
    handlers = bpy.app.handlers
    return (
        (handlers.save_pre, _beforeSave),
        (handlers.save_post, _afterSaveOrLoad),
        (handlers.load_post, _afterSaveOrLoad),
    )


def _addKeymap() -> None:
    """Double-click or Tab opens the graph a node runs, and Ctrl+Tab goes back, as Blender enters and leaves a
    node group. The operators answer only in this module's trees, so other trees keep Blender's own keys."""
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:  # Blender without a window, such as a background run, has no add-on keymaps
        return
    keymap = keyconfig.keymaps.new(name="Node Editor", space_type="NODE_EDITOR")
    for operator, key, value, ctrl in (
        (ENTER_OPERATOR, "LEFTMOUSE", "DOUBLE_CLICK", False),
        (ENTER_OPERATOR, "TAB", "PRESS", False),
        (BACK_OPERATOR, "TAB", "PRESS", True),
    ):
        _keymapItems.append((keymap, keymap.keymap_items.new(operator, key, value, ctrl=ctrl)))


def _removeKeymap() -> None:
    while _keymapItems:
        keymap, item = _keymapItems.pop()
        keymap.keymap_items.remove(item)


# Blender keeps no reference to the strings an item callback returns, so the last lists are kept here.
_items: dict[str, list[tuple[str, str, str]]] = {}


def _toolItems(_settings: object, _context: object) -> list[tuple[str, str, str]]:
    items = [(ACTIVE, "Active tool", "The tool the pen draws with")]
    target = BindingTarget()
    if target is not None and _subject is not None and hasattr(target, "Choices"):
        items += [(tool, tool, f"How {tool} is made") for tool in target.Choices(*_subject)]
    _items["tool"] = items
    return items


def _showChosen(_settings: object, context: object) -> None:
    Update()
    tool = ShownTool(context.window_manager)
    space = getattr(context, "space_data", None)
    if tool is None or space is None or getattr(space, "type", "") != "NODE_EDITOR":
        return
    tree = bpy.data.node_groups.get(TreeName(tool))
    if tree is not None:
        space.node_tree = tree


def _nodeEditor(context: object) -> tuple[object, object] | None:
    """A node editor to show the graph in, as (window, area): one already showing a graph, then any node
    editor of the current screen, then the largest area of a new window."""
    areas = [area for area in context.screen.areas if area.type == "NODE_EDITOR"]
    areas.sort(key=lambda area: getattr(area.spaces.active, "tree_type", "") != TREE_TYPE)
    if areas:
        return context.window, areas[0]
    if bpy.ops.wm.window_new() != {"FINISHED"}:
        return None
    window = context.window_manager.windows[-1]
    return window, max(window.screen.areas, key=lambda area: area.width * area.height)


class GraphViewOpenOperator(bpy.types.Operator):
    """Show how the active tool is made in a node editor, opening one in a new window when none is open."""

    bl_idname = OPEN_OPERATOR
    bl_label = "Open Graph"
    bl_description = "Show how the tool is made: its stages and the graphs inside them"

    @classmethod
    def poll(cls, _context: object) -> bool:
        return _subject is not None

    def execute(self, context: object) -> set[str]:
        Update()
        tool = ShownTool(context.window_manager)
        tree = bpy.data.node_groups.get(TreeName(tool)) if tool is not None else None
        if tree is None:
            self.report({"WARNING"}, "No tool to show yet: start painting first")
            return {"CANCELLED"}
        found = _nodeEditor(context)
        if found is None:
            return {"CANCELLED"}
        _window, area = found
        area.type = "NODE_EDITOR"
        area.ui_type = TREE_TYPE
        space = area.spaces.active
        space.node_tree = tree
        space.show_region_ui = True
        return {"FINISHED"}


def _shownTree(context: object) -> object | None:
    """The graph view tree the context's node editor shows, or None."""
    space = getattr(context, "space_data", None)
    tree = getattr(space, "node_tree", None)
    return tree if tree is not None and tree.get(GRAPH_KEY) is not None else None


class GraphViewEnterOperator(bpy.types.Operator):
    """Open the graph the node under the pointer runs, such as the brush a stage runs."""

    bl_idname = ENTER_OPERATOR
    bl_label = "Open Node Graph"
    bl_description = "Show the graph this node runs"

    @classmethod
    def poll(cls, context: object) -> bool:
        node = getattr(context, "active_node", None)
        return _shownTree(context) is not None and node is not None and bool(getattr(node, "Graph", ""))

    def execute(self, context: object) -> set[str]:
        tree = bpy.data.node_groups.get(TreeName(context.active_node.Graph))
        if tree is None:
            return {"CANCELLED"}
        context.space_data.node_tree = tree
        return {"FINISHED"}


class GraphViewBackOperator(bpy.types.Operator):
    """Go back to the graph the shown one was opened from."""

    bl_idname = BACK_OPERATOR
    bl_label = "Back"
    bl_description = "Show the graph this one runs inside"

    @classmethod
    def poll(cls, context: object) -> bool:
        tree = _shownTree(context)
        return tree is not None and tree.get(PARENT_KEY) is not None

    def execute(self, context: object) -> set[str]:
        tree = bpy.data.node_groups.get(TreeName(_shownTree(context)[PARENT_KEY]))
        if tree is None:
            return {"CANCELLED"}
        context.space_data.node_tree = tree
        return {"FINISHED"}


def _nodeClasses() -> tuple[type, type, type]:
    """The socket, node and tree types, made here rather than at module level so that importing this
    module needs no node types, and they exist only when the engine's UI has a graph view."""

    class GraphTree(bpy.types.NodeTree):
        """How a Flexible Drawing tool is made: shown from the engine, never edited here."""

        bl_idname = TREE_TYPE
        bl_label = "Flexible Drawing Graph"
        bl_icon = "NODETREE"
        # A shown graph has no group sockets to edit.
        bl_use_group_interface = False

        @classmethod
        def register(cls) -> None:
            for handlers, handler in _handlers():
                if handler not in handlers:
                    handlers.append(handler)
            bpy.app.timers.register(_tick, first_interval=0.0, persistent=True)
            _addKeymap()

        @classmethod
        def unregister(cls) -> None:
            for handlers, handler in _handlers():
                if handler in handlers:
                    handlers.remove(handler)
            if bpy.app.timers.is_registered(_tick):
                bpy.app.timers.unregister(_tick)
            _removeKeymap()
            RemoveTrees()

    class GraphSocket(bpy.types.NodeSocket):
        """A port of a graph node; its name says the port and any value it is given."""

        bl_idname = SOCKET_TYPE
        bl_label = "Flexible Drawing Port"

        def draw(self, _context: object, layout: object, _node: object, text: str) -> None:
            layout.label(text=text)

        @classmethod
        def draw_color_simple(cls) -> tuple[float, float, float, float]:
            return (0.6, 0.6, 0.6, 1.0)

    class GraphNode(bpy.types.Node):
        """One node of a Flexible Drawing graph, or the graph's inputs or outputs."""

        bl_idname = NODE_TYPE
        bl_label = "Flexible Drawing Node"

        Archetype: bpy.props.StringProperty(name="Archetype", description="What the node instantiates")
        Graph: bpy.props.StringProperty(name="Graph", description="The graph the node runs; empty for none")
        Resources: bpy.props.StringProperty(name="Resources", description="The resources it binds, one per line")

        @classmethod
        def poll(cls, tree: object) -> bool:
            return tree.bl_idname == TREE_TYPE

        def draw_buttons(self, _context: object, layout: object) -> None:
            if self.Archetype:
                layout.label(text=self.Archetype, icon="NODETREE" if self.Graph else "NONE")
            for resource in self.Resources.splitlines():
                layout.label(text=resource)

    return GraphSocket, GraphNode, GraphTree


def _settingsAndPanel() -> tuple[type, type]:
    """The settings and the panel, made here rather than at module level so the package's own class
    discovery never registers them: they exist only when the engine's UI has a graph view."""

    class GraphViewSettings(bpy.types.PropertyGroup):
        """Which tool the graph view shows."""

        Tool: bpy.props.EnumProperty(name="Tool", items=_toolItems, update=_showChosen)

        @classmethod
        def register(cls) -> None:
            setattr(bpy.types.WindowManager, SETTINGS_PROPERTY, bpy.props.PointerProperty(type=cls))

        @classmethod
        def unregister(cls) -> None:
            if hasattr(bpy.types.WindowManager, SETTINGS_PROPERTY):
                delattr(bpy.types.WindowManager, SETTINGS_PROPERTY)

    class GraphViewPanel(bpy.types.Panel):
        """Pick the tool the graph view shows, and go back from a graph a node runs."""

        bl_idname = "FD_PT_graph_view"
        bl_label = "Tool Graph"
        bl_space_type = "NODE_EDITOR"
        bl_region_type = "UI"
        bl_category = "Flexible Drawing"

        @classmethod
        def poll(cls, context: object) -> bool:
            return getattr(context.space_data, "tree_type", "") == TREE_TYPE

        def draw(self, context: object) -> None:
            settings = getattr(context.window_manager, SETTINGS_PROPERTY)
            self.layout.prop(settings, "Tool")
            if ShownTool(context.window_manager) is None:
                self.layout.label(text="No tool to show yet", icon="INFO")
                return
            tree = _shownTree(context)
            if tree is not None and tree.get(PARENT_KEY) is not None:
                self.layout.operator(BACK_OPERATOR, text=f"Back to {tree[PARENT_KEY]}", icon="BACK")
            self.layout.label(text="Double-click or Tab: open a node's graph", icon="INFO")

    return GraphViewSettings, GraphViewPanel


def GraphViewSubject(schema: object) -> tuple[str, str] | None:
    """The state binding of the engine UI's graph view editor, as (owner, state), or None without one."""
    for element in schema.Elements:
        if element.Kind == "Editor" and getattr(element, "View", None) == VIEW:
            for binding in element.Bindings:
                if binding.Role == "State":
                    return (binding.Owner.Value, binding.Id.Value)
    return None


def GeneratedClasses() -> list[type]:
    """The graph view's classes when the engine's UI has a graph view, or nothing."""
    global _subject, _built
    _subject, _built = None, None
    _expected.clear()
    engine = Engine()
    if engine is None:
        return []
    try:
        _subject = GraphViewSubject(engine.UiSchema.DescribePaintingWorkspace())
    except EngineError:
        return []
    if _subject is None:
        return []
    return [*_nodeClasses(), *_settingsAndPanel()]
