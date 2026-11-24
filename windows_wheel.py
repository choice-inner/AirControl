"""Windows wheel input with explicit WHEEL_DELTA units and error reporting."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


WHEEL_DELTA = 120
MOUSEEVENTF_WHEEL = 0x0800


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUTUNION)]


class WindowsWheelOutput:
    def __init__(self, send_input=None):
        if send_input is None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
            user32.SendInput.restype = wintypes.UINT
            send_input = user32.SendInput
        self._send_input = send_input

    def scroll(self, steps: int) -> None:
        if isinstance(steps, bool) or not isinstance(steps, int):
            raise ValueError("wheel steps must be an integer")
        delta = steps * WHEEL_DELTA
        if not -(2 ** 31) <= delta < 2 ** 31:
            raise ValueError("wheel delta exceeds signed 32-bit range")
        if not delta:
            return
        # SendInput takes a DWORD containing a signed two's-complement wheel delta.
        event = INPUT(type=0, mi=MOUSEINPUT(
            mouseData=delta & 0xFFFFFFFF, dwFlags=MOUSEEVENTF_WHEEL,
        ))
        ctypes.set_last_error(0)
        if self._send_input(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            code = ctypes.get_last_error()
            raise OSError(code, "Windows rejected wheel input; check target window permissions")
