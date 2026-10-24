"""System-wide hotkey for Windows.

The hotkey is registered with the Windows API function ``RegisterHotKey``
(called through ``ctypes``). Windows then sends a single ``WM_HOTKEY``
message when the combination is pressed. QuickDesk does not watch or
intercept any other keys.

``WM_HOTKEY`` is delivered to the message queue of the thread that
registered the hotkey, so registration and waiting happen in one small
background thread. That thread blocks in ``GetMessageW`` (no polling)
and calls the callback for every press. Tkinter keeps its own event loop
in the main thread; the callback is responsible for passing the event
over to it (see ``QuickDeskApp``).
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

DEFAULT_HOTKEY = "Ctrl+Alt+Q"

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # holding the keys down does not repeat the event

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_USER = 0x0400
PM_NOREMOVE = 0x0000

ERROR_HOTKEY_ALREADY_REGISTERED = 1409

HOTKEY_ID = 1

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}

_NAMED_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "home": 0x24,
    "end": 0x23,
    "insert": 0x2D,
    "delete": 0x2E,
}


class HotkeyError(Exception):
    """Raised when a hotkey is invalid or cannot be registered."""


def parse_hotkey(text: str) -> tuple[int, int]:
    """Convert text like ``"Ctrl+Alt+Space"`` to (modifiers, virtual key code).

    At least one modifier is required, so that a normal key such as "A"
    is never taken away from other programs.
    """
    parts = [part.strip().lower() for part in text.split("+")]
    if len(parts) < 2 or not all(parts):
        raise HotkeyError(f"Hotkey {text!r} must look like 'Ctrl+Alt+Space'.")

    *modifier_names, key_name = parts
    modifiers = 0
    for name in modifier_names:
        if name not in _MODIFIERS:
            raise HotkeyError(f"Unknown modifier {name!r} in hotkey {text!r}.")
        modifiers |= _MODIFIERS[name]

    return modifiers, _virtual_key(key_name, text)


def _virtual_key(name: str, text: str) -> int:
    if name in _NAMED_KEYS:
        return _NAMED_KEYS[name]
    if len(name) == 1 and (name.isascii() and name.isalnum()):
        return ord(name.upper())  # virtual key codes of A-Z and 0-9 equal their ASCII codes
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x70 + int(name[1:]) - 1  # VK_F1 = 0x70
    raise HotkeyError(f"Unknown key {name!r} in hotkey {text!r}.")


class GlobalHotkey:
    """Registers one system-wide hotkey while it is started."""

    def __init__(self, hotkey: str, callback: Callable[[], None]) -> None:
        self.hotkey = hotkey
        self._modifiers, self._key = parse_hotkey(hotkey)
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._error: str | None = None

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 2.0) -> None:
        """Register the hotkey. Raises HotkeyError if Windows refuses it."""
        if sys.platform != "win32":
            raise HotkeyError("The global hotkey is only available on Windows.")
        if self.active:
            return
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="QuickDeskHotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise HotkeyError(f"Registering the hotkey {self.hotkey} took too long.")
        if self._error:
            self._thread.join(timeout)
            self._thread = None
            raise HotkeyError(self._error)

    def stop(self, timeout: float = 1.0) -> None:
        """Release the hotkey and end the background thread."""
        if not self.active:
            return
        import ctypes

        ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout)
        self._thread = None

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT
        ]

        msg = wintypes.MSG()
        # Make sure this thread has a message queue before stop() can post WM_QUIT to it.
        user32.PeekMessageW(ctypes.byref(msg), None, WM_USER, WM_USER, PM_NOREMOVE)
        self._thread_id = kernel32.GetCurrentThreadId()

        if not user32.RegisterHotKey(None, HOTKEY_ID, self._modifiers | MOD_NOREPEAT, self._key):
            self._error = _describe_error(self.hotkey, ctypes.get_last_error())
            self._ready.set()
            return
        self._ready.set()

        try:
            # GetMessageW sleeps until a message arrives; it returns 0 on WM_QUIT.
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self._callback()
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)


def foreground_window_is_ours() -> bool | None:
    """True if the active window on screen belongs to this process.

    Returns None outside Windows, where the check is not available.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    import os
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return process_id.value == os.getpid()


def _describe_error(hotkey: str, code: int) -> str:
    if code == ERROR_HOTKEY_ALREADY_REGISTERED:
        return (
            f"The hotkey {hotkey} is already used by another program "
            f"(or QuickDesk is already running)."
        )
    return f"The hotkey {hotkey} could not be registered (Windows error {code})."
