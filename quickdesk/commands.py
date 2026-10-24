"""Command model, input validation and opening of commands.

A *command* is something QuickDesk can open: a Windows application,
a local file or folder, or a website. This module knows how to validate
a command and how to open it safely (no shell, no arbitrary arguments).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
import webbrowser
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

MAX_NAME_LENGTH = 60
MAX_DESCRIPTION_LENGTH = 200


class CommandType(str, Enum):
    APP = "app"
    PATH = "path"
    URL = "url"

    @property
    def label(self) -> str:
        return _TYPE_LABELS[self]

    @property
    def keywords(self) -> tuple[str, ...]:
        """Words that describe the category; used by search."""
        return _TYPE_KEYWORDS[self]


_TYPE_LABELS = {
    CommandType.APP: "Application",
    CommandType.PATH: "File or folder",
    CommandType.URL: "Website",
}

_TYPE_KEYWORDS = {
    CommandType.APP: ("application", "app", "program"),
    CommandType.PATH: ("file", "folder", "directory"),
    CommandType.URL: ("website", "site", "web", "url", "link"),
}


class ValidationError(ValueError):
    """Raised when user input for a command is invalid."""


class LaunchError(RuntimeError):
    """Raised when a command cannot be opened."""


class ProtectedCommandError(PermissionError):
    """Raised on an attempt to edit or delete a built-in command."""


@dataclass(frozen=True)
class Command:
    id: str
    name: str
    description: str
    type: CommandType
    target: str
    builtin: bool = False

    @classmethod
    def create(cls, name: str, description: str, type: CommandType | str, target: str) -> Command:
        """Validate user input and build a new user command."""
        name, description, type_, target = validate_command_input(name, description, type, target)
        return cls(uuid.uuid4().hex, name, description, type_, target)

    def edited(self, name: str, description: str, type: CommandType | str, target: str) -> Command:
        """Return a validated copy with new values. Built-in commands cannot be edited."""
        if self.builtin:
            raise ProtectedCommandError(f"'{self.name}' is a built-in command and cannot be changed.")
        name, description, type_, target = validate_command_input(name, description, type, target)
        return replace(self, name=name, description=description, type=type_, target=target)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "type": self.type.value,
            "target": self.target,
            "builtin": self.builtin,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Command:
        """Build a command from JSON data. Raises ValueError on malformed data."""
        if not isinstance(data, dict):
            raise ValueError("Command entry must be a JSON object.")
        try:
            id_, name, target = data["id"], data["name"], data["target"]
            type_ = CommandType(data["type"])
        except KeyError as error:
            raise ValueError(f"Command entry is missing the field {error}.") from None
        description = data.get("description", "")
        builtin = data.get("builtin", False)
        if not all(isinstance(value, str) for value in (id_, name, target, description)):
            raise ValueError("Command fields 'id', 'name', 'description' and 'target' must be strings.")
        if not id_.strip() or not name.strip() or not target.strip():
            raise ValueError("Command fields 'id', 'name' and 'target' must not be empty.")
        if not isinstance(builtin, bool):
            raise ValueError("Command field 'builtin' must be true or false.")
        return cls(id_, name, description, type_, target, builtin)


# --- Validation -------------------------------------------------------------


def validate_command_input(
    name: str, description: str, type: CommandType | str, target: str
) -> tuple[str, str, CommandType, str]:
    """Check user input and return cleaned values. Raises ValidationError."""
    name = name.strip()
    description = description.strip()
    target = target.strip()

    if not name:
        raise ValidationError("Name must not be empty.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Name must be at most {MAX_NAME_LENGTH} characters.")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(f"Description must be at most {MAX_DESCRIPTION_LENGTH} characters.")
    try:
        type_ = CommandType(type)
    except ValueError:
        raise ValidationError(f"Unknown command type: {type!r}.") from None
    if not target:
        raise ValidationError("Path or URL must not be empty.")

    if type_ is CommandType.URL:
        validate_url(target)
    elif type_ is CommandType.PATH:
        resolve_path(target)
    else:
        resolve_executable(target)
    return name, description, type_, target


def validate_url(url: str) -> str:
    """Accept only absolute http:// or https:// URLs."""
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValidationError("Website address must start with http:// or https://.")
    if not parsed.netloc or any(char.isspace() for char in url.strip()):
        raise ValidationError("Website address is not valid.")
    return url.strip()


def resolve_path(target: str) -> Path:
    """Expand environment variables and check that the file or folder exists."""
    path = Path(os.path.expandvars(os.path.expanduser(target.strip())))
    if not path.exists():
        raise ValidationError(f"File or folder does not exist: {path}")
    return path


def resolve_executable(target: str) -> str:
    """Find the .exe file for an application.

    The target is either a full path to an .exe file or a program name
    available on PATH (for example ``notepad.exe``). Only .exe files are
    allowed, so scripts such as .bat or .cmd cannot be used to run
    terminal commands.
    """
    expanded = os.path.expandvars(os.path.expanduser(target.strip()))
    if os.sep in expanded or (os.altsep and os.altsep in expanded):
        path = Path(expanded)
        if not path.is_file():
            raise ValidationError(f"Application file does not exist: {path}")
        resolved = str(path)
    else:
        found = shutil.which(expanded)
        if found is None:
            raise ValidationError(f"Application not found: {expanded}")
        resolved = found
    if sys.platform == "win32" and Path(resolved).suffix.lower() != ".exe":
        raise ValidationError("Application must be an .exe file.")
    return resolved


# --- Opening commands -------------------------------------------------------


def launch(command: Command) -> None:
    """Open a command. Raises LaunchError with a user-friendly message on failure."""
    try:
        if command.type is CommandType.URL:
            url = validate_url(command.target)
            if not webbrowser.open(url):
                raise LaunchError("No web browser is available to open the link.")
        elif command.type is CommandType.PATH:
            _open_path(resolve_path(command.target))
        else:
            subprocess.Popen([resolve_executable(command.target)], close_fds=True)
    except ValidationError as error:
        raise LaunchError(str(error)) from error
    except OSError as error:
        raise LaunchError(f"Could not open '{command.name}': {error.strerror or error}") from error


def _open_path(path: Path) -> None:
    """Open a file or folder with the program associated with it."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]  # Windows only
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# --- Built-in commands ------------------------------------------------------


def downloads_folder() -> Path:
    """Return the user's Downloads folder.

    On Windows the real location is asked from the system, because users
    can move the folder (for example to another drive).
    """
    if sys.platform == "win32":
        known = _windows_known_folder("{374DE290-123F-4565-9164-39C4925E467B}")
        if known is not None:
            return known
    return Path.home() / "Downloads"


def _windows_known_folder(folder_id: str) -> Path | None:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    guid = GUID()
    path_ptr = ctypes.c_wchar_p()
    try:
        if ctypes.oledll.ole32.CLSIDFromString(folder_id, ctypes.byref(guid)) != 0:
            return None
        ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path_ptr))
        return Path(path_ptr.value) if path_ptr.value else None
    except OSError:
        return None
    finally:
        if path_ptr:
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)


def builtin_commands() -> list[Command]:
    """Commands that QuickDesk provides out of the box."""
    return [
        Command("builtin-notepad", "Notepad", "Windows text editor", CommandType.APP, "notepad.exe", True),
        Command("builtin-calculator", "Calculator", "Windows calculator", CommandType.APP, "calc.exe", True),
        Command("builtin-paint", "Paint", "Windows drawing program", CommandType.APP, "mspaint.exe", True),
        Command("builtin-explorer", "File Explorer", "Browse files and folders", CommandType.APP, "explorer.exe", True),
        Command("builtin-downloads", "Downloads", "Your Downloads folder", CommandType.PATH, str(downloads_folder()), True),
        Command("builtin-github", "GitHub", "Code hosting and collaboration", CommandType.URL, "https://github.com", True),
        Command("builtin-youtube", "YouTube", "Video hosting", CommandType.URL, "https://www.youtube.com", True),
    ]


def merge_builtins(commands: Iterable[Command], builtins: Iterable[Command]) -> list[Command]:
    """Make sure every built-in command is present and unmodified.

    Built-in entries from the saved file are replaced by the current
    definitions (so, for example, the Downloads path stays correct);
    missing built-ins are added. User commands are kept in their order.
    """
    builtins = list(builtins)
    builtin_ids = {command.id for command in builtins}
    user_commands = [command for command in commands if command.id not in builtin_ids and not command.builtin]
    return builtins + user_commands


class CommandLibrary:
    """In-memory list of commands with protection for built-in ones."""

    def __init__(self, commands: Iterable[Command]) -> None:
        self._commands = list(commands)

    @property
    def commands(self) -> tuple[Command, ...]:
        return tuple(self._commands)

    def get(self, command_id: str) -> Command:
        for command in self._commands:
            if command.id == command_id:
                return command
        raise KeyError(command_id)

    def add(self, command: Command) -> None:
        if any(existing.id == command.id for existing in self._commands):
            raise ValueError(f"Command with id {command.id!r} already exists.")
        self._commands.append(command)

    def update(self, command: Command) -> None:
        index = self._index_of_user_command(command.id)
        self._commands[index] = command

    def remove(self, command_id: str) -> None:
        """Remove a command entry. This never touches files on disk."""
        index = self._index_of_user_command(command_id)
        del self._commands[index]

    def _index_of_user_command(self, command_id: str) -> int:
        for index, command in enumerate(self._commands):
            if command.id == command_id:
                if command.builtin:
                    raise ProtectedCommandError(f"'{command.name}' is a built-in command and cannot be changed.")
                return index
        raise KeyError(command_id)
