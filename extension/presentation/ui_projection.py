"""The engine's UI, drawn with Blender widgets: the same few classes project any UI it describes.

Flexible Drawing defines its UI once, for every host, and the engine describes it through the C ABI
as surfaces, sections, groups, editors and controls, each control bound to the state it shows and
the action it requests. Nothing here names a control. The projection walks whatever the engine
describes and maps each *kind* to one Blender idea:

    surface   a panel                   section   a sub-panel of its panel
    group     a box inside its panel    editor    a box, its bindings drawn as controls
    control   a widget chosen by its role: a number field, a checkbox, a text field, a drop-down
              for a choice, or a button for a command

A new control in the engine's UI appears in Blender without a line changing here. Blender needs a
registered class per panel and an RNA property per value, so those are made from the description
when the add-on registers (see `GeneratedClasses`), never written by hand.

The widgets act on the *binding target* the add-on lends (`presentation.BindingTarget`): a change
sends the control's action binding, and the control shows the state binding's effective value. A
value that has been requested and has not taken effect is marked pending, with the value in effect
beside it, because a stroke in progress keeps the tool it started with.

The schema carries meaning, not appearance, so labels come from identities: a control is named by
the last part of the state it shows (`pressure_brush.hardness` is "Hardness"), and a container by
the part before its kind (`painting.active_tool.section` is "Active Tool"). There are no ranges or
units yet, so numbers are unbounded fields.
"""

import logging
import struct
from typing import NamedTuple

import bpy

from ..abi import (
    FD_UI_BINDING_ACTION,
    FD_UI_BINDING_STATE,
    FD_UI_CONTROL_BOOLEAN,
    FD_UI_CONTROL_CHOICE,
    FD_UI_CONTROL_COMMAND,
    FD_UI_CONTROL_INTEGER,
    FD_UI_CONTROL_NUMBER,
    FD_UI_CONTROL_TEXT,
    FD_UI_ELEMENT_CONTROL,
    FD_UI_ELEMENT_SECTION,
    FD_UI_ELEMENT_SURFACE,
    EngineError,
    UiBinding,
    UiSchema,
)
from . import BindingTarget, Engine

_logger = logging.getLogger("flexible_drawing")

#: Where the projected panels appear: the Properties editor's Scene tab, beside the document.
_SPACE_TYPE = "PROPERTIES"
_REGION_TYPE = "WINDOW"
_CONTEXT = "scene"
#: The window-manager property holding every projected value. Blender never saves it: the values
#: belong to whoever the bindings act on, and come back from there.
VALUES_PROPERTY = "flexible_drawing_ui"
_SINGLE = struct.Struct("<f")


class ProjectedControl(NamedTuple):
    """What drawing and updating one control needs, worked out once from the schema."""

    Label: str
    Role: int
    Property: str | None  #: the values group's property, or None when the role has no value
    State: UiBinding | None
    Action: UiBinding | None
    Choices: tuple[str, ...]


class Projection(NamedTuple):
    """The schema being shown, with what drawing it needs worked out once."""

    Schema: UiSchema
    Children: dict[int, tuple[int, ...]]
    Controls: dict[int, ProjectedControl]


_projection: Projection | None = None
_refreshing = False


def Words(identity: str) -> str:
    """An identity part as words: `minimum_radius` is "Minimum Radius"."""
    return identity.replace("_", " ").strip().title()


def ContainerLabel(identity: str) -> str:
    """A container's label: the part of its identity before its kind (`painting.workspace` is "Painting")."""
    parts = identity.split(".")
    return Words(parts[-2] if len(parts) > 1 else parts[0])


def ControlLabel(identity: str, state: UiBinding | None, action: UiBinding | None) -> str:
    """A control's label: the last part of the state it shows, else of the action it requests."""
    named = state or action
    return Words((named.Id if named is not None else identity).split(".")[-1])


def _binding(bindings: tuple[UiBinding, ...], role: int) -> UiBinding | None:
    return next((binding for binding in bindings if binding.Role == role), None)


def _control(schema: UiSchema, index: int) -> ProjectedControl:
    element = schema.Elements[index]
    bindings = schema.BindingsOf(element)
    state = _binding(bindings, FD_UI_BINDING_STATE)
    action = _binding(bindings, FD_UI_BINDING_ACTION)
    choices = schema.ChoicesOf(index)
    hasValue = element.ControlRole in _PROPERTY_TYPES and (element.ControlRole != FD_UI_CONTROL_CHOICE or choices)
    return ProjectedControl(
        Label=ControlLabel(element.Id, state, action),
        Role=element.ControlRole,
        Property=f"control_{index}" if hasValue else None,
        State=state,
        Action=action,
        Choices=choices,
    )


# Sending and showing values.


def _sent(control: ProjectedControl, value: object) -> object:
    """A widget's value as the action carries it: every number travels as a real number.

    A Blender number field holds 32 bits, so 0.8 typed in reads back as 0.800000011920929. What the
    person meant is the shortest decimal that is that same 32-bit number, and that is what is sent.
    """
    if control.Role == FD_UI_CONTROL_INTEGER:
        return float(value)
    if control.Role != FD_UI_CONTROL_NUMBER:
        return value
    single = _SINGLE.pack(value)
    return next(
        (shortest for digits in range(1, 10) if _SINGLE.pack(shortest := float(f"{value:.{digits}g}")) == single),
        float(value),
    )


def _requester(index: int) -> object:
    """The update callback of control `index`'s property: request its action with the new value."""

    def _update(values: object, _context: object) -> None:
        if _refreshing or _projection is None:
            return
        control = _projection.Controls[index]
        target = BindingTarget()
        if target is None or control.Action is None:
            return
        value = _sent(control, getattr(values, control.Property))
        if not target.Request(control.Action.Owner, control.Action.Id, value):
            _logger.warning("[blender] %s cannot request %s", target.Label, control.Action.Id)

    return _update


def Refresh(windowManager: object) -> None:
    """Show each control's effective value, except while its own request is still pending."""
    global _refreshing
    values = getattr(windowManager, VALUES_PROPERTY, None)
    target = BindingTarget()
    if _projection is None or values is None or target is None:
        return
    _refreshing = True  # writing a property calls its update, which must not request it again
    try:
        for control in _projection.Controls.values():
            if control.Property is None or control.State is None:
                continue
            if control.Action is not None and target.Pending(control.Action.Owner, control.Action.Id) is not None:
                continue
            effective = _shownValue(control, target.Effective(control.State.Owner, control.State.Id))
            if effective is not None and not _shows(control, getattr(values, control.Property), effective):
                setattr(values, control.Property, effective)
    finally:
        _refreshing = False


def _shownValue(control: ProjectedControl, value: object) -> object:
    """`value` as the control's widget holds it, or None when it cannot, as for a vector parameter."""
    if control.Role == FD_UI_CONTROL_CHOICE:
        return value if value in control.Choices else None
    if control.Role == FD_UI_CONTROL_NUMBER:
        return value if isinstance(value, float) else None
    if control.Role == FD_UI_CONTROL_INTEGER:
        return int(value) if isinstance(value, float) and value.is_integer() else None
    expected = {FD_UI_CONTROL_BOOLEAN: bool, FD_UI_CONTROL_TEXT: str}.get(control.Role)
    return value if expected is not None and isinstance(value, expected) else None


def _shows(control: ProjectedControl, shown: object, value: object) -> bool:
    """Whether the widget already shows `value`, to the 32 bits a number field holds."""
    if control.Role == FD_UI_CONTROL_NUMBER:
        return _SINGLE.pack(shown) == _SINGLE.pack(value)
    return shown == value


def _shown(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3g}"
    return "unknown" if value is None else str(value)


# Drawing.


def _drawControl(layout: object, index: int) -> None:
    control = _projection.Controls[index]
    target = BindingTarget()
    available = target is not None and target.Available
    row = layout.row()
    row.enabled = available
    values = getattr(bpy.context.window_manager, VALUES_PROPERTY, None)
    if control.Property is not None and values is not None:
        row.prop(values, control.Property, text=control.Label)
    elif control.Role == FD_UI_CONTROL_COMMAND:
        row.operator(UiActionOperator.bl_idname, text=control.Label).Element = index
    else:
        row.label(text=control.Label)
    if available and control.State is not None:
        effective = target.Effective(control.State.Owner, control.State.Id)
        pending = target.Pending(control.Action.Owner, control.Action.Id) if control.Action is not None else None
        if pending is None:
            layout.label(text=f"Effective {_shown(effective)}", icon="CHECKMARK")
        else:
            layout.label(text=f"Pending {_shown(pending)}; in effect {_shown(effective)}", icon="TIME")


def _drawChildren(layout: object, index: int) -> None:
    for child in _projection.Children.get(index, ()):
        element = _projection.Schema.Elements[child]
        if element.Kind == FD_UI_ELEMENT_SECTION:
            continue  # a sub-panel of its own
        if element.Kind == FD_UI_ELEMENT_CONTROL:
            _drawControl(layout, child)
        else:
            box = layout.box()
            box.label(text=ContainerLabel(element.Id))
            _drawChildren(box, child)


def _drawer(index: int) -> object:
    def draw(panel: object, _context: object) -> None:
        if _projection is None:
            return
        layout = panel.layout
        if _projection.Schema.Elements[index].Kind == FD_UI_ELEMENT_SURFACE:
            target = BindingTarget()
            if target is None or not target.Available:
                reason = "No drawing target is available" if target is None else target.UnavailableReason
                layout.label(text=reason, icon="INFO")
            else:
                layout.label(text=f"Acts on: {target.Label}")
        _drawChildren(layout, index)

    return draw


class UiActionOperator(bpy.types.Operator):
    """Request the action of a command in the engine's UI."""

    bl_idname = "flexible_drawing.ui_action"
    bl_label = "Flexible Drawing Command"

    Element: bpy.props.IntProperty(name="Element", description="Index of the command in the engine's UI")

    @classmethod
    def poll(cls, _context: object) -> bool:
        target = BindingTarget()
        return _projection is not None and target is not None and target.Available

    def execute(self, _context: object) -> set[str]:
        control = _projection.Controls.get(self.Element)
        if control is None or control.Action is None:
            return {"CANCELLED"}
        if not BindingTarget().Request(control.Action.Owner, control.Action.Id, None):
            self.report({"WARNING"}, f"{BindingTarget().Label} does not take {control.Label} yet")
            return {"CANCELLED"}
        return {"FINISHED"}


# Making the classes.

_PROPERTY_TYPES = {
    FD_UI_CONTROL_NUMBER: "FloatProperty",
    FD_UI_CONTROL_INTEGER: "IntProperty",
    FD_UI_CONTROL_BOOLEAN: "BoolProperty",
    FD_UI_CONTROL_TEXT: "StringProperty",
    FD_UI_CONTROL_CHOICE: "EnumProperty",
}


def _property(index: int, control: ProjectedControl) -> object:
    fields: dict[str, object] = {"name": control.Label, "update": _requester(index)}
    if control.Role == FD_UI_CONTROL_CHOICE:
        fields["items"] = tuple((choice, Words(choice.split(".")[-1]), choice) for choice in control.Choices)
    return getattr(bpy.props, _PROPERTY_TYPES[control.Role])(**fields)


def _attachValues(cls: type) -> None:
    setattr(bpy.types.WindowManager, VALUES_PROPERTY, bpy.props.PointerProperty(type=cls))


def _detachValues(_cls: type) -> None:
    if hasattr(bpy.types.WindowManager, VALUES_PROPERTY):
        delattr(bpy.types.WindowManager, VALUES_PROPERTY)


def Project(schema: UiSchema) -> list[type]:
    """The Blender classes that show `schema`: the values group first, then panels, parents first."""
    global _projection
    children: dict[int, list[int]] = {}
    for index, element in enumerate(schema.Elements):
        children.setdefault(element.Parent, []).append(index)
    controls = {
        index: _control(schema, index)
        for index, element in enumerate(schema.Elements)
        if element.Kind == FD_UI_ELEMENT_CONTROL
    }
    _projection = Projection(schema, {key: tuple(value) for key, value in children.items()}, controls)

    annotations = {
        control.Property: _property(index, control) for index, control in controls.items() if control.Property
    }
    values = type(
        "FD_UiValues",
        (bpy.types.PropertyGroup,),
        {
            "__annotations__": annotations,
            "__doc__": "Every value the projected UI shows.",
            # Blender calls these when it registers the class, so the pointer lives exactly as long.
            "register": classmethod(_attachValues),
            "unregister": classmethod(_detachValues),
        },
    )
    classes: list[type] = [values]
    panels: dict[int, str] = {}  # element index to the identifier of the panel it is drawn in
    for index, element in enumerate(schema.Elements):
        if element.Kind not in (FD_UI_ELEMENT_SURFACE, FD_UI_ELEMENT_SECTION):
            panels[index] = panels.get(element.Parent, "")
            continue
        identifier = f"FD_PT_ui_{index}"
        attributes = {
            "bl_idname": identifier,
            "bl_label": ContainerLabel(element.Id),
            "bl_space_type": _SPACE_TYPE,
            "bl_region_type": _REGION_TYPE,
            "bl_context": _CONTEXT,
            "__doc__": f"The engine's {element.Id}.",
            "draw": _drawer(index),
        }
        parent = panels.get(element.Parent)
        if element.Kind == FD_UI_ELEMENT_SURFACE:
            parent = "FD_PT_document"
        if parent:
            attributes["bl_parent_id"] = parent
        classes.append(type(identifier, (bpy.types.Panel,), attributes))
        panels[index] = identifier
    return classes


def GeneratedClasses() -> list[type]:
    """The projection of the lent engine's UI, or nothing when there is no engine or no UI."""
    global _projection
    _projection = None
    engine = Engine()
    if engine is None:
        return []
    try:
        schema = engine.UiSchema.Describe()
    except EngineError:
        _logger.exception("[blender] the engine did not describe its UI")
        return []
    return Project(schema)
