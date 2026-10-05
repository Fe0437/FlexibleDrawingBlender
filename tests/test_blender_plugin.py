#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
from unittest import mock
import zipfile


class FakeDocuments:
    """Stands in for the document interface table, which the bridge exposes as `.Documents`."""

    def Create(self, _name: str) -> object:
        return types.SimpleNamespace(DocumentId=11, Revision=1, LayerCount=1)

    def Query(self, document_id: int) -> object:
        return types.SimpleNamespace(DocumentId=document_id, Revision=1, LayerCount=1)

    def Close(self, document_id: int) -> object:
        return types.SimpleNamespace(DocumentId=document_id, Revision=2, LayerCount=1)

    def Restore(self, _snapshot: object) -> None:
        return None


class FakeScene(dict):
    """A Blender scene as the add-on uses one: custom properties, plus the name it is known by."""

    def __init__(self, name: str = "Scene") -> None:
        super().__init__()
        self.name = name


def fake_ui_schema() -> object:
    """A UI shaped like the engine's, with one control of every role, as the engine's bytes decode."""
    abi = importlib.import_module("flexible_drawing.abi")
    owner = "presentation.tool_ui"

    def binding(identity: str, role: str, value: str) -> object:
        return abi.Record(
            {"Owner": abi.Record({"Value": owner}), "Id": abi.Record({"Value": identity}), "Role": role, "Value": value}
        )

    def bound(state: str, action: str, value: str) -> tuple[object, object]:
        return binding(state, "State", value), binding(action, "Action", value)

    def element(
        identity: str,
        kind: str,
        parent: int | None,
        control: str | None = None,
        bindings: tuple[object, ...] = (),
        choices: tuple[str, ...] = (),
    ) -> object:
        return abi.Record(
            {
                "Id": identity,
                "Kind": kind,
                "Control": control,
                "Parent": parent,
                "Bindings": bindings,
                "Choices": choices,
            }
        )

    elements = (
        element("painting.workspace", "Surface", None),
        element("painting.active_tool.section", "Section", 0),
        element("painting.active_tool.settings.group", "Group", 1),
        element(
            "painting.pressure_brush.hardness.control",
            "Control",
            2,
            "Number",
            bound("pressure_brush.hardness", "pressure_brush.set_hardness", "Number"),
        ),
        element(
            "painting.active_tool.selector",
            "Control",
            1,
            "Choice",
            bound("active_tool", "select_tool", "Identity"),
            ("freehand.pressure_brush", "freehand.pen"),
        ),
        element(
            "painting.pressure_brush.spacing.control",
            "Control",
            2,
            "Integer",
            bound("pressure_brush.spacing", "pressure_brush.set_spacing", "Integer"),
        ),
        element(
            "painting.pressure_brush.smoothing.control",
            "Control",
            2,
            "Boolean",
            bound("pressure_brush.smoothing", "pressure_brush.set_smoothing", "Boolean"),
        ),
        element("painting.brush.name.control", "Control", 2, "Text", bound("brush.name", "brush.rename", "Text")),
        element("painting.canvas.clear.control", "Control", 0, "Command", (binding("canvas.clear", "Action", "None"),)),
    )
    return abi.UiSchema(elements)


class FakeBridge:
    opened = 0
    shutdown = 0

    def __init__(self) -> None:
        self.Documents = FakeDocuments()
        self.UiSchema = types.SimpleNamespace(Describe=fake_ui_schema)

    @classmethod
    def Open(cls, extensionRoot: Path | None = None, log: object = None) -> FakeBridge:
        if log is not None:
            log(2, "engine", "fake engine created")
        cls.opened += 1
        return cls()

    def Shutdown(self) -> None:
        type(self).shutdown += 1

    def Version(self) -> str:
        return "0.1.0"


class DeletedOwner:
    def get(self, *_args: object) -> object:
        raise ReferenceError("deleted")


class RecordingLayout:
    """Record the labels, operators and properties a Blender panel asks its layout to show.

    A row or box records into the same lists as its parent, and remembers whether it was enabled,
    so a test reads one flat list in drawing order.
    """

    def __init__(self, parent: RecordingLayout | None = None) -> None:
        self.Labels: list[str] = parent.Labels if parent else []
        self.Operators: list[str] = parent.Operators if parent else []
        self.OperatorProperties: list[types.SimpleNamespace] = parent.OperatorProperties if parent else []
        self.Properties: list[tuple[str, str, bool]] = parent.Properties if parent else []
        self.enabled = True

    def column(self) -> RecordingLayout:
        return self

    def row(self) -> RecordingLayout:
        return RecordingLayout(self)

    def box(self) -> RecordingLayout:
        return RecordingLayout(self)

    def label(self, *, text: str, icon: str = "NONE") -> None:
        self.Labels.append(text)

    def prop(self, _data: object, name: str, text: str = "") -> None:
        self.Properties.append((name, text, self.enabled))

    def operator(self, identifier: str, text: str | None = None) -> types.SimpleNamespace:
        self.Operators.append(identifier if text is None else f"{identifier} [{text}]")
        # Blender returns the operator's properties so a panel can set them per button.
        properties = types.SimpleNamespace()
        self.OperatorProperties.append(properties)
        return properties


def fake_bpy() -> types.SimpleNamespace:
    registered: list[type] = []
    timerCallbacks: list[object] = []

    def unregisterTimer(callback: object) -> None:
        timerCallbacks[:] = [entry for entry in timerCallbacks if entry[0] is not callback]

    return types.SimpleNamespace(
        app=types.SimpleNamespace(
            version=(5, 2, 1),
            debug=False,
            driver_namespace={},
            handlers=types.SimpleNamespace(persistent=lambda handler: handler, load_post=[]),
            timers=types.SimpleNamespace(
                register=lambda callback, first_interval, persistent=False: timerCallbacks.append(
                    (callback, first_interval)
                ),
                is_registered=lambda callback: any(entry[0] is callback for entry in timerCallbacks),
                unregister=unregisterTimer,
            ),
        ),
        context=types.SimpleNamespace(scene=FakeScene(), window_manager=types.SimpleNamespace(windows=[])),
        # Distinct bases, as real Blender has: `object` would make every class look registrable.
        types=types.SimpleNamespace(
            Operator=type("Operator", (), {}),
            Panel=type("Panel", (), {}),
            PropertyGroup=type("PropertyGroup", (), {}),
            AddonPreferences=type("AddonPreferences", (), {}),
            WindowManager=type("WindowManager", (), {}),
        ),
        # Blender resolves property annotations when it registers a class, so a fake operator has no
        # `SpaceType` attribute and a test sets it the way Blender's caller does. A property here is
        # the fields it was declared with, so a test can read what a generated class asked for.
        props=types.SimpleNamespace(
            **{
                name: (lambda kind: lambda **fields: {"kind": kind, **fields})(name)
                for name in ("BoolProperty", "FloatProperty", "IntProperty", "PointerProperty", "StringProperty")
            },
            EnumProperty=lambda **fields: fields.get("default", {"kind": "EnumProperty", **fields}),
        ),
        utils=types.SimpleNamespace(
            register_class=lambda cls: registered.append(cls),
            unregister_class=lambda cls: registered.remove(cls),
            resource_path=lambda _kind: "/tmp/blender-resources",
        ),
        registered=registered,
        timerCallbacks=timerCallbacks,
    )


class PluginTests(unittest.TestCase):
    extension: Path
    source: Path
    library: Path
    diagnostics: bool

    def setUp(self) -> None:
        FakeBridge.opened = 0
        FakeBridge.shutdown = 0

    def test_manifest_and_idempotent_registration(self) -> None:
        manifest = tomllib.loads((self.extension / "blender_manifest.toml").read_text())
        self.assertEqual(manifest["blender_version_min"], "5.2.0")
        bpy = fake_bpy()
        bpy.context = types.SimpleNamespace()  # Blender restricts context while enabling add-ons.
        with mock.patch.dict(sys.modules, {"bpy": bpy}):
            spec = importlib.util.spec_from_file_location(
                "flexible_drawing", self.extension / "__init__.py", submodule_search_locations=[str(self.extension)]
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules["flexible_drawing"] = module
            assert spec.loader is not None
            spec.loader.exec_module(module)
            module.EngineBridge = FakeBridge
            with self.assertLogs("flexible_drawing", level="INFO") as records:
                module.register()
                module.register()
                module.unregister()
                module.unregister()
            self.assertTrue(any("[engine] fake engine created" in record for record in records.output))
        self.assertEqual(FakeBridge.opened, 1)
        self.assertEqual(FakeBridge.shutdown, 1)
        self.assertEqual(bpy.registered, [])

    def test_native_startup_failure_leaves_no_host_state(self) -> None:
        bpy = fake_bpy()
        with mock.patch.dict(sys.modules, {"bpy": bpy}):
            spec = importlib.util.spec_from_file_location(
                "flexible_drawing", self.extension / "__init__.py", submodule_search_locations=[str(self.extension)]
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules["flexible_drawing"] = module
            assert spec.loader is not None
            spec.loader.exec_module(module)

            class IncompatibleBridge:
                @classmethod
                def Open(cls, **_arguments: object) -> object:
                    raise module.EngineError(3, "intentional incompatible runtime")

            module.EngineBridge = IncompatibleBridge
            with self.assertRaisesRegex(module.EngineError, "intentional incompatible runtime") as raised:
                module.register()
            self.assertEqual(raised.exception.Status, 3)
            self.assertIsNone(module._engine)
            self.assertIsNone(module._logHandler)
            self.assertEqual(bpy.registered, [])
            self.assertNotIn("flexible_drawing_engine_version", bpy.app.driver_namespace)

    def test_document_binding_and_operator_lifecycle(self) -> None:
        bpy = fake_bpy()
        with mock.patch.dict(sys.modules, {"bpy": bpy}):
            spec = importlib.util.spec_from_file_location(
                "flexible_drawing", self.extension / "__init__.py", submodule_search_locations=[str(self.extension)]
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules["flexible_drawing"] = module
            assert spec.loader is not None
            spec.loader.exec_module(module)
            module.EngineBridge = FakeBridge
            module.register()

            documentPresentation = importlib.import_module("flexible_drawing.presentation.document")
            documentBinding = importlib.import_module("flexible_drawing.host.document_binding")
            scene = FakeScene()
            context = types.SimpleNamespace(scene=scene)
            create = documentPresentation.CreateDocumentOperator
            inspect = documentPresentation.InspectDocumentOperator
            close = documentPresentation.CloseDocumentOperator
            self.assertTrue(create.poll(context))
            self.assertEqual(create().execute(context), {"FINISHED"})
            self.assertFalse(create.poll(context))
            self.assertTrue(inspect.poll(context))
            self.assertEqual(inspect().execute(context), {"FINISHED"})
            self.assertEqual(scene["flexible_drawing_document_layer_count"], 1)
            geometry = importlib.import_module("flexible_drawing.host.geometry")
            geometrySync = importlib.import_module("flexible_drawing.host.geometry_sync")
            mesh = geometry.FromCapturedMesh(((0, 0, 0), (1, 0, 0), (0, 1, 0)), ((0, 1, 2),))
            self.assertEqual(mesh.SourceCapability, "MESH")
            # Flat buffers, three numbers per vertex, counted by the properties rather than by len.
            self.assertEqual((mesh.VertexCount, mesh.TriangleCount), (3, 1))
            self.assertEqual(len(mesh.Vertices), 9)
            self.assertEqual(geometry.CapabilityForObjectType("GREASEPENCIL"), "GREASE_PENCIL")
            sync = geometrySync.GeometrySyncState()
            leftKey = "CapturedMesh/tile/0"
            rightKey = "CapturedMesh/tile/1"
            rightMesh = geometry.FromCapturedMesh(((2, 0, 0), (3, 0, 0), (2, 1, 0)), ((0, 1, 2),))
            # A region never read must be read once, without anything having to mark it.
            self.assertTrue(sync.Changed(leftKey))
            left = sync.Commit(leftKey, mesh)
            right = sync.Commit(rightKey, rightMesh)
            self.assertFalse(sync.Changed(leftKey))
            self.assertEqual(sync.ChangedRegions(), ())
            sync.MarkChanged(leftKey)
            self.assertEqual(sync.ChangedRegions(), (leftKey,))
            changed = geometry.FromCapturedMesh(((0, 0, 0), (2, 0, 0), (0, 1, 0)), ((0, 1, 2),))
            self.assertEqual(sync.Commit(leftKey, changed).Revision, 2)
            self.assertEqual(sync.Region(leftKey).Id, left.Id)
            self.assertEqual(sync.Region(rightKey), right)
            with self.assertRaises(ValueError):
                geometry.FromCapturedMesh(((0, 0, 0),), ((0, 1, 2),))
            self.assertEqual(close().execute(context), {"FINISHED"})
            self.assertNotIn("flexible_drawing_document_id", scene)
            self.assertFalse(close.poll(context))
            with self.assertRaises(documentBinding.StaleBindingError):
                documentBinding.Read(DeletedOwner())
            module.unregister()

    def _LoadAbi(self) -> object:
        """Import the host-neutral half alone, proving it needs neither bpy nor the outer package."""
        if "flexible_drawing_abi" in sys.modules:
            return sys.modules["flexible_drawing_abi"]
        root = self.extension / "abi"
        spec = importlib.util.spec_from_file_location(
            "flexible_drawing_abi", root / "__init__.py", submodule_search_locations=[str(root)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_a_sized_record_carries_its_own_size(self) -> None:
        """The one rule a host cannot be trusted to remember is stamped by the constructor."""
        module = self._LoadAbi()
        record = module.generated.fd_document_snapshot
        self.assertEqual(record().struct_size, ctypes.sizeof(record))

    def test_the_engine_refuses_an_interface_it_does_not_serve(self) -> None:
        module = self._LoadAbi()
        bridge = module.EngineBridge.FromLibrary(module.LoadLibrary(self.library))
        try:
            with self.assertRaises(module.EngineError) as raised:
                bridge.Table("brush", 1, module.generated.fd_document_api, ("create",))
            self.assertEqual(raised.exception.Status, module.FD_ENGINE_STATUS_UNKNOWN_INTERFACE)
        finally:
            bridge.Shutdown()

    def test_the_engine_describes_its_ui_as_named_records(self) -> None:
        """The real engine's UI decodes by name: every element has the fields its C++ projection declares."""
        module = self._LoadAbi()
        bridge = module.EngineBridge.FromLibrary(module.LoadLibrary(self.library))
        try:
            schema = bridge.UiSchema.Describe()
        finally:
            bridge.Shutdown()
        self.assertTrue(schema.Surfaces())
        kinds = {"Surface", "Section", "Group", "Editor", "Control"}
        for index, element in enumerate(schema.Elements):
            self.assertIn(element.Kind, kinds)
            self.assertEqual(element.Parent is None, element.Kind == "Surface")
            if element.Parent is not None:
                self.assertLess(element.Parent, index)  # depth first: every parent comes first
            self.assertEqual(element.Control is not None, element.Kind == "Control")
            for binding in element.Bindings:
                self.assertTrue(binding.Owner.Value and binding.Id.Value)
                self.assertIn(binding.Role, {"State", "Action", "Capability"})
        choices = [element for element in schema.Elements if element.Control == "Choice"]
        self.assertTrue(choices and all(element.Choices for element in choices))

    def test_a_self_describing_value_refuses_malformed_bytes(self) -> None:
        module = self._LoadAbi()
        record = module.reflected.MARKER + struct.pack("<IBI", module.reflected.FORMAT_VERSION, 8, 0)
        self.assertEqual(module.Decode(record), module.Record({}))
        for broken in (
            b"XXXX" + record[4:],  # not this format
            module.reflected.MARKER + struct.pack("<IBI", 99, 8, 0),  # another format version
            record[:-1],  # ends early
            record + b"\0",  # trailing bytes
            module.reflected.MARKER + struct.pack("<IB", 1, 42),  # unknown tag
        ):
            with self.assertRaises(ValueError):
                module.Decode(broken)

    def test_package_is_reproducible_and_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = [root / "one.zip", root / "two.zip"]
            wheel = root / "iceoryx2-0.10.0-cp38-abi3-macosx_11_0_arm64.whl"
            wheel.write_bytes(b"wheel fixture")
            wheelLicense = root / "iceoryx2-LICENSE-MIT"
            wheelLicense.write_bytes(b"MIT license fixture")
            nativeLicense = root / "LICENSE.txt"
            nativeLicense.write_bytes(b"native dependency license fixture")
            for output in outputs:
                subprocess.run(
                    [
                        sys.executable,
                        str(self.source / "tools/blender/package.py"),
                        "--extension",
                        str(self.extension),
                        "--library",
                        str(self.library),
                        "--output",
                        str(output),
                        "--wheel",
                        str(wheel),
                        "--third-party-notice",
                        str(wheelLicense),
                        "--bundled-notice",
                        f"native-dependency-LICENSE={nativeLicense}",
                    ],
                    check=True,
                )
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            with zipfile.ZipFile(outputs[0]) as archive:
                metadata = json.loads(archive.read("flexible_drawing/package_metadata.json"))
                packaged_manifest = tomllib.loads(archive.read("flexible_drawing/blender_manifest.toml").decode())
                expected_platform = {
                    "Darwin": "macos-arm64",
                    "Windows": "windows-x64",
                    "Linux": "linux-x64",
                }[platform.system()]
                self.assertEqual(metadata["platform"], expected_platform)
                self.assertEqual(metadata["version"], packaged_manifest["version"])
                self.assertEqual(metadata["license"], "GPL-3.0-or-later")
                self.assertEqual(packaged_manifest["platforms"], [expected_platform])
                self.assertEqual(
                    packaged_manifest["wheels"],
                    ["./wheels/iceoryx2-0.10.0-cp38-abi3-macosx_11_0_arm64.whl"],
                )
                self.assertEqual(packaged_manifest["copyright"], ["2026 Flexible Drawing contributors"])
                self.assertIn("flexible_drawing/LICENSE.txt", archive.namelist())
                self.assertIn("GNU GENERAL PUBLIC LICENSE", archive.read("flexible_drawing/LICENSE.txt").decode())
                self.assertIn("flexible_drawing/LICENSING.md", archive.namelist())
                self.assertIn("Dual-licensing model", archive.read("flexible_drawing/LICENSING.md").decode())
                self.assertIn("flexible_drawing/README.md", archive.namelist())
                packaged_readme = archive.read("flexible_drawing/README.md").decode()
                self.assertIn("Licence and distribution", packaged_readme)
                self.assertIn("(LICENSE.txt)", packaged_readme)
                self.assertNotIn("../../", packaged_readme)
                self.assertNotIn("flexible_drawing/COPYRIGHT.txt", archive.namelist())
                self.assertNotIn("flexible_drawing/COMMERCIAL_DISTRIBUTION.md", archive.namelist())
                self.assertEqual(
                    archive.read("flexible_drawing/wheels/iceoryx2-0.10.0-cp38-abi3-macosx_11_0_arm64.whl"),
                    b"wheel fixture",
                )
                self.assertEqual(
                    archive.read("flexible_drawing/third_party/iceoryx2-LICENSE-MIT"),
                    b"MIT license fixture",
                )
                self.assertEqual(
                    archive.read("flexible_drawing/third_party/native-dependency-LICENSE"),
                    b"native dependency license fixture",
                )

    def test_dependency_audit(self) -> None:
        """Which parts of the extension may import what, read from the imports themselves."""

        def imports(path: Path) -> set[str]:
            """Every module `path` imports, relative ones resolved inside the extension's package."""
            package = path.relative_to(self.extension).parent.parts
            found: set[str] = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    found.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level:
                        base = package[: len(package) - node.level + 1]
                        module = ".".join(("flexible_drawing", *base, *module.split("."))).rstrip(".")
                    found.add(module)
                    found.update(f"{module}.{alias.name}" for alias in node.names)
            return found

        sources = {path: imports(path) for path in self.extension.rglob("*.py") if "__pycache__" not in path.parts}
        for path, imported in sources.items():
            area = path.relative_to(self.extension).parts[0]
            with self.subTest(source=str(path.relative_to(self.extension))):
                # Rendering stays in the native engine and the Realtime Plane; Python never touches it.
                self.assertFalse([name for name in imported if "lightrhi" in name.lower()])
                if area in ("abi", "realtime_plane"):
                    self.assertNotIn("bpy", {name.split(".")[0] for name in imported}, "host-neutral code")
                    self.assertFalse([name for name in imported if name.startswith("flexible_drawing.presentation")])

    def test_hydra_registration_is_optional_without_host_api(self) -> None:
        bpy = fake_bpy()
        with mock.patch.dict(sys.modules, {"bpy": bpy}):
            spec = importlib.util.spec_from_file_location(
                "flexible_drawing", self.extension / "__init__.py", submodule_search_locations=[str(self.extension)]
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules["flexible_drawing"] = module
            assert spec.loader is not None
            spec.loader.exec_module(module)
            hydra = importlib.import_module("flexible_drawing.host.hydra")
            usd = importlib.import_module("flexible_drawing.host.usd")
            fingerprint, classes = hydra.RegisterAvailableEngines(bpy)
            self.assertIsNone(fingerprint)
            self.assertEqual(classes, ())
            with (
                mock.patch.object(usd.importlib, "import_module", side_effect=ModuleNotFoundError),
                self.assertRaises(usd.CompatibilityError),
            ):
                usd.ProbeBundledRuntime(bpy)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-source-dir", type=Path, required=True)
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--diagnostics", choices=("0", "1"), required=True, help="DEBUG_ENABLED of --library")
    args, remaining = parser.parse_known_args()
    # The profile the extension's Realtime Plane client loads, and a scope no person's Realtime Plane uses.
    os.environ["FLEXIBLE_DRAWING_PROTOCOL_DIR"] = str(
        args.project_source_dir / "apps/application/ipc/realtime_plane_protocol"
    )
    os.environ["FLEXIBLE_DRAWING_REALTIME_PLANE_SCOPE"] = f"plugin-test-{os.getpid()}"
    PluginTests.source = args.project_source_dir
    PluginTests.extension = args.extension_dir.resolve()
    PluginTests.library = args.library
    PluginTests.diagnostics = args.diagnostics == "1"
    unittest.main(argv=[sys.argv[0], *remaining])
