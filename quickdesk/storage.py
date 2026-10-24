"""Reading and writing the commands file (JSON).

By default the file lives in ``%APPDATA%/QuickDesk/commands.json`` so that
user data never ends up in the source code folder.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .commands import Command

FILE_VERSION = 1
CONFIG_DIR_ENV = "QUICKDESK_HOME"


def default_config_dir() -> Path:
    """Folder for QuickDesk data: %APPDATA%/QuickDesk, or QUICKDESK_HOME if set."""
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "QuickDesk"


class StorageError(Exception):
    """Raised when the commands file cannot be read or written."""


@dataclass(frozen=True)
class LoadResult:
    commands: list[Command]
    warning: str | None = None


class CommandStore:
    """Loads and saves commands in a single JSON file."""

    def __init__(self, path: Path, defaults: Iterable[Command]) -> None:
        self.path = Path(path)
        self._defaults = list(defaults)
        # Set when a damaged file could not be backed up: saving is blocked
        # so the user's original data is never overwritten silently.
        self.read_only = False

    def load(self) -> LoadResult:
        """Read commands from disk.

        * No file or an empty file: the default commands are written and returned.
        * Damaged file: it is renamed to a backup (never deleted), the defaults
          are written instead and a warning explains what happened.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        except (OSError, UnicodeDecodeError) as error:
            return self._recover(f"it could not be read ({error})")

        if not text.strip():
            self.save(self._defaults)
            return LoadResult(list(self._defaults))

        try:
            return LoadResult(parse_commands(text))
        except ValueError as error:
            return self._recover(f"it is damaged ({error})")

    def save(self, commands: Iterable[Command]) -> None:
        """Write commands atomically: a temporary file replaces the old one."""
        if self.read_only:
            raise StorageError(
                f"Changes are not saved: the damaged file {self.path} must be fixed or removed first."
            )
        data = {"version": FILE_VERSION, "commands": [command.to_dict() for command in commands]}
        temp_path = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp_path, self.path)
        except OSError as error:
            raise StorageError(f"Could not save commands to {self.path}: {error}") from error

    def _recover(self, reason: str) -> LoadResult:
        backup = self._backup_path()
        try:
            os.replace(self.path, backup)
        except OSError as error:
            # The damaged file stays where it is; do not overwrite it.
            self.read_only = True
            return LoadResult(
                list(self._defaults),
                f"The commands file {self.path} could not be loaded because {reason}. "
                f"It also could not be backed up ({error}), so changes will not be saved "
                f"over it until the file is fixed or removed.",
            )
        self.save(self._defaults)
        return LoadResult(
            list(self._defaults),
            f"The commands file could not be loaded because {reason}. "
            f"The original file was kept as {backup} and default commands were restored.",
        )

    def _backup_path(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = self.path.with_name(f"{self.path.stem}.broken-{stamp}{self.path.suffix}")
        counter = 1
        while candidate.exists():
            candidate = self.path.with_name(f"{self.path.stem}.broken-{stamp}-{counter}{self.path.suffix}")
            counter += 1
        return candidate


def parse_commands(text: str) -> list[Command]:
    """Parse the JSON file content. Raises ValueError if the data is invalid."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg} at line {error.lineno}") from None
    if not isinstance(data, dict) or not isinstance(data.get("commands"), list):
        raise ValueError("expected an object with a 'commands' list")

    commands = [Command.from_dict(entry) for entry in data["commands"]]
    ids = [command.id for command in commands]
    if len(ids) != len(set(ids)):
        raise ValueError("command ids must be unique")
    return commands
