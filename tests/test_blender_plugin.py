#!/usr/bin/env python3
from __future__ import annotations

import argparse
import array
import ctypes
import importlib.util
import json
from pathlib import Path
import platform
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


class RecordingBatch:
    """Stands in for an InputBatch, keeping what was appended so a test can look at it."""

    def __init__(self) -> None:
        self.appended: list[dict] = []

    def __len__(self) -> int:
        return len(self.appended)

    def Clear(self) -> None:
        self.appended.clear()

    def Append(self, **fields: object) -> None:
        self.appended.append(fields)


class FakeReceivers:
    """Stands in for the receiver interface table, which the bridge exposes as `.Receivers`."""

    def __init__(self) -> None:
        self.Submissions: list[list[dict]] = []
        self.Seeds: list[int] = []
        self.InputCapabilities: list[int] = []
        self.BatchCapacities: list[int] = []
        self.Contacts: list[tuple[str, int, int]] = []
        self.Ordinals: list[int] = []
        #: Refuse this many submissions as busy first, the way a loaded engine does.
        self.BusyRefusals = 0
        self._revision = 0
        self._next = 1

    def Batch(self, capacity: int = 64) -> RecordingBatch:
        self.BatchCapacities.append(capacity)
        return RecordingBatch()

    def Create(
        self,
        *,
        seed: int,
        tileExtent: int = 64,
        maximumBatchSamples: int = 1024,
        maximumPacketDabs: int = 65536,
        inputCapabilities: int = 0,
    ) -> object:
        self.Seeds.append(seed)
        self.InputCapabilities.append(inputCapabilities)
        receiverId = self._next
        self._next += 1
        return types.SimpleNamespace(
            ReceiverId=receiverId,
            Revision=0,
            CommittedSequence=0,
            AcceptedSampleCount=0,
            PredictedSampleCount=0,
        )

    def BeginContact(self, receiverId: int, contactId: int) -> None:
        self.Contacts.append(("begin", receiverId, contactId))

    def Submit(self, receiverId: int, contactId: int, batchOrdinal: int, batch: RecordingBatch) -> object:
        if self.BusyRefusals:
            self.BusyRefusals -= 1
            raise _EngineErrorType()(_BUSY_STATUS(), "a submission is already running")
        self.Submissions.append(list(batch.appended))
        self.Ordinals.append(batchOrdinal)
        self._revision += 1
        committed = [sample for sample in batch.appended if sample["origin"] != 2]
        return types.SimpleNamespace(
            ReceiverId=receiverId,
            Revision=self._revision,
            CommittedSequence=committed[-1]["sequence"] if committed else 0,
            AcceptedSampleCount=len(batch.appended),
            PredictedSampleCount=len(batch.appended) - len(committed),
        )

    def EndContact(self, receiverId: int, contactId: int, contactEnd: int) -> None:
        self.Contacts.append(("end", receiverId, contactId))

    def Close(self, receiverId: int) -> None:
        self.Contacts.append(("close", receiverId, 0))


class FakeScene(dict):
    """A Blender scene as the add-on uses one: custom properties, plus the name it is known by."""

    def __init__(self, name: str = "Scene") -> None:
        super().__init__()
        self.name = name


class FakeEvent:
    """One Blender pointer event, in the shape the modal operator reads."""

    def __init__(
        self,
        eventType: str,
        x: float,
        y: float,
        value: str = "NOTHING",
        pressure: float = 1.0,
        isTablet: bool = False,
    ) -> None:
        self.type = eventType
        self.value = value
        self.mouse_region_x = x
        self.mouse_region_y = y
        self.pressure = pressure
        self.is_tablet = isTablet


def fake_image_region() -> types.SimpleNamespace:
    """An Image Editor region whose View2D reports the displayed image's normalized space."""
    return types.SimpleNamespace(
        type="WINDOW", view2d=types.SimpleNamespace(region_to_view=lambda x, y: (x / 100.0, y / 100.0))
    )


class FakeBridge:
    opened = 0
    shutdown = 0

    def __init__(self) -> None:
        self.Documents = FakeDocuments()
        self.Receivers = FakeReceivers()

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


def _EngineErrorType() -> type:
    return importlib.import_module("flexible_drawing.abi").EngineError


def _BUSY_STATUS() -> int:
    return importlib.import_module("flexible_drawing.abi").FD_RECEIVER_STATUS_BUSY


class DeletedOwner:
    def get(self, *_args: object) -> object:
        raise ReferenceError("deleted")


# More draws than the reveal timer will ever wait for, so a fake sidebar can stay unready.
_REVEAL_ATTEMPTS_CEILING = 1000


class FakeSidebarRegion:
    """A Blender sidebar region, which refuses a tab until Blender has drawn it at least once."""

    def __init__(self, drawsUntilReady: int = 1) -> None:
        self.type = "UI"
        self.active_panel_category = "Item"
        self._drawsUntilReady = drawsUntilReady

    def is_property_readonly(self, name: str) -> bool:
        assert name == "active_panel_category"
        return self._drawsUntilReady > 0

    def Draw(self) -> None:
        self._drawsUntilReady = max(0, self._drawsUntilReady - 1)


class FakeArea:
    """A Blender editor area, which builds its sidebar's tabs when it is asked to redraw."""

    def __init__(self, areaType: str = "VIEW_3D", regions: tuple = ()) -> None:
        self.type = areaType
        self.spaces = types.SimpleNamespace(active=types.SimpleNamespace(show_region_ui=False))
        self.regions = regions
        self.Redraws = 0
        self._tagged = False

    def tag_redraw(self) -> None:
        """Blender only marks the area here; the draw itself happens later, on its event loop."""
        self.Redraws += 1
        self._tagged = True

    def Draw(self) -> None:
        """Run the draw Blender's event loop would have run, so a test can decide when it happens."""
        if self._tagged:
            self._tagged = False
            for region in self.regions:
                region.Draw()


class RecordingLayout:
    """Record the labels and operators a Blender panel asks its layout to show."""

    def __init__(self) -> None:
        self.Labels: list[str] = []
        self.Operators: list[str] = []
        self.OperatorProperties: list[types.SimpleNamespace] = []

    def column(self) -> RecordingLayout:
        return self

    def label(self, *, text: str) -> None:
        self.Labels.append(text)

    def operator(self, identifier: str, text: str | None = None) -> types.SimpleNamespace:
        self.Operators.append(identifier if text is None else f"{identifier} [{text}]")
        # Blender returns the operator's properties so a panel can set them per button.
        properties = types.SimpleNamespace()
        self.OperatorProperties.append(properties)
        return properties


def fake_bpy(sidebarDraws: int = 1) -> types.SimpleNamespace:
    registered: list[type] = []
    registeredTools: list[type] = []
    timerCallbacks: list[object] = []
    windows: list[object] = []

    def window_new() -> set[str]:
        """Blender's new window holds exactly one area, copied from the active one."""
        area = FakeArea(regions=(FakeSidebarRegion(sidebarDraws),))
        windows.append(types.SimpleNamespace(screen=types.SimpleNamespace(areas=[area])))
        return {"FINISHED"}

    return types.SimpleNamespace(
        ops=types.SimpleNamespace(wm=types.SimpleNamespace(window_new=window_new)),
        windows=windows,
        app=types.SimpleNamespace(
            version=(5, 2, 1),
            driver_namespace={},
            timers=types.SimpleNamespace(
                register=lambda callback, first_interval: timerCallbacks.append((callback, first_interval))
            ),
        ),
        context=types.SimpleNamespace(scene=FakeScene(), window_manager=types.SimpleNamespace(windows=windows)),
        # Distinct bases, as real Blender has: `object` would make every class look registrable.
        types=types.SimpleNamespace(
            Operator=type("Operator", (), {}),
            Panel=type("Panel", (), {}),
            WorkSpaceTool=type("WorkSpaceTool", (), {}),
        ),
        # Blender resolves property annotations when it registers a class, so a fake operator has no
        # `SpaceType` attribute and a test sets it the way Blender's caller does.
        props=types.SimpleNamespace(EnumProperty=lambda **fields: fields["default"]),
        utils=types.SimpleNamespace(
            register_class=lambda cls: registered.append(cls),
            unregister_class=lambda cls: registered.remove(cls),
            register_tool=lambda cls, separator=False, group=False: registeredTools.append(cls),
            unregister_tool=lambda cls: registeredTools.remove(cls),
            resource_path=lambda _kind: "/tmp/blender-resources",
        ),
        registeredTools=registeredTools,
        registered=registered,
        timerCallbacks=timerCallbacks,
    )


class PluginTests(unittest.TestCase):
    extension: Path
    source: Path
    library: Path

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
            inputHost = importlib.import_module("flexible_drawing.host.input")
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
            receiverBinding = importlib.import_module("flexible_drawing.host.receiver_binding")
            receiverBinding.Bind(module._engine, scene)
            recorded = RecordingBatch()
            inputHost.AppendHostEvents(
                recorded,
                ({"x": 0, "y": 0, "pressure": 1, "time_nanoseconds": 1, "sequence": 1, "origin": "PREDICTED"},),
            )
            self.assertEqual(recorded.appended[0]["origin"], 2)
            with self.assertRaises(ValueError):
                inputHost.AppendHostEvents(
                    RecordingBatch(),
                    ({"x": 0, "y": 0, "pressure": 2, "time_nanoseconds": 1, "sequence": 1, "origin": "MEASURED"},),
                )
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
            self.assertIn(("close", 1, 0), module._engine.Receivers.Contacts)
            self.assertNotIn("flexible_drawing_document_id", scene)
            self.assertFalse(close.poll(context))
            with self.assertRaises(documentBinding.StaleBindingError):
                documentBinding.Read(DeletedOwner())
            module.unregister()

    def test_viewport_operator_opens_the_sidebar_and_panel_reports_document_state(self) -> None:
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

            presentation = importlib.import_module("flexible_drawing.presentation.viewport")
            scene = FakeScene()
            # `wm.window_new` copies the active area, so the operator still needs one to exist.
            context = types.SimpleNamespace(scene=scene, area=FakeArea("PROPERTIES"))

            self.assertIn(presentation.OpenViewportOperator, bpy.registered)
            self.assertIn(presentation.ImageEditorSidebarPanel, bpy.registered)
            self.assertIn(presentation.View3DSidebarPanel, bpy.registered)
            # The shared half is not a Blender class, so the registrar must not have found it.
            self.assertNotIn(presentation.ViewportSidebar, bpy.registered)
            self.assertTrue(presentation.OpenViewportOperator.poll(context))

            # Blender installs an operator's properties when it registers the class, so a test sets
            # `SpaceType` the way Blender's caller does.
            for spaceType in ("IMAGE_EDITOR", "VIEW_3D"):
                operator = presentation.OpenViewportOperator()
                operator.SpaceType = spaceType
                self.assertEqual(operator.execute(context), {"FINISHED"})

                openedArea = bpy.windows[-1].screen.areas[0]
                self.assertEqual(openedArea.type, spaceType)
                self.assertTrue(openedArea.spaces.active.show_region_ui)
                # Blender has not drawn the new window yet, so it refuses the tab. The failed
                # attempt asks for the redraw that will make the tab selectable, and queues a retry.
                sidebar = openedArea.regions[0]
                self.assertEqual(sidebar.active_panel_category, "Item")
                self.assertEqual(openedArea.Redraws, 1)
                callback, firstInterval = bpy.timerCallbacks.pop()
                self.assertEqual(firstInterval, 0.0)
                # Blender has still not drawn the tagged area, so the retry refuses and asks again.
                self.assertEqual(callback(), presentation._REVEAL_RETRY_INTERVAL)
                openedArea.Draw()
                self.assertIsNone(callback())
                self.assertEqual(sidebar.active_panel_category, "Flexible Drawing")

            # Each press opens its own window rather than taking over the one already in use.
            self.assertEqual(len(bpy.windows), 2)
            self.assertEqual(context.area.type, "PROPERTIES")

            documentPresentation = importlib.import_module("flexible_drawing.presentation.document")
            self.assertEqual(documentPresentation.CreateDocumentOperator().execute(context), {"FINISHED"})
            # A stroke through the scene's receiver, which is what the sidebar's revision comes from.
            inputSource = importlib.import_module("flexible_drawing.host.input_source")
            receiverBinding = importlib.import_module("flexible_drawing.host.receiver_binding")
            source = inputSource.InputSourceOnBlender(
                module._engine,
                receiverBinding.Bind(module._engine, scene),
                contactId=1,
                maximumBatchSamples=receiverBinding.MAXIMUM_BATCH_SAMPLES,
            )
            source.Begin()
            source.CollectAll(
                (
                    {"x": 1.0, "y": 1.0, "pressure": 0.5, "time_nanoseconds": 1, "sequence": 1, "origin": "MEASURED"},
                    {"x": 65.0, "y": 1.0, "pressure": 0.5, "time_nanoseconds": 2, "sequence": 2, "origin": "COALESCED"},
                    {
                        "x": 130.0,
                        "y": 1.0,
                        "pressure": 0.5,
                        "time_nanoseconds": 3,
                        "sequence": 3,
                        "origin": "PREDICTED",
                    },
                )
            )
            self.assertTrue(source.Submit())
            self.assertEqual(source.Snapshot.PredictedSampleCount, 1)
            self.assertEqual(source.Finish(), 0)
            scene["flexible_drawing_receiver_revision"] = source.Snapshot.Revision
            # Both editors show the same sidebar, because both get it from the same shared half.
            for panelClass in (presentation.ImageEditorSidebarPanel, presentation.View3DSidebarPanel):
                layout = RecordingLayout()
                panel = panelClass()
                panel.layout = layout
                panel.draw(context)
                # A receiver revision, not a tile count: the engine reports what it accepted.
                self.assertEqual(layout.Labels, ["Document 11", "Revision 1", "Layers 1", "Canvas revision 1"])
                self.assertEqual(
                    layout.Operators,
                    [
                        "flexible_drawing.document_create",
                        "flexible_drawing.document_inspect",
                        "flexible_drawing.document_close",
                    ],
                )

            documentLayout = RecordingLayout()
            documentPanel = documentPresentation.DocumentPanel()
            documentPanel.layout = documentLayout
            documentPanel.draw(context)
            self.assertEqual(
                documentLayout.Operators[:2],
                [
                    "flexible_drawing.viewport_open [Open 2D Canvas]",
                    "flexible_drawing.viewport_open [Open 3D Viewport]",
                ],
            )
            self.assertEqual(
                [properties.SpaceType for properties in documentLayout.OperatorProperties[:2]],
                ["IMAGE_EDITOR", "VIEW_3D"],
            )
            module.unregister()

    def test_the_viewport_gives_up_on_a_sidebar_that_never_appears_and_reports_a_refused_window(
        self,
    ) -> None:
        # A sidebar that stays unready far longer than the retry budget allows.
        bpy = fake_bpy(sidebarDraws=_REVEAL_ATTEMPTS_CEILING)
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

            presentation = importlib.import_module("flexible_drawing.presentation.viewport")
            context = types.SimpleNamespace(scene=FakeScene(), area=FakeArea("PROPERTIES"))
            operator = presentation.OpenViewportOperator()
            operator.SpaceType = "IMAGE_EDITOR"
            self.assertEqual(operator.execute(context), {"FINISHED"})

            openedArea = bpy.windows[-1].screen.areas[0]
            callback, _ = bpy.timerCallbacks.pop()
            for _ in range(presentation._REVEAL_ATTEMPTS - 1):
                self.assertEqual(callback(), presentation._REVEAL_RETRY_INTERVAL)
                openedArea.Draw()
            # The budget is spent, so the timer stops instead of running for the rest of the session.
            self.assertIsNone(callback())
            self.assertEqual(openedArea.regions[0].active_panel_category, "Item")

            # Blender refuses to make a window when it has no area to copy, which is not a crash.
            bpy.ops.wm.window_new = lambda: {"CANCELLED"}
            reported: list[tuple] = []
            refused = presentation.OpenViewportOperator()
            refused.SpaceType = "IMAGE_EDITOR"
            refused.report = lambda level, message: reported.append((level, message))
            self.assertEqual(refused.execute(context), {"CANCELLED"})
            self.assertEqual(len(bpy.windows), 1)
            self.assertIn("IMAGE_EDITOR", reported[0][1])
            module.unregister()

    def test_modal_stroke_batches_a_run_and_keeps_input_the_engine_was_too_busy_to_take(self) -> None:
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

            stroke = importlib.import_module("flexible_drawing.presentation.stroke")
            receiverBinding = importlib.import_module("flexible_drawing.host.receiver_binding")
            documentPresentation = importlib.import_module("flexible_drawing.presentation.document")
            self.assertIn(stroke.PaintStrokeOperator, bpy.registered)
            # A tool joins the toolbar rather than the class registry, so it must not be in both.
            self.assertIn(stroke.PaintTool, bpy.registeredTools)
            self.assertNotIn(stroke.PaintTool, bpy.registered)

            scene = FakeScene()
            modalHandlers: list[object] = []
            context = types.SimpleNamespace(
                scene=scene,
                area=FakeArea("IMAGE_EDITOR"),
                region=fake_image_region(),
                window_manager=types.SimpleNamespace(modal_handler_add=modalHandlers.append),
            )
            # Nothing to draw on until a document is bound.
            self.assertFalse(stroke.PaintStrokeOperator.poll(context))
            documentPresentation.CreateDocumentOperator().execute(context)
            self.assertTrue(stroke.PaintStrokeOperator.poll(context))
            # The 3D View cannot convert a pointer position yet, so it cannot start a stroke.
            self.assertFalse(
                stroke.PaintStrokeOperator.poll(types.SimpleNamespace(scene=scene, area=FakeArea("VIEW_3D")))
            )

            receivers = module._engine.Receivers
            operator = stroke.PaintStrokeOperator()
            self.assertEqual(
                operator.invoke(context, FakeEvent("LEFTMOUSE", 0.0, 100.0, value="PRESS")), {"RUNNING_MODAL"}
            )
            self.assertEqual(modalHandlers, [operator])
            # The press alone does not reach the engine: a run is sent, not a sample.
            self.assertEqual(receivers.Submissions, [])

            run = (
                FakeEvent("INBETWEEN_MOUSEMOVE", 25.0, 100.0, pressure=0.25, isTablet=True),
                FakeEvent("INBETWEEN_MOUSEMOVE", 50.0, 100.0, pressure=0.5, isTablet=True),
                FakeEvent("MOUSEMOVE", 75.0, 100.0, pressure=0.75, isTablet=True),
            )
            for event in run:
                self.assertEqual(operator.modal(context, event), {"RUNNING_MODAL"})

            # One call for the whole run: the press measured, the in-betweens coalesced, then the
            # measured position that ended it. Blender never reports a predicted sample.
            self.assertEqual(len(receivers.Submissions), 1)
            self.assertEqual([sample["origin"] for sample in receivers.Submissions[0]], [0, 1, 1, 0])
            self.assertEqual([sample["sequence"] for sample in receivers.Submissions[0]], [1, 2, 3, 4])
            # Canvas units, measured downward from the top-left of a 1024-unit canvas.
            self.assertEqual((receivers.Submissions[0][0]["x"], receivers.Submissions[0][0]["y"]), (0.0, 0.0))
            self.assertEqual((receivers.Submissions[0][3]["x"], receivers.Submissions[0][3]["y"]), (768.0, 0.0))
            # A mouse reports no pressure, so only the tablet's samples carry one below 1.0.
            self.assertEqual([sample["pressure"] for sample in receivers.Submissions[0]], [1.0, 0.25, 0.5, 0.75])
            # One receiver for the scene, opened once and reused, because a second would give the
            # same canvas two sets of committed tiles and neither would be the whole picture.
            self.assertEqual(len(receivers.Seeds), 1)
            self.assertEqual(receivers.InputCapabilities, [receiverBinding.BLENDER_INPUT_CAPABILITIES])
            self.assertEqual(receivers.BatchCapacities, [receiverBinding.MAXIMUM_BATCH_SAMPLES])
            self.assertEqual([kind for kind, _, _ in receivers.Contacts], ["begin"])
            # Submissions are ordered within the contact, so a run that arrives late is refused
            # rather than applied out of order.
            self.assertEqual(receivers.Ordinals, [1])

            # Something that is not pointer motion is not ours to swallow.
            self.assertEqual(operator.modal(context, FakeEvent("LEFT_SHIFT", 75.0, 100.0)), {"PASS_THROUGH"})

            # The engine refuses while it is still working. That input is kept, not dropped, and
            # goes out with the next run instead.
            receivers.BusyRefusals = 1
            self.assertEqual(operator.modal(context, FakeEvent("MOUSEMOVE", 100.0, 100.0)), {"RUNNING_MODAL"})
            self.assertEqual(len(receivers.Submissions), 1)
            self.assertEqual(operator.modal(context, FakeEvent("MOUSEMOVE", 200.0, 100.0)), {"RUNNING_MODAL"})
            self.assertEqual(len(receivers.Submissions), 2)
            self.assertEqual([sample["sequence"] for sample in receivers.Submissions[1]], [5, 6])

            # Releasing sends whatever arrived after the last measured position and ends the stroke.
            operator.modal(context, FakeEvent("INBETWEEN_MOUSEMOVE", 300.0, 100.0))
            self.assertEqual(
                operator.modal(context, FakeEvent("LEFTMOUSE", 300.0, 100.0, value="RELEASE")), {"FINISHED"}
            )
            self.assertEqual(len(receivers.Submissions), 3)
            self.assertEqual(scene["flexible_drawing_receiver_revision"], 3)
            self.assertEqual(scene["flexible_drawing_committed_sequence"], 7)
            self.assertEqual(context.area.Redraws, 1)

            # Cancelling drops only what was never sent; it cannot recall a committed submission.
            cancelled = stroke.PaintStrokeOperator()
            cancelled.invoke(context, FakeEvent("LEFTMOUSE", 0.0, 100.0, value="PRESS"))
            cancelled.modal(context, FakeEvent("INBETWEEN_MOUSEMOVE", 10.0, 100.0))
            self.assertEqual(cancelled.modal(context, FakeEvent("ESC", 10.0, 100.0, value="PRESS")), {"CANCELLED"})
            self.assertEqual(len(receivers.Submissions), 3)

            # The source owns exactly the receiver's declared bound. It refuses another event
            # before growing or submitting a partial run.
            inputSource = importlib.import_module("flexible_drawing.host.input_source")
            bounded = inputSource.InputSourceOnBlender(
                module._engine, receiverBinding.Bind(module._engine, scene), contactId=99, maximumBatchSamples=1
            )
            bounded.Begin()
            captured = {
                "x": 1.0,
                "y": 1.0,
                "pressure": 1.0,
                "time_nanoseconds": 1,
                "sequence": 1,
                "origin": "MEASURED",
            }
            bounded.Collect(captured)
            with self.assertRaises(inputSource.InputSourceOverflowError):
                bounded.Collect(captured)
            self.assertEqual(bounded.Unsent, 1)
            self.assertEqual(bounded.Cancel(), 1)
            module.unregister()
            self.assertEqual(bpy.registeredTools, [])

    def test_image_editor_pointer_positions_convert_to_canvas_units(self) -> None:
        # Loaded on its own, with no bpy: converting a pointer position is arithmetic, and this
        # fails if the module ever reaches for Blender to do it.
        spec = importlib.util.spec_from_file_location(
            "flexible_drawing_host_viewport", self.extension / "host" / "viewport.py"
        )
        viewport = importlib.util.module_from_spec(spec)
        # `dataclass` resolves annotations through the defining module, so it has to be findable.
        sys.modules[spec.name] = viewport
        assert spec.loader is not None
        spec.loader.exec_module(viewport)

        extent = viewport.CanvasExtent(Width=1920.0, Height=1080.0)
        # Blender's View2D reports the image's normalized space, so a fake one is enough here.
        region = types.SimpleNamespace(view2d=types.SimpleNamespace(region_to_view=lambda x, y: (x / 100.0, y / 200.0)))

        # The engine measures the canvas downward from the top-left, so the vertical axis flips.
        self.assertEqual(viewport.ImageEditorRegionToCanvas(region, 0.0, 200.0, extent), (0.0, 0.0))
        self.assertEqual(viewport.ImageEditorRegionToCanvas(region, 100.0, 0.0, extent), (1920.0, 1080.0))
        self.assertEqual(viewport.ImageEditorRegionToCanvas(region, 50.0, 100.0, extent), (960.0, 540.0))
        # A stroke that leaves the canvas is the caller's decision, so nothing is clamped.
        self.assertEqual(viewport.ImageEditorRegionToCanvas(region, -100.0, 400.0, extent), (-1920.0, -1080.0))

        with self.assertRaises(ValueError):
            viewport.OpenViewport(types.SimpleNamespace(type="PROPERTIES"), "PROPERTIES")
        self.assertFalse(viewport.OpenViewport(None, "IMAGE_EDITOR"))
        # An area Blender has not turned into a viewport yet has no sidebar to reveal.
        self.assertFalse(viewport.RevealViewportSidebar(types.SimpleNamespace(type="PROPERTIES")))

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

    def test_native_input_batch_reuses_bridge_storage(self) -> None:
        module = self._LoadAbi()
        records: list[tuple[int, str, str]] = []
        bridge = module.EngineBridge.FromLibrary(
            module.LoadLibrary(self.library),
            lambda severity, category, message: records.append((severity, category, message)),
        )
        try:
            self.assertEqual(bridge.GrantedAbi, (module.FD_ABI_VERSION_MAJOR, module.FD_ABI_VERSION_MINOR))
            self.assertTrue(any(category == "engine" and "ABI" in message for _, category, message in records))
            receiver = bridge.Receivers.Create(
                seed=42, tileExtent=64, maximumBatchSamples=64, inputCapabilities=module.FD_RECEIVER_INPUT_PRESSURE
            )
            self.assertNotEqual(receiver.ReceiverId, 0)
            bridge.Receivers.BeginContact(receiver.ReceiverId, 1)
            batch = bridge.Receivers.Batch()
            for index, x in enumerate((1.0, 65.0), start=1):
                batch.Append(
                    x=x,
                    y=1.0,
                    pressure=0.5,
                    timeNanoseconds=index,
                    sequence=index,
                    origin=module.FD_RECEIVER_ORIGIN_MEASURED,
                )
            self.assertEqual(len(batch), 2)
            first = bridge.Receivers.Submit(receiver.ReceiverId, 1, 1, batch)
            # A reused batch keeps its memory, so a stroke that submits every frame allocates once.
            address = ctypes.addressof(ctypes.c_char.from_buffer(batch._arrays["xy"]))
            batch.Clear()
            self.assertEqual(len(batch), 0)
            batch.Append(x=130.0, y=1.0, sequence=3, origin=module.FD_RECEIVER_ORIGIN_MEASURED)
            self.assertEqual(ctypes.addressof(ctypes.c_char.from_buffer(batch._arrays["xy"])), address)
            second = bridge.Receivers.Submit(receiver.ReceiverId, 1, 2, batch)
            bridge.Receivers.EndContact(receiver.ReceiverId, 1)

            # A field never given allocates nothing; the engine uses the default the header states.
            bridge.Receivers.BeginContact(receiver.ReceiverId, 2)
            sparse = bridge.Receivers.Batch()
            sparse.Append(x=1.0, y=1.0)
            # A position is one array of pairs; nothing else is allocated until it is given.
            self.assertEqual(sorted(sparse._arrays), ["xy"])
            self.assertEqual(bridge.Receivers.Submit(receiver.ReceiverId, 2, 1, sparse).PredictedSampleCount, 0)
            bridge.Receivers.EndContact(receiver.ReceiverId, 2)

            # Numbers that already exist are pointed at, never copied.
            positions = array.array("d", [1.0, 1.0, 65.0, 1.0])
            borrowed = module.InputBatch.Borrowing(2, xy=positions)
            bridge.Receivers.BeginContact(receiver.ReceiverId, 3)
            self.assertEqual(bridge.Receivers.Submit(receiver.ReceiverId, 3, 1, borrowed).AcceptedSampleCount, 2)
            self.assertEqual(
                ctypes.cast(borrowed._describe().xy, ctypes.c_void_p).value,
                ctypes.addressof(ctypes.c_char.from_buffer(positions)),
            )
            with self.assertRaises(module.EngineError):
                module.InputBatch.Borrowing(2, xy=array.array("d", [1.0, 1.0]))  # two samples need four numbers
            with self.assertRaises(module.EngineError):
                module.InputBatch.Borrowing(2, pressure=array.array("d", [1.0, 1.0]))  # a position is not optional
            with self.assertRaises(module.EngineError):
                borrowed.Append(x=1.0, y=1.0)  # it points at someone else's memory
            # A revision, not a tile count: what a host stores and compares is what the receiver
            # accepted, and where that is drawn is its presentation provider's business.
            self.assertEqual(first.Revision, 1)
            self.assertEqual(second.Revision, 2)
            self.assertEqual(first.CommittedSequence, 2)
            self.assertEqual(second.CommittedSequence, 3)
            bridge.Receivers.EndContact(receiver.ReceiverId, 3)
            bridge.Receivers.Close(receiver.ReceiverId)
            # A closed receiver is gone, and a call naming it is refused rather than guessed at.
            with self.assertRaises(module.EngineError) as closed:
                bridge.Receivers.BeginContact(receiver.ReceiverId, 4)
            self.assertEqual(closed.exception.Status, module.FD_RECEIVER_STATUS_UNKNOWN)
            document = bridge.Documents.Create("Drawing")
            self.assertEqual(bridge.Documents.Query(document.DocumentId).DocumentId, document.DocumentId)
        finally:
            bridge.Shutdown()
        # Every table and entry point dies with the engine, so a later call must refuse rather than
        # dereference a freed handle.
        with self.assertRaises(module.EngineError):
            bridge.Documents.Query(1)

    def test_a_sized_record_carries_its_own_size(self) -> None:
        """The one rule a host cannot be trusted to remember is stamped by the constructor."""
        module = self._LoadAbi()
        for record in (module.generated.fd_document_snapshot, module.generated.fd_input_batch):
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

    def test_package_is_reproducible_and_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = [root / "one.zip", root / "two.zip"]
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
    args, remaining = parser.parse_known_args()
    PluginTests.source = args.project_source_dir
    PluginTests.extension = args.extension_dir.resolve()
    PluginTests.library = args.library
    unittest.main(argv=[sys.argv[0], *remaining])
