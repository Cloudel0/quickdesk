import sys
import unittest
from unittest import mock

from quickdesk.hotkey import (
    DEFAULT_HOTKEY,
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    GlobalHotkey,
    HotkeyError,
    parse_hotkey,
)

# An unusual combination, so the test does not clash with real shortcuts
# (including QuickDesk's own Ctrl+Alt+Q if it is running).
TEST_HOTKEY = "Ctrl+Alt+Shift+F24"


class ParseHotkeyTests(unittest.TestCase):
    def test_default_hotkey(self):
        self.assertEqual(parse_hotkey(DEFAULT_HOTKEY), (MOD_CONTROL | MOD_ALT, ord("Q")))

    def test_is_case_and_space_insensitive(self):
        self.assertEqual(parse_hotkey(" ctrl + ALT + space "), (MOD_CONTROL | MOD_ALT, 0x20))

    def test_letters_digits_and_function_keys(self):
        self.assertEqual(parse_hotkey("Win+Q"), (MOD_WIN, ord("Q")))
        self.assertEqual(parse_hotkey("Ctrl+Shift+1"), (MOD_CONTROL | MOD_SHIFT, ord("1")))
        self.assertEqual(parse_hotkey("Alt+F1"), (MOD_ALT, 0x70))
        self.assertEqual(parse_hotkey("Alt+F24"), (MOD_ALT, 0x87))

    def test_control_is_an_alias_of_ctrl(self):
        self.assertEqual(parse_hotkey("Control+K"), parse_hotkey("Ctrl+K"))

    def test_rejects_invalid_hotkeys(self):
        for text in ("", "Space", "Ctrl+", "Ctrl++A", "Hyper+A", "Ctrl+Banana", "Ctrl+F25", "Ctrl+Ж"):
            with self.subTest(text=text):
                with self.assertRaises(HotkeyError):
                    parse_hotkey(text)


class GlobalHotkeyTests(unittest.TestCase):
    def test_invalid_hotkey_fails_early(self):
        with self.assertRaises(HotkeyError):
            GlobalHotkey("A", lambda: None)

    def test_only_windows_is_supported(self):
        hotkey = GlobalHotkey(TEST_HOTKEY, lambda: None)
        with mock.patch("quickdesk.hotkey.sys.platform", "linux"):
            with self.assertRaisesRegex(HotkeyError, "only available on Windows"):
                hotkey.start()
        self.assertFalse(hotkey.active)

    def test_stop_without_start_does_nothing(self):
        GlobalHotkey(TEST_HOTKEY, lambda: None).stop()


@unittest.skipUnless(sys.platform == "win32", "uses the Windows API")
class WindowsRegistrationTests(unittest.TestCase):
    """Registers a real (unusual) hotkey for a moment; no keys are pressed."""

    def test_register_and_release(self):
        hotkey = GlobalHotkey(TEST_HOTKEY, lambda: None)
        hotkey.start()
        try:
            self.assertTrue(hotkey.active)
        finally:
            hotkey.stop()
        self.assertFalse(hotkey.active)

        # After release the same combination can be registered again.
        again = GlobalHotkey(TEST_HOTKEY, lambda: None)
        again.start()
        again.stop()

    def test_busy_hotkey_gives_clear_error(self):
        first = GlobalHotkey(TEST_HOTKEY, lambda: None)
        first.start()
        try:
            second = GlobalHotkey(TEST_HOTKEY, lambda: None)
            with self.assertRaisesRegex(HotkeyError, "already used by another program"):
                second.start()
            self.assertFalse(second.active)
        finally:
            first.stop()


if __name__ == "__main__":
    unittest.main()
