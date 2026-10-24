# QuickDesk

QuickDesk is a small desktop launcher for Windows. Type a few letters into one search box and open
an application, a folder, a file or a website without hunting through the Start menu or bookmarks.

It is a learning and portfolio project: the code is kept small, readable and covered by tests.

![QuickDesk main window](docs/screenshot.png)

## Features

- **Instant search** that updates as you type:
  - case-insensitive;
  - matches the name, the description and the category (for example `website` or `folder`);
  - partial matches (`calc` finds *Calculator*, `hub` finds *GitHub*);
  - tolerates simple typos (`notpad`, `calcualtor`);
  - the best matches are shown first;
  - a clear message when nothing is found.
- **Built-in commands** on first start: Notepad, Calculator, Paint, File Explorer, the Downloads folder,
  GitHub and YouTube. They are protected and cannot be edited or deleted.
- **Your own commands**: add, edit and delete commands of three types: application (`.exe`),
  file or folder, and website.
- **Input validation**: websites must use `http://` or `https://`; files, folders and programs must exist.
- **Saved between runs** in `%APPDATA%\QuickDesk\commands.json`.
- **Global hotkey** `Ctrl+Alt+Space` (configurable): brings QuickDesk to the front from any program
  with the cursor in the search box; pressing it again while QuickDesk is active minimizes it.
  After a command is opened, QuickDesk minimizes and keeps running in the background.
- **Keyboard control**:

  | Key              | Action                                                        |
  |------------------|---------------------------------------------------------------|
  | `Ctrl+Alt+Space` | Show QuickDesk from anywhere / minimize it (Windows only)     |
  | `Ctrl+K`         | Focus the search box                                          |
  | `Up` / `Down`    | Move between results                                          |
  | `Enter`          | Open the selected result                                      |
  | `Escape`         | Clear the search; if it is empty, minimize QuickDesk; in a dialog, close it |

  To quit QuickDesk completely, close the window with the **X** button (or close it from the taskbar).

- Dark, compact interface with small success and error messages at the bottom of the window.

## Technologies

- Python 3.11+
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) for the interface
- Python standard library only for everything else (`json`, `subprocess`, `webbrowser`, `difflib`, `pathlib`, ...)
- `unittest` and `unittest.mock` for tests

No network services, databases or AI APIs are used. Everything runs locally.

## Project structure

```
quickdesk/
├── main.py              # entry point: python main.py
├── requirements.txt
├── README.md
├── docs/
│   └── screenshot.png
├── quickdesk/
│   ├── __init__.py
│   ├── app.py           # interface: main window, command manager, add/edit dialog
│   ├── commands.py      # command model, validation, opening commands, built-ins
│   ├── hotkey.py        # global hotkey (Windows RegisterHotKey via ctypes)
│   ├── search.py        # search and ranking
│   └── storage.py       # reading and writing commands.json
└── tests/
    ├── test_commands.py
    ├── test_hotkey.py
    ├── test_search.py
    └── test_storage.py
```

## Installation and running (Windows)

1. Install [Python 3.11 or newer](https://www.python.org/downloads/) (tick *Add Python to PATH*).
2. Clone the repository and open the folder:

   ```powershell
   git clone https://github.com/Cloudel0/quickdesk.git
   cd quickdesk
   ```

3. Create a virtual environment and install the dependency:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. Start the app:

   ```powershell
   python main.py
   ```

## Running the tests

```powershell
python -m unittest discover -s tests
```

The tests do not start programs, open websites or touch your real settings: system calls are mocked
and files are written to temporary folders. The tests do not need CustomTkinter. On Windows, two tests
register an unused combination (`Ctrl+Alt+Shift+F24`) for a moment to check the real hotkey API;
no keys are pressed.

## Changing the global hotkey

On first start QuickDesk creates `%APPDATA%\QuickDesk\settings.json`:

```json
{
  "hotkey": "Ctrl+Alt+Space"
}
```

Change the value and restart QuickDesk. Use one or more of `Ctrl`, `Alt`, `Shift`, `Win` plus a key:
a letter, a digit, `F1`–`F24`, `Space`, `Enter`, `Tab`, `Home`, `End`, `Insert` or `Delete`
(for example `Ctrl+Alt+Q` or `Ctrl+Shift+F2`).

If the combination is already taken by another program (or QuickDesk is already running), Windows
refuses it. QuickDesk then shows a message, keeps working without the hotkey and can be opened from the
taskbar.

## Example: adding your own command

1. Click **Manage commands**, then **Add command**.
2. Fill in the form, for example:

   | Field       | Value                          |
   |-------------|--------------------------------|
   | Name        | `Python docs`                  |
   | Description | `Official documentation`       |
   | Type        | `Website`                      |
   | Path or URL | `https://docs.python.org/3/`   |

3. Click **Save** (or press `Enter`). Now type `python` in the search box and press `Enter`.

Other examples:

- **Application**: `Code.exe` from `C:\Users\you\AppData\Local\Programs\Microsoft VS Code\Code.exe`
  (use the **File…** button), or just `notepad.exe` if the program is on `PATH`.
- **File or folder**: `C:\Users\you\Documents\Study` (use the **Folder…** button).
  Environment variables such as `%USERPROFILE%\Documents` also work.

The commands file is plain JSON, for example:

```json
{
  "version": 1,
  "commands": [
    {
      "id": "3f2c9a0e8b1d4b6f9c7a5e2d1b0a9f8e",
      "name": "Python docs",
      "description": "Official documentation",
      "type": "url",
      "target": "https://docs.python.org/3/",
      "builtin": false
    }
  ]
}
```

## Design decisions

- **Small modules with one job each.** `search.py`, `storage.py` and `commands.py` do not depend on
  the interface, so they are easy to test. `app.py` only connects them to widgets.
- **Safe launching.** No `eval`, `exec` or `shell=True`. Applications are started with
  `subprocess.Popen([path_to_exe])` and only `.exe` files are accepted, so a command cannot run `.bat`
  scripts or pass arguments to a terminal. Files and folders are opened with `os.startfile`, websites
  with `webbrowser.open`. Paths are checked right before opening.
- **Simple, explainable ranking.** Every query word must match. Exact word > word prefix > substring >
  close spelling (`difflib.SequenceMatcher`, only for words of 4+ letters). Matches in the name count
  more than matches in the description or category. See the docstring at the top of `search.py`.
- **User data outside the source folder.** Commands are stored in `%APPDATA%\QuickDesk\commands.json`.
  The global hotkey is stored separately in `settings.json`. The commands file is written atomically (temporary file + replace), so a crash while saving cannot leave half
  a file. You can set the `QUICKDESK_HOME` environment variable to use another folder, which is handy
  for trying the app without touching your real data.
- **Damaged settings are never lost silently.** If `commands.json` is not valid, it is renamed to
  `commands.broken-<date>.json`, the defaults are restored and a message tells you where the old file is.
  If the backup cannot be made, QuickDesk starts with the defaults but refuses to save over the file.
- **Built-ins come from code.** Built-in commands are stored in the file too, but on every start they
  are refreshed from the code. This keeps them correct (for example, the real Downloads location is
  read from Windows, even if you moved the folder) and protects them from accidental changes.
- **Deleting a command only removes the entry** from `commands.json`. QuickDesk never deletes files.
- **One registered hotkey instead of a keyboard hook.** `RegisterHotKey` asks Windows to report one
  combination; QuickDesk never sees other keys and does not poll the keyboard. Windows delivers the
  event to the thread that registered it, so a small background thread waits in `GetMessageW` and
  hands each press to Tkinter with `event_generate` (tkinter forwards it to the main thread). The
  window is only changed from Tkinter's own event loop. On exit the thread receives `WM_QUIT` and
  calls `UnregisterHotKey`.
- **Minimize instead of hiding.** QuickDesk minimizes rather than disappearing completely, so it is
  always visible in the taskbar and can be closed normally even without a tray icon.

## Limitations of version 0.1

- Windows is the main target. The core modules and tests also run on Linux/macOS, but the built-in
  commands are Windows programs and the interface was checked only on Windows.
- The global hotkey works only on Windows and only while QuickDesk is running; it is changed in
  `settings.json`, not in the interface. There is no tray icon and no autostart with Windows.
- Commands cannot pass arguments to programs (this is intentional for safety).
- Application commands must be `.exe` files; to open a shortcut (`.lnk`) add it as *File or folder*.
- The interface is in English only.

## Ideas for the future

- A system tray icon and an option to start with Windows.
- Choosing the hotkey in a settings window.
- Optional hotkeys for individual commands.
- Show recently or frequently used commands first.
- Icons for results (extracted from programs and websites).
- Import commands from Start menu shortcuts.
- Optional program arguments with a safe, explicit list of allowed values.
- Light theme and a settings window.
- Packaging into a single `.exe` with PyInstaller.
