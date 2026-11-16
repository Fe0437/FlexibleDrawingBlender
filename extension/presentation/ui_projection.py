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

The schema carries meaning, not appearance. An element may declare an English label and help text,
shown as given. One that declares no label is named from its identity: a control by the last part of
the state it shows (`pressure_brush.hardness` is "Hardness"), and a container by the part before its
kind (`painting.active_tool.section` is "Active Tool"). An editor may ask for a slider, a step or a
precision for a number setting it shows; they are hints, applied where a Blender property has them.
Parameter ranges come from the effective tool; units are not currently published.
"""

import logging
import math
import struct
from typing import NamedTuple

import bpy

from ..abi import EngineError, Record, UiSchema
from ..realtime_plane.profile import Profile
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

# The engine's C++ enumerator names this projection draws differently. They change only when the
# engine renames what a kind or role means, which is a change in meaning this module must follow.
_SURFACE, _SECTION, _CONTROL = "Surface", "Section", "Control"
_COMMAND, _BOOLEAN, _INTEGER, _NUMBER, _CHOICE, _TEXT = "Command", "Boolean", "Integer", "Number", "Choice", "Text"
_STATE, _ACTION = "State", "Action"
_SLIDER = "Slider"
_INTEGER_LOWEST, _INTEGER_HIGHEST = -(2**31), 2**31 - 1  # what a Blender integer field holds


class ProjectedControl(NamedTuple):
    """What drawing and updating one control needs, worked out once from the schema."""

    Label: str
    Role: str  #: the control's C++ role name, such as "Number"
    Property: str | None  #: the values group's property, or None when the role has no value
    State: Record | None  #: the state binding: `Owner.Value`, `Id.Value`, `Role`, `Value`
    Action: Record | None
    Bounds: tuple | None = None
    TypeBounds: tuple | None = None  #: the range the setting's type allows, from the editor's parameter control
    WholeNumber: type | None = None  #: how a whole number travels: the protocol's signed or unsigned type
    Help: str = ""  #: what the control does, shown as its tooltip
    Presentation: Record | None = None  #: the editor's number presentation for this setting, if it names one


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


def _declared(element: Record, field: str) -> str | None:
    """The words `element` declares in `field`, or None; a schema from before words were declared has none."""
    return getattr(element, field, None) or None


def ElementLabel(element: Record) -> str:
    """The label an element declares, else one made from its identity."""
    return _declared(element, "Label") or ContainerLabel(element.Id)


def ControlLabel(identity: str, state: Record | None, action: Record | None) -> str:
    """A control's label: the last part of the state it shows, else of the action it requests."""
    named = state or action
    return Words((named.Id.Value if named is not None else identity).split(".")[-1])


def _binding(bindings: tuple[Record, ...], role: str) -> Record | None:
    return next((binding for binding in bindings if binding.Role == role), None)


def _control(schema: UiSchema, index: int) -> ProjectedControl:
    element = schema.Elements[index]
    state = _binding(element.Bindings, _STATE)
    action = _binding(element.Bindings, _ACTION)
    hasValue = element.Control in _PROPERTY_TYPES
    return ProjectedControl(
        Label=_declared(element, "Label") or ControlLabel(element.Id, state, action),
        Role=element.Control,
        Property=f"control_{index}" if hasValue else None,
        State=state,
        Action=action,
        Help=_declared(element, "Help") or "",
    )


# Sending and showing values.


def _sent(control: ProjectedControl, value: object) -> object:
    """A widget's value as the action carries it: every number travels as a real number.

    A Blender number field holds 32 bits, so 0.8 typed in reads back as 0.800000011920929. What the
    person meant is the shortest decimal that is that same 32-bit number, and that is what is sent.
    """
    if control.Role == _INTEGER:
        return (control.WholeNumber or Profile.Integer)(int(value))
    if control.Role != _NUMBER:
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
        if not target.Request(control.Action.Owner.Value, control.Action.Id.Value, value):
            _logger.warning("[blender] %s cannot request %s", target.Label, control.Action.Id.Value)

    return _update


def Refresh(windowManager: object) -> None:
    """Show each control's effective value, except while its own request is still pending."""
    global _refreshing
    values = getattr(windowManager, VALUES_PROPERTY, None)
    target = BindingTarget()
    if _projection is None or values is None or target is None:
        return
    _replaceParameterControls(target, type(values))
    _refreshing = True  # writing a property calls its update, which must not request it again
    try:
        for control in _projection.Controls.values():
            if control.Property is None or control.State is None:
                continue
            if (
                control.Action is not None
                and target.Pending(control.Action.Owner.Value, control.Action.Id.Value) is not None
            ):
                continue
            effective = _shownValue(control, target.Effective(control.State.Owner.Value, control.State.Id.Value))
            if effective is not None and not _shows(control, getattr(values, control.Property), effective):
                setattr(values, control.Property, effective)
    finally:
        _refreshing = False


def _shownValue(control: ProjectedControl, value: object) -> object:
    """`value` as the control's widget holds it, or None when it cannot, as for a vector parameter."""
    if control.Role == _INTEGER and hasattr(value, "Value"):
        value = value.Value
    if control.Role == _CHOICE:
        return value if value in _choices(control) else None
    if control.Role == _NUMBER:
        return value if isinstance(value, float) else None
    if control.Role == _INTEGER:
        return int(value) if isinstance(value, int) or (isinstance(value, float) and value.is_integer()) else None
    expected = {_BOOLEAN: bool, _TEXT: str}.get(control.Role)
    return value if expected is not None and isinstance(value, expected) else None


def _shows(control: ProjectedControl, shown: object, value: object) -> bool:
    """Whether the widget already shows `value`, to the 32 bits a number field holds."""
    if control.Role == _NUMBER:
        return _SINGLE.pack(shown) == _SINGLE.pack(value)
    return shown == value


def _shown(value: object) -> str:
    value = getattr(value, "Value", value)
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
        slider = control.Presentation is not None and control.Presentation.Widget == _SLIDER
        row.prop(values, control.Property, text=control.Label, slider=slider)
    elif control.Role == _COMMAND:
        row.operator(UiActionOperator.bl_idname, text=control.Label).Element = index
    else:
        row.label(text=control.Label)
    if available and control.State is not None:
        effective = target.Effective(control.State.Owner.Value, control.State.Id.Value)
        pending = (
            target.Pending(control.Action.Owner.Value, control.Action.Id.Value) if control.Action is not None else None
        )
        if pending is None:
            layout.label(text=f"Effective {_shown(effective)}", icon="CHECKMARK")
        else:
            layout.label(text=f"Pending {_shown(pending)}; in effect {_shown(effective)}", icon="TIME")


def _typeBounds(setting: Record) -> tuple | None:
    """The range a single-number setting's type allows, as (least, greatest); None when it allows any."""
    bounds = getattr(setting, "Bounds", None)
    if bounds is None or not bounds.Minimum or not bounds.Maximum:
        return None
    return (bounds.Minimum[0], bounds.Maximum[0])


def _isParameterControl(element: Record) -> bool:
    """Whether `element` is the control an editor makes for each setting of one value type."""
    return getattr(element, "Setting", None) is not None


def _drawChildren(layout: object, index: int) -> None:
    for child in _projection.Children.get(index, ()):
        if child in _dynamicControls:
            _drawControl(layout, child)
            continue
        element = _projection.Schema.Elements[child]
        if element.Kind == _SECTION:
            continue  # a sub-panel of its own
        if _isParameterControl(element):
            continue  # made again for each setting the session reports
        if element.Kind == _CONTROL:
            _drawControl(layout, child)
        else:
            box = layout.box()
            box.label(text=ElementLabel(element))
            _drawChildren(box, child)


def _drawer(index: int) -> object:
    def draw(panel: object, _context: object) -> None:
        if _projection is None:
            return
        layout = panel.layout
        if _projection.Schema.Elements[index].Kind == _SURFACE:
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
        if not BindingTarget().Request(control.Action.Owner.Value, control.Action.Id.Value, None):
            self.report({"WARNING"}, f"{BindingTarget().Label} does not take {control.Label} yet")
            return {"CANCELLED"}
        return {"FINISHED"}


# Making the classes.

_PROPERTY_TYPES = {
    _NUMBER: "FloatProperty",
    _INTEGER: "IntProperty",
    _BOOLEAN: "BoolProperty",
    _TEXT: "StringProperty",
    _CHOICE: "EnumProperty",
}


_choiceCache: dict[tuple[str, ...], tuple] = {}
_parameterSignature: tuple = ()
_dynamicControls: set[int] = set()


def _choices(control: ProjectedControl) -> tuple[str, ...]:
    target = BindingTarget()
    if target is not None and hasattr(target, "Choices") and control.State is not None:
        return target.Choices(control.State.Owner.Value, control.State.Id.Value)
    return ()


def _choiceItems(control: ProjectedControl) -> tuple:
    # Blender borrows the returned strings. Retain them for the projection's lifetime.
    choices = _choices(control)
    if choices not in _choiceCache:
        _choiceCache[choices] = tuple((choice, Words(choice.split(".")[-1]), choice) for choice in choices)
    return _choiceCache[choices]


def _replaceParameterControls(target: object, valuesType: type) -> None:
    """Project an identity editor's session parameters, replacing properties only when its shape changes."""
    global _parameterSignature
    if not hasattr(target, "Parameters"):
        return
    editors = []
    for index, element in enumerate(_projection.Schema.Elements):
        if element.Kind != "Editor":
            continue
        for binding in element.Bindings:
            if binding.Role == _STATE:
                editors.extend(
                    (index, parameter) for parameter in target.Parameters(binding.Owner.Value, binding.Id.Value)
                )
    signature = tuple((parent, p.Owner, p.State, type(p.Value), p.Bounds) for parent, p in editors)
    if signature == _parameterSignature:
        return
    _parameterSignature = signature
    for index in _dynamicControls:
        control = _projection.Controls.pop(index)
        if hasattr(valuesType, control.Property):
            delattr(valuesType, control.Property)
    for parent in _projection.Children:
        _projection.Children[parent] = tuple(
            index for index in _projection.Children[parent] if index not in _dynamicControls
        )
    _dynamicControls.clear()
    # C++ owns the semantic controls: the schema says, for each value type, which control shows a setting
    # and what its binding carries. Python applies that rule and maps the role to a Blender property; it
    # never infers a role from a value.
    if not editors:
        return
    typeNames = {number: name for name, number in Profile.SETTINGS.ValueTypes._asdict().items()}
    offset = 0
    for parent, parameter in editors:
        # The editor's control for this setting's value type: its role, binding value and range come from
        # the engine; the setting's name, bounds and value come from the session.
        model = next(
            (
                _projection.Schema.Elements[child]
                for child in _projection.Children.get(parent, ())
                if child not in _dynamicControls
                and _isParameterControl(_projection.Schema.Elements[child])
                and _projection.Schema.Elements[child].Setting.Type == typeNames.get(parameter.Type, "")
            ),
            None,
        )
        if model is None:
            continue
        index = len(_projection.Schema.Elements) + offset
        offset += 1
        bindings = tuple(
            Record(
                {
                    "Owner": Record({"Value": parameter.Owner}),
                    "Id": Record({"Value": parameter.State}),
                    "Role": role,
                    "Value": model.Setting.Value,
                }
            )
            for role in (_STATE, _ACTION)
        )
        bounds = (
            None if parameter.Bounds is None else tuple(getattr(bound, "Value", bound) for bound in parameter.Bounds)
        )
        typeName = typeNames.get(parameter.Type, "")
        presentation = next(
            (
                setting
                for setting in getattr(_projection.Schema.Elements[parent], "NumberSettings", ())
                if setting.Setting == parameter.State
            ),
            None,
        )
        control = ProjectedControl(
            Label=ControlLabel(f"{parameter.Owner}.{parameter.State}.control", bindings[0], bindings[1]),
            Role=model.Control,
            Property=f"control_{index}",
            State=bindings[0],
            Action=bindings[1],
            Bounds=bounds,
            TypeBounds=_typeBounds(model.Setting),
            # Signedness is how the session takes the value, not how it is shown.
            WholeNumber=Profile.UnsignedInteger if typeName == "UnsignedInteger" else Profile.Integer,
            Presentation=presentation if model.Control == _NUMBER else None,
        )
        _projection.Controls[index] = control
        _dynamicControls.add(index)
        setattr(valuesType, control.Property, _property(index, control))
        _projection.Children[parent] = (*_projection.Children.get(parent, ()), index)


def _property(index: int, control: ProjectedControl) -> object:
    fields: dict[str, object] = {"name": control.Label, "update": _requester(index)}
    if control.Help:
        fields["description"] = control.Help
    if control.Presentation is not None:
        # A Blender float steps in hundredths and shows up to six digits after the point.
        if control.Presentation.Step is not None:
            fields["step"] = max(1, min(100, round(control.Presentation.Step * 100)))
        if control.Presentation.Precision is not None:
            fields["precision"] = min(6, control.Presentation.Precision)
    if control.Role == _CHOICE:
        fields["items"] = lambda _values, _context: _choiceItems(control)
    # The setting's own bounds narrow what its type allows; a Blender integer field holds 32 bits.
    low, high = (-math.inf, math.inf)
    for bounds in (control.TypeBounds, control.Bounds):
        if bounds is not None:
            low, high = max(low, bounds[0]), min(high, bounds[1])
    if control.Role == _INTEGER:
        low, high = max(low, _INTEGER_LOWEST), min(high, _INTEGER_HIGHEST)
    if low != -math.inf:
        fields["min"] = int(low) if control.Role == _INTEGER else low
    if high != math.inf:
        fields["max"] = int(high) if control.Role == _INTEGER else high
    return getattr(bpy.props, _PROPERTY_TYPES[control.Role])(**fields)


def _attachValues(cls: type) -> None:
    setattr(bpy.types.WindowManager, VALUES_PROPERTY, bpy.props.PointerProperty(type=cls))


def _detachValues(_cls: type) -> None:
    if hasattr(bpy.types.WindowManager, VALUES_PROPERTY):
        delattr(bpy.types.WindowManager, VALUES_PROPERTY)


def Project(schema: UiSchema) -> list[type]:
    """The Blender classes that show `schema`: the values group first, then panels, parents first."""
    global _projection, _parameterSignature
    _parameterSignature = ()
    _dynamicControls.clear()
    _choiceCache.clear()
    children: dict[int, list[int]] = {}
    for index, element in enumerate(schema.Elements):
        children.setdefault(element.Parent, []).append(index)
    controls = {
        index: _control(schema, index)
        for index, element in enumerate(schema.Elements)
        if element.Kind == _CONTROL and not _isParameterControl(element)
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
        if element.Kind not in (_SURFACE, _SECTION):
            panels[index] = panels.get(element.Parent, "")
            continue
        identifier = f"FD_PT_ui_{index}"
        attributes = {
            "bl_idname": identifier,
            "bl_label": ElementLabel(element),
            "bl_description": _declared(element, "Help") or "",
            "bl_space_type": _SPACE_TYPE,
            "bl_region_type": _REGION_TYPE,
            "bl_context": _CONTEXT,
            "__doc__": f"The engine's {element.Id}.",
            "draw": _drawer(index),
        }
        parent = panels.get(element.Parent)
        if element.Kind == _SURFACE:
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
