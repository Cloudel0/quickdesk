import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quickdesk.commands import (
    Command,
    CommandLibrary,
    CommandType,
    LaunchError,
    ProtectedCommandError,
    ValidationError,
    builtin_commands,
    launch,
    merge_builtins,
    resolve_executable,
    validate_url,
)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.dir = Path(temp_dir.name)


class UrlValidationTests(unittest.TestCase):
    def test_accepts_http_and_https(self):
        for url in ("http://example.com", "https://example.com/path?q=1", "HTTPS://Example.com"):
            with self.subTest(url=url):
                self.assertEqual(validate_url(url), url)

    def test_strips_surrounding_spaces(self):
        self.assertEqual(validate_url("  https://example.com  "), "https://example.com")

    def test_rejects_other_or_missing_schemes(self):
        for url in ("example.com", "ftp://example.com", "file:///C:/Windows", "javascript:alert(1)", "www.github.com"):
            with self.subTest(url=url):
                with self.assertRaises(ValidationError):
                    validate_url(url)

    def test_rejects_url_without_host_or_with_spaces(self):
        for url in ("https://", "http:///path", "https://exa mple.com"):
            with self.subTest(url=url):
                with self.assertRaises(ValidationError):
                    validate_url(url)


class CreateCommandTests(TempDirTestCase):
    def test_create_url_command(self):
        command = Command.create("  Docs ", " Python docs ", "url", "https://docs.python.org")
        self.assertEqual(command.name, "Docs")
        self.assertEqual(command.description, "Python docs")
        self.assertIs(command.type, CommandType.URL)
        self.assertFalse(command.builtin)
        self.assertTrue(command.id)

    def test_each_command_gets_unique_id(self):
        first = Command.create("A", "", CommandType.URL, "https://a.com")
        second = Command.create("A", "", CommandType.URL, "https://a.com")
        self.assertNotEqual(first.id, second.id)

    def test_create_path_command_for_existing_folder_and_file(self):
        file_path = self.dir / "notes.txt"
        file_path.write_text("hi", encoding="utf-8")
        for target in (self.dir, file_path):
            with self.subTest(target=target):
                command = Command.create("Item", "", CommandType.PATH, str(target))
                self.assertEqual(command.target, str(target))

    def test_rejects_missing_path(self):
        with self.assertRaisesRegex(ValidationError, "does not exist"):
            Command.create("Missing", "", CommandType.PATH, str(self.dir / "nope"))

    def test_rejects_empty_name_and_target(self):
        with self.assertRaisesRegex(ValidationError, "Name"):
            Command.create("   ", "", CommandType.URL, "https://a.com")
        with self.assertRaisesRegex(ValidationError, "must not be empty"):
            Command.create("Name", "", CommandType.URL, "  ")

    def test_rejects_too_long_name(self):
        with self.assertRaises(ValidationError):
            Command.create("x" * 61, "", CommandType.URL, "https://a.com")

    def test_rejects_unknown_type(self):
        with self.assertRaisesRegex(ValidationError, "Unknown command type"):
            Command.create("Name", "", "script", "anything")

    def test_rejects_invalid_url(self):
        with self.assertRaises(ValidationError):
            Command.create("Bad", "", CommandType.URL, "github.com")


class ExecutableTests(TempDirTestCase):
    def test_missing_program_name(self):
        with mock.patch("quickdesk.commands.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValidationError, "not found"):
                resolve_executable("no-such-program.exe")

    def test_missing_full_path(self):
        with self.assertRaisesRegex(ValidationError, "does not exist"):
            resolve_executable(str(self.dir / "missing.exe"))

    def test_folder_is_not_an_application(self):
        with self.assertRaises(ValidationError):
            resolve_executable(str(self.dir) + os.sep)

    @unittest.skipUnless(sys.platform == "win32", "Windows-specific rule")
    def test_scripts_are_rejected_on_windows(self):
        script = self.dir / "run.bat"
        script.write_text("echo hi", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, r"\.exe"):
            resolve_executable(str(script))

    @unittest.skipUnless(sys.platform == "win32", "Windows-specific rule")
    def test_existing_exe_is_accepted(self):
        program = self.dir / "tool.exe"
        program.write_bytes(b"")
        self.assertEqual(resolve_executable(str(program)), str(program))


class EditProtectionTests(unittest.TestCase):
    def test_builtin_command_cannot_be_edited(self):
        builtin = builtin_commands()[0]
        with self.assertRaises(ProtectedCommandError):
            builtin.edited("New", "", CommandType.URL, "https://a.com")

    def test_user_command_can_be_edited(self):
        command = Command.create("Old", "", CommandType.URL, "https://old.com")
        edited = command.edited("New", "desc", CommandType.URL, "https://new.com")
        self.assertEqual((edited.id, edited.name, edited.target), (command.id, "New", "https://new.com"))

    def test_edit_is_validated(self):
        command = Command.create("Old", "", CommandType.URL, "https://old.com")
        with self.assertRaises(ValidationError):
            command.edited("Old", "", CommandType.URL, "not a url")


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.builtin = builtin_commands()[0]
        self.user = Command("u1", "Docs", "", CommandType.URL, "https://docs.python.org")
        self.library = CommandLibrary([self.builtin, self.user])

    def test_add_and_get(self):
        new = Command("u2", "New", "", CommandType.URL, "https://new.com")
        self.library.add(new)
        self.assertEqual(self.library.get("u2"), new)

    def test_add_duplicate_id_fails(self):
        with self.assertRaises(ValueError):
            self.library.add(self.user)

    def test_update_user_command(self):
        updated = self.user.edited("Docs 2", "", CommandType.URL, "https://docs.python.org/3")
        self.library.update(updated)
        self.assertEqual(self.library.get("u1").name, "Docs 2")

    def test_remove_user_command(self):
        self.library.remove("u1")
        self.assertEqual(self.library.commands, (self.builtin,))

    def test_builtin_cannot_be_removed_or_replaced(self):
        with self.assertRaises(ProtectedCommandError):
            self.library.remove(self.builtin.id)
        with self.assertRaises(ProtectedCommandError):
            self.library.update(self.builtin)
        self.assertIn(self.builtin, self.library.commands)

    def test_unknown_id(self):
        with self.assertRaises(KeyError):
            self.library.remove("missing")


class BuiltinTests(unittest.TestCase):
    def test_expected_builtins_exist(self):
        names = {command.name for command in builtin_commands()}
        self.assertEqual(names, {"Notepad", "Calculator", "Paint", "File Explorer", "Downloads", "GitHub", "YouTube"})
        self.assertTrue(all(command.builtin for command in builtin_commands()))

    def test_merge_restores_missing_and_modified_builtins(self):
        builtins = builtin_commands()
        tampered = Command(builtins[0].id, "Hacked", "", CommandType.APP, "cmd.exe", True)
        user = Command("u1", "Docs", "", CommandType.URL, "https://docs.python.org")
        merged = merge_builtins([tampered, user], builtins)
        self.assertEqual(merged, builtins + [user])


class FromDictTests(unittest.TestCase):
    def test_round_trip(self):
        command = Command("id", "Name", "Desc", CommandType.PATH, r"C:\Temp", False)
        self.assertEqual(Command.from_dict(command.to_dict()), command)

    def test_rejects_malformed_entries(self):
        bad_entries = [
            "not an object",
            {"name": "x", "type": "url", "target": "https://a.com"},
            {"id": "1", "name": "x", "type": "unknown", "target": "y"},
            {"id": "1", "name": 5, "type": "url", "target": "https://a.com"},
            {"id": "1", "name": "", "type": "url", "target": "https://a.com"},
            {"id": "1", "name": "x", "type": "url", "target": "https://a.com", "builtin": "yes"},
        ]
        for entry in bad_entries:
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    Command.from_dict(entry)


class LaunchTests(TempDirTestCase):
    """Nothing is really started here: every system call is mocked."""

    def test_url_opens_in_browser(self):
        command = Command("1", "Site", "", CommandType.URL, "https://example.com")
        with mock.patch("quickdesk.commands.webbrowser.open", return_value=True) as open_url:
            launch(command)
        open_url.assert_called_once_with("https://example.com")

    def test_url_without_browser_raises(self):
        command = Command("1", "Site", "", CommandType.URL, "https://example.com")
        with mock.patch("quickdesk.commands.webbrowser.open", return_value=False):
            with self.assertRaises(LaunchError):
                launch(command)

    def test_invalid_url_is_never_opened(self):
        command = Command("1", "Bad", "", CommandType.URL, "file:///C:/Windows/System32")
        with mock.patch("quickdesk.commands.webbrowser.open") as open_url:
            with self.assertRaises(LaunchError):
                launch(command)
        open_url.assert_not_called()

    def test_existing_path_is_opened(self):
        command = Command("1", "Folder", "", CommandType.PATH, str(self.dir))
        with mock.patch("quickdesk.commands._open_path") as open_path:
            launch(command)
        open_path.assert_called_once_with(self.dir)

    def test_missing_path_is_not_opened(self):
        command = Command("1", "Gone", "", CommandType.PATH, str(self.dir / "gone"))
        with mock.patch("quickdesk.commands._open_path") as open_path:
            with self.assertRaisesRegex(LaunchError, "does not exist"):
                launch(command)
        open_path.assert_not_called()

    def test_path_with_environment_variable(self):
        command = Command("1", "Temp", "", CommandType.PATH, "%QD_TEST_DIR%")
        with mock.patch.dict("os.environ", {"QD_TEST_DIR": str(self.dir)}), \
                mock.patch("quickdesk.commands._open_path") as open_path:
            if sys.platform != "win32":
                command = Command("1", "Temp", "", CommandType.PATH, "$QD_TEST_DIR")
            launch(command)
        open_path.assert_called_once_with(self.dir)

    def test_application_started_without_shell(self):
        command = Command("1", "Notepad", "", CommandType.APP, "notepad.exe")
        with mock.patch("quickdesk.commands.resolve_executable", return_value=r"C:\Windows\notepad.exe"), \
                mock.patch("quickdesk.commands.subprocess.Popen") as popen:
            launch(command)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [r"C:\Windows\notepad.exe"])
        self.assertNotIn("shell", kwargs)

    def test_application_os_error_becomes_launch_error(self):
        command = Command("1", "Broken", "", CommandType.APP, "broken.exe")
        with mock.patch("quickdesk.commands.resolve_executable", return_value="broken.exe"), \
                mock.patch("quickdesk.commands.subprocess.Popen", side_effect=OSError(2, "No such file")):
            with self.assertRaisesRegex(LaunchError, "Could not open 'Broken'"):
                launch(command)

    def test_missing_application_is_reported(self):
        command = Command("1", "Ghost", "", CommandType.APP, "ghost.exe")
        with mock.patch("quickdesk.commands.shutil.which", return_value=None), \
                mock.patch("quickdesk.commands.subprocess.Popen") as popen:
            with self.assertRaisesRegex(LaunchError, "not found"):
                launch(command)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
