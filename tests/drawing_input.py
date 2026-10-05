"""Who draws in the Realtime Plane window during a check: posted pointer events, or a person.

Every check that needs strokes in the real Realtime Plane takes `--input synthetic` or
`--input person` and asks this module for strokes, so the same check runs unattended under CTest or
by hand with a pen. Synthetic strokes are posted to the operating system as a mouse's would be, so
they travel the whole native input path; they need macOS and permission to post events
(Accessibility, for the terminal that runs the check). A person is asked to draw and the check
waits until they say they are done, or, with no terminal to answer, for a fixed time.

```python
drawing = DrawingInput.Open("synthetic")  # None when events cannot be posted here
drawing.Draw(realtimePlanePid, strokes=3, seconds=1.0, seed=0, what="three strokes across the canvas")
```
"""

from __future__ import annotations

from collections.abc import Callable
import ctypes
import ctypes.util
import math
import random
import sys
import time

#: Choices of `--input`.
INPUTS = ("synthetic", "person")


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("width", ctypes.c_double), ("height", ctypes.c_double)]


_ON_SCREEN_ONLY = 1 << 0
_EXCLUDE_DESKTOP = 1 << 4
_SINT64 = 4  # kCFNumberSInt64Type
_IGNORING_OTHER_APPS = 1 << 1  # NSApplicationActivateIgnoringOtherApps
_WINDOW_KEYS = (b"kCGWindowOwnerPID", b"kCGWindowLayer", b"kCGWindowBounds")
#: Height of a window's title bar, which takes no strokes.
_TITLE_BAR_POINTS = 28.0


class SyntheticPointer:
    """Posts left-button pointer events through Core Graphics, as a mouse would deliver them."""

    _DOWN, _UP, _DRAGGED = 1, 2, 6

    def __init__(self, rate: float = 240.0) -> None:
        self.Rate = rate
        """Events per second while a stroke is drawn."""
        self._cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        self._cg.CGPreflightPostEventAccess.restype = ctypes.c_bool
        self._cg.CGRequestPostEventAccess.restype = ctypes.c_bool
        self._cg.CGMainDisplayID.restype = ctypes.c_uint32
        self._cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
        self._cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t
        self._cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        self._cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, _Point, ctypes.c_uint32]
        self._cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        self._cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        self._cf.CFRelease.argtypes = [ctypes.c_void_p]

    @property
    def Description(self) -> str:
        """What drew, for a report."""
        return f"synthetic pointer events at {self.Rate:.0f} Hz"

    def Allowed(self) -> bool:
        """Whether posted events can reach a window: permission granted, and the screen not locked.

        Asks the system for permission once when this process does not have it yet. While the screen
        is locked, posted events reach no application, so a check cannot draw.
        """
        allowed = bool(self._cg.CGPreflightPostEventAccess() or self._cg.CGRequestPostEventAccess())
        return allowed and not self._screenLocked()

    def _screenLocked(self) -> bool:
        self._cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
        self._cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        self._cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        self._cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        self._cf.CFBooleanGetValue.restype = ctypes.c_bool
        self._cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        session = self._cg.CGSessionCopyCurrentDictionary()
        if not session:
            return True  # no graphical session at all: nothing can be drawn
        key = self._cf.CFStringCreateWithCString(None, b"CGSSessionScreenIsLocked", 0x08000100)
        value = self._cf.CFDictionaryGetValue(session, key)
        locked = bool(value) and self._cf.CFBooleanGetValue(value)
        self._cf.CFRelease(key)
        self._cf.CFRelease(session)
        return locked

    def _post(self, kind: int, x: float, y: float) -> None:
        event = self._cg.CGEventCreateMouseEvent(None, kind, _Point(x, y), 0)
        self._cg.CGEventPost(0, event)  # the HID tap: the event enters as a device's would
        self._cf.CFRelease(event)

    def _windows(self) -> list[tuple[int, int, tuple[float, float, float, float]]]:
        """Every window on screen, front to back: its process, its layer, and its bounds in points."""
        cg, cf = self._cg, self._cf
        cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
        cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        cg.CGRectMakeWithDictionaryRepresentation.restype = ctypes.c_bool
        cg.CGRectMakeWithDictionaryRepresentation.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Rect)]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        keys = {name: cf.CFStringCreateWithCString(None, name, 0x08000100) for name in _WINDOW_KEYS}
        found = []
        windows = cg.CGWindowListCopyWindowInfo(_ON_SCREEN_ONLY | _EXCLUDE_DESKTOP, 0)
        for index in range(cf.CFArrayGetCount(windows) if windows else 0):
            window = cf.CFArrayGetValueAtIndex(windows, index)
            numbers = []
            for name in (b"kCGWindowOwnerPID", b"kCGWindowLayer"):
                value = ctypes.c_int64()
                cf.CFNumberGetValue(cf.CFDictionaryGetValue(window, keys[name]), _SINT64, ctypes.byref(value))
                numbers.append(value.value)
            rect = _Rect()
            if cg.CGRectMakeWithDictionaryRepresentation(
                cf.CFDictionaryGetValue(window, keys[b"kCGWindowBounds"]), rect
            ):
                found.append((numbers[0], numbers[1], (rect.x, rect.y, rect.width, rect.height)))
        for key in keys.values():
            cf.CFRelease(key)
        if windows:
            cf.CFRelease(windows)
        return found

    def _window(self, pid: int) -> tuple[float, float, float, float] | None:
        """The bounds of the process's largest ordinary window on screen, or None."""
        owned = [bounds for owner, layer, bounds in self._windows() if owner == pid and layer == 0]
        return max(owned, key=lambda bounds: bounds[2] * bounds[3], default=None)

    def _inFront(self, pid: int, x: float, y: float) -> bool:
        """Whether the topmost ordinary window at (x, y) belongs to the process."""
        for owner, layer, (left, top, width, height) in self._windows():
            if layer == 0 and left <= x < left + width and top <= y < top + height:
                return owner == pid
        return False

    def _activate(self, pid: int) -> None:
        """Bring the process and its windows to the front through the accessibility interface.

        Asking an application to activate another is ignored by recent macOS; the accessibility
        interface, which posting events already needs permission for, is not.
        """
        ax = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        cf = self._cf
        ax.AXUIElementCreateApplication.restype = ctypes.c_void_p
        ax.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
        ax.AXUIElementSetAttributeValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        ax.AXUIElementCopyAttributeValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        ax.AXUIElementPerformAction.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        wanted = (b"AXFrontmost", b"AXWindows", b"AXRaise")
        names = {name: cf.CFStringCreateWithCString(None, name, 0x08000100) for name in wanted}
        application = ax.AXUIElementCreateApplication(pid)
        true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
        ax.AXUIElementSetAttributeValue(application, names[b"AXFrontmost"], true)
        windows = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(application, names[b"AXWindows"], ctypes.byref(windows)) == 0 and windows:
            for index in range(cf.CFArrayGetCount(windows)):
                ax.AXUIElementPerformAction(cf.CFArrayGetValueAtIndex(windows, index), names[b"AXRaise"])
            cf.CFRelease(windows)
        cf.CFRelease(application)
        for name in names.values():
            cf.CFRelease(name)

    def _bringToFront(self, pid: int) -> tuple[float, float, float, float]:
        """Bring the window to the front and return its bounds; fail rather than draw elsewhere."""
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            bounds = self._window(pid)
            if bounds is not None:
                centre = (bounds[0] + bounds[2] / 2.0, bounds[1] + bounds[3] / 2.0)
                if self._inFront(pid, *centre):
                    return bounds
                self._activate(pid)
            time.sleep(0.1)
        raise RuntimeError(f"the Realtime Plane window (process {pid}) could not be brought to the front")

    def Draw(
        self,
        window: int,
        strokes: int,
        seconds: float,
        seed: int,
        what: str = "",
        started: Callable[[], None] = lambda: None,
    ) -> None:
        """Draw `strokes` wavy strokes of `seconds` each inside the window of process `window`.

        The window is brought to the front first, and before every stroke the point it starts at is
        checked to belong to it, so no event ever lands in another window. `what` is for a person
        only. `started` is called right before the first stroke, so a check can time the strokes alone.
        """
        left, top, width, height = self._bringToFront(window)
        top += _TITLE_BAR_POINTS
        height -= _TITLE_BAR_POINTS
        centre = (left + width / 2.0, top + height / 2.0)
        half = (width * 0.4, height * 0.35)
        randomness = random.Random(seed)
        started()
        for _ in range(strokes):
            row = randomness.uniform(-half[1], half[1])
            if not self._inFront(window, centre[0] - half[0], centre[1] + row):
                self._bringToFront(window)
            steps = max(2, int(seconds * self.Rate))
            start = time.perf_counter()
            for step in range(steps):
                x = centre[0] - half[0] + 2.0 * half[0] * step / (steps - 1)
                y = centre[1] + row + min(40.0, half[1] * 0.2) * math.sin(step / 9.0)
                self._post(self._DOWN if step == 0 else self._DRAGGED, x, y)
                # Paced against the start, so a late wake-up does not slow the whole stroke.
                delay = start + (step + 1) / self.Rate - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            self._post(self._UP, x, y)
            time.sleep(0.15)


class Person:
    """Asks the person at the machine to draw, and waits for them."""

    def __init__(self, device: str = "", seconds: float = 15.0) -> None:
        self.Device = device
        self._seconds = seconds

    @property
    def Description(self) -> str:
        """What drew, for a report."""
        return f"a person{f' with {self.Device}' if self.Device else ''}"

    def Draw(
        self,
        window: int,
        strokes: int,
        seconds: float,
        seed: int,
        what: str = "",
        started: Callable[[], None] = lambda: None,
    ) -> None:
        """Ask for `what`, about `strokes` strokes of `seconds` each, and wait until the person is done."""
        request = what or f"{strokes} stroke(s) of about {seconds:.0f} s each"
        started()  # a person starts whenever they like; the whole wait counts
        if sys.stdin.isatty():
            input(f"\nDraw {request} in the Realtime Plane window, then press Enter here... ")
        else:
            print(f"\nDraw {request} in the Realtime Plane window within {self._seconds:.0f} s", flush=True)
            time.sleep(self._seconds)


class DrawingInput:
    """Chooses who draws from a check's `--input`."""

    @staticmethod
    def Open(kind: str, device: str = "", rate: float = 240.0) -> SyntheticPointer | Person | None:
        """The input for `kind`; None for synthetic input where events cannot be posted."""
        if kind == "person":
            return Person(device)
        if sys.platform != "darwin":
            return None
        pointer = SyntheticPointer(rate)
        return pointer if pointer.Allowed() else None
