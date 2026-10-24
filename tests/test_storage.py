import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quickdesk.commands import Command, CommandType
from quickdesk.storage import (
    CommandStore,
    StorageError,
    default_config_dir,
    load_settings,
    parse_commands,
    visible_path,
)

DEFAULTS = [
    Command("builtin-github", "GitHub", "Code hosting", CommandType.URL, "https://github.com", True),
]
USER_COMMAND = Command("abc123", "Docs", "Python docs", CommandType.URL, "https://docs.python.org")


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.dir = Path(temp_dir.name)
        self.path = self.dir / "QuickDesk" / "commands.json"
        self.store = CommandStore(self.path, DEFAULTS)


class FirstRunTests(StorageTestCase):
    def test_missing_file_creates_defaults(self):
        result = self.store.load()
        self.assertEqual(result.commands, DEFAULTS)
        self.assertIsNone(result.warning)
        self.assertTrue(self.path.exists())
        self.assertEqual(parse_commands(self.path.read_text(encoding="utf-8")), DEFAULTS)

    def test_empty_file_is_treated_as_first_run(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("  \n", encoding="utf-8")
        result = self.store.load()
        self.assertEqual(result.commands, DEFAULTS)
        self.assertIsNone(result.warning)

    def test_existing_file_is_not_overwritten(self):
        self.store.save([USER_COMMAND])
        result = CommandStore(self.path, DEFAULTS).load()
        self.assertEqual(result.commands, [USER_COMMAND])

    def test_empty_command_list_is_valid(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"version": 1, "commands": []}', encoding="utf-8")
        self.assertEqual(self.store.load().commands, [])


class SaveAndLoadTests(StorageTestCase):
    def test_round_trip_keeps_all_fields(self):
        commands = DEFAULTS + [USER_COMMAND]
        self.store.save(commands)
        self.assertEqual(self.store.load().commands, commands)

    def test_non_ascii_text_is_saved_readably(self):
        command = Command("ru", "Блокнот", "Текстовый редактор", CommandType.APP, "notepad.exe")
        self.store.save([command])
        self.assertIn("Блокнот", self.path.read_text(encoding="utf-8"))
        self.assertEqual(self.store.load().commands, [command])

    def test_save_leaves_no_temporary_file(self):
        self.store.save(DEFAULTS)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["commands.json"])

    def test_save_error_is_reported(self):
        with mock.patch("quickdesk.storage.os.replace", side_effect=PermissionError("denied")):
            with self.assertRaises(StorageError):
                self.store.save(DEFAULTS)


class DamagedFileTests(StorageTestCase):
    def write(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")

    def backups(self):
        return [p for p in self.path.parent.iterdir() if ".broken-" in p.name]

    def assert_recovered(self, original_text):
        result = self.store.load()
        self.assertEqual(result.commands, DEFAULTS)
        self.assertIsNotNone(result.warning)
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), original_text)
        self.assertIn(str(backups[0]), result.warning)
        # A working file with defaults is written in place of the damaged one.
        self.assertEqual(parse_commands(self.path.read_text(encoding="utf-8")), DEFAULTS)

    def test_invalid_json_is_backed_up_and_defaults_restored(self):
        self.write("{not json")
        self.assert_recovered("{not json")

    def test_wrong_structure_is_backed_up(self):
        self.write('["just", "a", "list"]')
        self.assert_recovered('["just", "a", "list"]')

    def test_invalid_command_entry_is_backed_up(self):
        text = json.dumps({"commands": [{"id": "x", "name": "X", "type": "rocket", "target": "y"}]})
        self.write(text)
        self.assert_recovered(text)

    def test_duplicate_ids_are_rejected(self):
        entry = USER_COMMAND.to_dict()
        text = json.dumps({"commands": [entry, entry]})
        self.write(text)
        self.assert_recovered(text)

    def test_two_recoveries_keep_both_backups(self):
        self.write("broken 1")
        self.store.load()
        self.write("broken 2")
        with mock.patch("quickdesk.storage.datetime") as fake_datetime:
            # Same timestamp as before is possible; backups must not collide.
            fake_datetime.now.return_value.strftime.return_value = self.backups()[0].stem.split(".broken-")[1]
            self.store.load()
        contents = sorted(p.read_text(encoding="utf-8") for p in self.backups())
        self.assertEqual(contents, ["broken 1", "broken 2"])

    def test_file_is_not_overwritten_when_backup_fails(self):
        self.write("{damaged")
        with mock.patch("quickdesk.storage.os.replace", side_effect=PermissionError("locked")):
            result = self.store.load()
        self.assertEqual(result.commands, DEFAULTS)
        self.assertIn("could not be backed up", result.warning)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{damaged")
        with self.assertRaises(StorageError):
            self.store.save(DEFAULTS)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{damaged")


class SettingsTests(StorageTestCase):
    DEFAULTS = {"hotkey": "Ctrl+Alt+Space"}

    def setUp(self):
        super().setUp()
        self.settings_path = self.dir / "QuickDesk" / "settings.json"

    def test_missing_file_writes_defaults(self):
        settings, warning = load_settings(self.settings_path, self.DEFAULTS)
        self.assertEqual(settings, self.DEFAULTS)
        self.assertIsNone(warning)
        self.assertEqual(json.loads(self.settings_path.read_text(encoding="utf-8")), self.DEFAULTS)

    def test_user_value_is_used(self):
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text('{"hotkey": "Ctrl+Alt+Q", "other": 1}', encoding="utf-8")
        settings, warning = load_settings(self.settings_path, self.DEFAULTS)
        self.assertEqual(settings, {"hotkey": "Ctrl+Alt+Q"})
        self.assertIsNone(warning)

    def test_broken_file_is_not_changed(self):
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text("{oops", encoding="utf-8")
        settings, warning = load_settings(self.settings_path, self.DEFAULTS)
        self.assertEqual(settings, self.DEFAULTS)
        self.assertIn("not valid JSON", warning)
        self.assertEqual(self.settings_path.read_text(encoding="utf-8"), "{oops")

    def test_wrong_value_type_falls_back_to_default(self):
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text('{"hotkey": 42}', encoding="utf-8")
        settings, warning = load_settings(self.settings_path, self.DEFAULTS)
        self.assertEqual(settings, self.DEFAULTS)
        self.assertIn("hotkey", warning)


class VisiblePathTests(StorageTestCase):
    """Microsoft Store Python: files created in %APPDATA% really live in the package folder."""

    def setUp(self):
        super().setUp()
        self.appdata = self.dir / "Roaming"
        self.local = self.dir / "Local"
        env = mock.patch.dict("os.environ", {"APPDATA": str(self.appdata), "LOCALAPPDATA": str(self.local)})
        env.start()
        self.addCleanup(env.stop)
        self.file = self.appdata / "QuickDesk" / "settings.json"
        self.redirected = self.local / "Packages" / "Python.Test" / "LocalCache" / "Roaming" / "QuickDesk" / "settings.json"

    def test_packaged_python_shows_redirected_location(self):
        self.redirected.parent.mkdir(parents=True)
        self.redirected.write_text("{}", encoding="utf-8")
        with mock.patch("quickdesk.storage._package_family_name", return_value="Python.Test"):
            self.assertEqual(visible_path(self.file), self.redirected)

    def test_normal_python_keeps_path(self):
        with mock.patch("quickdesk.storage._package_family_name", return_value=None):
            self.assertEqual(visible_path(self.file), self.file)

    def test_path_outside_appdata_is_unchanged(self):
        other = self.dir / "elsewhere.json"
        with mock.patch("quickdesk.storage._package_family_name", return_value="Python.Test"):
            self.assertEqual(visible_path(other), other)


class ConfigDirTests(unittest.TestCase):
    def test_uses_appdata(self):
        with mock.patch.dict("os.environ", {"APPDATA": r"C:\Users\me\AppData\Roaming"}, clear=True):
            self.assertEqual(default_config_dir(), Path(r"C:\Users\me\AppData\Roaming") / "QuickDesk")

    def test_override_with_environment_variable(self):
        with mock.patch.dict("os.environ", {"APPDATA": "x", "QUICKDESK_HOME": "custom"}, clear=True):
            self.assertEqual(default_config_dir(), Path("custom"))


if __name__ == "__main__":
    unittest.main()
