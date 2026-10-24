"""Graphical interface of QuickDesk (CustomTkinter)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from .commands import (
    Command,
    CommandLibrary,
    CommandType,
    LaunchError,
    ValidationError,
    builtin_commands,
    launch,
    merge_builtins,
)
from .hotkey import DEFAULT_HOTKEY, GlobalHotkey, HotkeyError, foreground_window_is_ours
from .search import search
from .storage import CommandStore, StorageError, default_config_dir, load_settings, visible_path

DEFAULT_SETTINGS = {"hotkey": DEFAULT_HOTKEY}

# --- Style ------------------------------------------------------------------

BG = "#16181d"
SURFACE = "#1f2229"
SELECTED = "#2b4778"
BORDER = "#2c313a"
TEXT = "#e6e8eb"
MUTED = "#9aa0aa"
ACCENT = "#3b82f6"
ACCENT_HOVER = "#2f6fd6"
DANGER = "#b4423f"
DANGER_HOVER = "#963532"
SUCCESS = "#4ade80"
ERROR = "#f87171"

PAD = 16
GAP = 8
RADIUS = 8
MAX_RESULTS = 50
NOTIFICATION_MS = 4000

# Windows virtual key code of "K". Used so that Ctrl+K also works
# with a non-English keyboard layout (for example Russian).
VK_K = 75

# Virtual event used to pass a hotkey press from the hotkey thread to Tkinter.
HOTKEY_EVENT = "<<QuickDeskHotkey>>"

TYPE_BY_LABEL = {command_type.label: command_type for command_type in CommandType}

TARGET_HINTS = {
    CommandType.APP: "notepad.exe or C:\\Path\\To\\Program.exe",
    CommandType.PATH: "C:\\Users\\you\\Documents",
    CommandType.URL: "https://example.com",
}


class Fonts:
    """Fonts can only be created after the main window exists."""

    def __init__(self) -> None:
        self.title = ctk.CTkFont(size=22, weight="bold")
        self.search = ctk.CTkFont(size=16)
        self.name = ctk.CTkFont(size=14, weight="bold")
        self.body = ctk.CTkFont(size=13)
        self.small = ctk.CTkFont(size=12)


# --- Main window ------------------------------------------------------------


class QuickDeskApp(ctk.CTk):
    def __init__(
        self,
        store: CommandStore,
        library: CommandLibrary,
        startup_warning: str | None = None,
        hotkey: str | None = DEFAULT_HOTKEY,
        settings_path: Path | None = None,
    ) -> None:
        super().__init__(fg_color=BG)
        self.store = store
        self.library = library
        self.fonts = Fonts()
        self.results: list[Command] = []
        self.rows: list[ResultRow] = []
        self.selected = 0
        self._notification_job: str | None = None
        self._last_query = ""
        self._closing = False

        self.title("QuickDesk")
        self.geometry("640x500")
        self.minsize(480, 360)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        # The window close button really quits; hiding is done with Esc or the hotkey.
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

        warnings = [startup_warning] if startup_warning else []
        self.hotkey = self._start_hotkey(hotkey, settings_path, warnings)

        self._build_header()
        self._build_search()
        self._build_results()
        self._build_status_bar()
        self._bind_keys()

        self.refresh_results()
        self.after(100, self.focus_search)
        if warnings:
            self.after(300, lambda: messagebox.showwarning("QuickDesk", "\n\n".join(warnings), parent=self))

    # Layout

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, GAP))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="QuickDesk", font=self.fonts.title, text_color=TEXT).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            header,
            text="Manage commands",
            width=150,
            font=self.fonts.body,
            fg_color=SURFACE,
            hover_color=BORDER,
            border_width=1,
            border_color=BORDER,
            corner_radius=RADIUS,
            command=self.open_manager,
        ).grid(row=0, column=1, sticky="e")

    def _build_search(self) -> None:
        # A textvariable would disable the placeholder in CustomTkinter,
        # so changes are detected on key release instead.
        self.search_entry = ctk.CTkEntry(
            self,
            placeholder_text="Search apps, folders and websites  (Ctrl+K)",
            height=44,
            font=self.fonts.search,
            fg_color=SURFACE,
            border_color=BORDER,
            corner_radius=RADIUS,
        )
        self.search_entry.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(0, GAP))
        self.search_entry.bind("<KeyRelease>", lambda _event: self._on_query_change())
        self.search_entry.bind("<<Paste>>", lambda _event: self.after_idle(self._on_query_change), add="+")
        self.search_entry.bind("<<Cut>>", lambda _event: self.after_idle(self._on_query_change), add="+")

    def _build_results(self) -> None:
        self.results_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.results_frame.grid(row=2, column=0, sticky="nsew", padx=(PAD, PAD - 6), pady=0)
        self.results_frame.grid_columnconfigure(0, weight=1)
        self.empty_label = ctk.CTkLabel(self.results_frame, text="", font=self.fonts.body, text_color=MUTED)

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=PAD, pady=(GAP, PAD - 4))
        bar.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(bar, text="", font=self.fonts.small, text_color=MUTED, anchor="w")
        self.status_label.grid(row=0, column=0, sticky="w")
        hint = "↑↓ select   Enter open   Esc clear"
        if self.hotkey:
            hint = f"{self.hotkey.hotkey} show/hide   " + hint.replace("Esc clear", "Esc clear/hide")
        ctk.CTkLabel(bar, text=hint, font=self.fonts.small, text_color=MUTED).grid(row=0, column=1, sticky="e")

    def _bind_keys(self) -> None:
        # These bindings belong to the main window only; dialogs have their own.
        self.bind("<Control-KeyPress>", self._on_control_key)
        self.bind("<Return>", lambda _event: self.open_selected())
        self.bind("<KP_Enter>", lambda _event: self.open_selected())
        self.bind("<Up>", lambda _event: self.move_selection(-1))
        self.bind("<Down>", lambda _event: self.move_selection(1))
        self.bind("<Escape>", lambda _event: self.on_escape())
        self.bind(HOTKEY_EVENT, lambda _event: self.toggle_window())

    # Global hotkey and window visibility

    def _start_hotkey(
        self, hotkey: str | None, settings_path: Path | None, warnings: list[str]
    ) -> GlobalHotkey | None:
        if not hotkey:
            return None
        try:
            global_hotkey = GlobalHotkey(hotkey, self._on_hotkey_pressed)
            global_hotkey.start()
        except HotkeyError as error:
            message = f"{error}\n\nQuickDesk works without it; open it from the taskbar."
            if settings_path:
                message += (
                    f'\nTo use another combination, change "hotkey" in {visible_path(settings_path)} '
                    f"and restart QuickDesk."
                )
            warnings.append(message)
            return None
        return global_hotkey

    def _on_hotkey_pressed(self) -> None:
        """Called in the hotkey thread. Only hands the event over to Tkinter."""
        if self._closing:
            return
        try:
            # tkinter forwards calls from other threads to the main loop thread.
            self.event_generate(HOTKEY_EVENT, when="tail")
        except (RuntimeError, tk.TclError):
            pass  # the window is being closed

    def toggle_window(self) -> None:
        if self.is_active():
            self.hide_window()
        else:
            self.show_window()

    def is_active(self) -> bool:
        """True if the window is visible and QuickDesk is the active program."""
        if self.state() != "normal":
            return False
        ours = foreground_window_is_ours()
        if ours is not None:
            return ours
        try:
            return self.focus_get() is not None
        except (KeyError, tk.TclError):
            return False

    def show_window(self) -> None:
        self.deiconify()
        self.lift()
        # Being "topmost" for a moment brings the window in front of all others.
        self.attributes("-topmost", True)
        self.focus_force()
        self.focus_search()
        self.after(150, lambda: self.attributes("-topmost", False))

    def hide_window(self) -> None:
        self.iconify()

    def quit_app(self) -> None:
        self._closing = True
        if self.hotkey:
            self.hotkey.stop()
        self.destroy()

    # Search and results

    @property
    def query(self) -> str:
        return self.search_entry.get()

    def _on_query_change(self) -> None:
        if self.query != self._last_query:
            self.refresh_results()

    def refresh_results(self) -> None:
        self._last_query = self.query
        self.results = search(self.query, self.library.commands)[:MAX_RESULTS]
        self.selected = 0
        self._render_results()

    def _render_results(self) -> None:
        for row in self.rows:
            row.destroy()
        self.rows = []
        self.empty_label.grid_forget()

        if not self.results:
            query = self.query.strip()
            text = f"Nothing found for “{query}”." if query else "No commands yet. Add one in Manage commands."
            self.empty_label.configure(text=text)
            self.empty_label.grid(row=0, column=0, pady=40)
            return

        for index, command in enumerate(self.results):
            row = ResultRow(self.results_frame, command, self.fonts)
            row.grid(row=index, column=0, sticky="ew", pady=(0, 6), padx=(0, 6))
            row.bind_all_children("<Button-1>", lambda _event, i=index: self.select(i))
            row.bind_all_children("<Double-Button-1>", lambda _event, i=index: self.open_selected())
            self.rows.append(row)
        self.select(0)
        self.results_frame._parent_canvas.yview_moveto(0)

    def select(self, index: int) -> None:
        if not self.rows:
            return
        self.rows[self.selected].set_selected(False)
        self.selected = max(0, min(index, len(self.rows) - 1))
        self.rows[self.selected].set_selected(True)
        self._scroll_into_view(self.rows[self.selected])

    def move_selection(self, delta: int) -> str:
        self.select(self.selected + delta)
        return "break"  # keep the cursor in the search field where it is

    def _scroll_into_view(self, row: ctk.CTkFrame) -> None:
        canvas = self.results_frame._parent_canvas
        self.update_idletasks()
        content_height = self.results_frame.winfo_height()
        visible_height = canvas.winfo_height()
        if content_height <= visible_height:
            return
        view_top = canvas.yview()[0] * content_height
        row_top = row.winfo_y()
        row_bottom = row_top + row.winfo_height()
        if row_top < view_top:
            canvas.yview_moveto(row_top / content_height)
        elif row_bottom > view_top + visible_height:
            canvas.yview_moveto((row_bottom - visible_height + 6) / content_height)

    def open_selected(self) -> None:
        if self.results:
            self.open_command(self.results[self.selected])

    def open_command(self, command: Command) -> None:
        try:
            launch(command)
        except LaunchError as error:
            self.notify(str(error), error=True)
        else:
            self.notify(f"Opened {command.name}")
            if self.hotkey:
                # Get out of the way; the hotkey brings QuickDesk back.
                self.hide_window()

    # Keyboard helpers

    def _on_control_key(self, event) -> str | None:
        if event.keycode == VK_K or event.keysym.lower() == "k":
            self.focus_search()
            return "break"
        return None

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def on_escape(self) -> None:
        if self.query or not self.hotkey:
            self.clear_search()
        else:
            self.hide_window()

    def clear_search(self) -> None:
        self.search_entry.delete(0, "end")
        self.refresh_results()
        self.focus_search()

    # Notifications

    def notify(self, text: str, error: bool = False) -> None:
        self.status_label.configure(text=text, text_color=ERROR if error else SUCCESS)
        if self._notification_job:
            self.after_cancel(self._notification_job)
        self._notification_job = self.after(NOTIFICATION_MS, lambda: self.status_label.configure(text=""))

    # Managing commands

    def open_manager(self) -> None:
        CommandManager(self)

    def add_command(self, command: Command) -> bool:
        return self._apply_change(lambda library: library.add(command), f"Added {command.name}")

    def update_command(self, command: Command) -> bool:
        return self._apply_change(lambda library: library.update(command), f"Saved {command.name}")

    def remove_command(self, command: Command) -> bool:
        return self._apply_change(lambda library: library.remove(command.id), f"Removed {command.name}")

    def _apply_change(self, change: Callable[[CommandLibrary], None], success_text: str) -> bool:
        """Change a copy of the library and keep it only if it was saved to disk."""
        updated = CommandLibrary(self.library.commands)
        change(updated)
        try:
            self.store.save(updated.commands)
        except StorageError as error:
            self.notify(str(error), error=True)
            return False
        self.library = updated
        self.refresh_results()
        self.notify(success_text)
        return True


class ResultRow(ctk.CTkFrame):
    """One search result: name, description and type."""

    def __init__(self, master, command: Command, fonts: Fonts) -> None:
        super().__init__(master, fg_color=SURFACE, corner_radius=RADIUS, border_width=1, border_color=BORDER)
        self.grid_columnconfigure(0, weight=1)
        name = ctk.CTkLabel(self, text=command.name, font=fonts.name, text_color=TEXT, anchor="w")
        name.grid(row=0, column=0, sticky="ew", padx=(12, GAP), pady=(8, 0))
        description = ctk.CTkLabel(
            self, text=command.description or command.target, font=fonts.small, text_color=MUTED, anchor="w"
        )
        description.grid(row=1, column=0, sticky="ew", padx=(12, GAP), pady=(0, 8))
        badge = ctk.CTkLabel(
            self, text=command.type.label, font=fonts.small, text_color=MUTED, fg_color=BG, corner_radius=6
        )
        badge.grid(row=0, column=1, rowspan=2, padx=12, ipadx=6)
        self.configure(cursor="hand2")

    def bind_all_children(self, sequence: str, callback: Callable) -> None:
        self.bind(sequence, callback)
        for child in self.winfo_children():
            child.bind(sequence, callback)

    def set_selected(self, selected: bool) -> None:
        self.configure(fg_color=SELECTED if selected else SURFACE, border_color=ACCENT if selected else BORDER)


# --- Dialogs ----------------------------------------------------------------


class ModalWindow(ctk.CTkToplevel):
    """Base for dialogs: modal, closes on Escape, appears above its parent."""

    def __init__(self, master, title: str, size: str) -> None:
        super().__init__(master, fg_color=BG)
        self.title(title)
        self.geometry(size)
        self.transient(master)
        self.bind("<Escape>", lambda _event: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        # CustomTkinter windows on Windows need a short delay before they can
        # take focus and grab input.
        self.after(150, self._activate)

    def _activate(self) -> None:
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except Exception:  # the window may not be visible yet; it still works without a grab
            pass

    def close(self) -> None:
        self.grab_release()
        parent = self.master
        self.destroy()
        if isinstance(parent, ModalWindow):
            parent._activate()


class CommandManager(ModalWindow):
    """Lists all commands; user commands can be edited and deleted."""

    def __init__(self, app: QuickDeskApp) -> None:
        super().__init__(app, "Manage commands", "560x480")
        self.app = app
        fonts = app.fonts
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, GAP))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Commands", font=fonts.name, text_color=TEXT).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            top, text="Add command", width=130, font=fonts.body, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            corner_radius=RADIUS, command=self.add,
        ).grid(row=0, column=1, sticky="e")

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=(PAD, PAD - 6), pady=(0, PAD))
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.render()

    def render(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        fonts = self.app.fonts
        for index, command in enumerate(self.app.library.commands):
            row = ctk.CTkFrame(self.list_frame, fg_color=SURFACE, corner_radius=RADIUS, border_width=1, border_color=BORDER)
            row.grid(row=index, column=0, sticky="ew", pady=(0, 6), padx=(0, 6))
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=command.name, font=fonts.name, text_color=TEXT, anchor="w").grid(
                row=0, column=0, sticky="ew", padx=12, pady=(8, 0)
            )
            ctk.CTkLabel(row, text=command.type.label, font=fonts.small, text_color=MUTED, anchor="w").grid(
                row=1, column=0, sticky="ew", padx=12, pady=(0, 8)
            )
            if command.builtin:
                ctk.CTkLabel(row, text="Built-in", font=fonts.small, text_color=MUTED).grid(
                    row=0, column=1, rowspan=2, padx=12
                )
                continue
            buttons = ctk.CTkFrame(row, fg_color="transparent")
            buttons.grid(row=0, column=1, rowspan=2, padx=12)
            ctk.CTkButton(
                buttons, text="Edit", width=64, font=fonts.small, fg_color=BORDER, hover_color=SELECTED,
                corner_radius=6, command=lambda c=command: self.edit(c),
            ).grid(row=0, column=0, padx=(0, 6))
            ctk.CTkButton(
                buttons, text="Delete", width=64, font=fonts.small, fg_color=DANGER, hover_color=DANGER_HOVER,
                corner_radius=6, command=lambda c=command: self.delete(c),
            ).grid(row=0, column=1)

    def add(self) -> None:
        CommandDialog(self, "Add command", None, self._submit_new)

    def edit(self, command: Command) -> None:
        CommandDialog(self, "Edit command", command, self._submit_edit)

    def delete(self, command: Command) -> None:
        question = f"Remove the command “{command.name}” from QuickDesk?\n\nThe file, folder or program itself is not deleted."
        if messagebox.askyesno("Remove command", question, parent=self):
            self.app.remove_command(command)
            self.render()
        self._activate()

    def _submit_new(self, command: Command) -> bool:
        saved = self.app.add_command(command)
        self.render()
        return saved

    def _submit_edit(self, command: Command) -> bool:
        saved = self.app.update_command(command)
        self.render()
        return saved


class CommandDialog(ModalWindow):
    """Form for creating or editing a user command."""

    def __init__(
        self, master: ModalWindow, title: str, command: Command | None, on_submit: Callable[[Command], bool]
    ) -> None:
        super().__init__(master, title, "500x420")
        self.resizable(False, False)
        self.command = command
        self.on_submit = on_submit
        fonts = master.app.fonts
        self.grid_columnconfigure(0, weight=1)

        self.name_entry = self._add_field(0, "Name", fonts)
        self.description_entry = self._add_field(2, "Description (optional)", fonts)

        ctk.CTkLabel(self, text="Type", font=fonts.body, text_color=MUTED).grid(
            row=4, column=0, sticky="w", padx=PAD, pady=(GAP, 2)
        )
        self.type_selector = ctk.CTkSegmentedButton(
            self,
            values=list(TYPE_BY_LABEL),
            font=fonts.body,
            fg_color=SURFACE,
            unselected_color=SURFACE,
            unselected_hover_color=BORDER,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            command=lambda _value: self._on_type_change(),
        )
        self.type_selector.grid(row=5, column=0, sticky="ew", padx=PAD)

        ctk.CTkLabel(self, text="Path or URL", font=fonts.body, text_color=MUTED).grid(
            row=6, column=0, sticky="w", padx=PAD, pady=(GAP, 2)
        )
        target_row = ctk.CTkFrame(self, fg_color="transparent")
        target_row.grid(row=7, column=0, sticky="ew", padx=PAD)
        target_row.grid_columnconfigure(0, weight=1)
        self.target_entry = ctk.CTkEntry(target_row, font=fonts.body, fg_color=SURFACE, border_color=BORDER)
        self.target_entry.grid(row=0, column=0, sticky="ew")
        self.file_button = ctk.CTkButton(
            target_row, text="File…", width=64, font=fonts.small, fg_color=BORDER, hover_color=SELECTED,
            command=self._browse_file,
        )
        self.file_button.grid(row=0, column=1, padx=(6, 0))
        self.folder_button = ctk.CTkButton(
            target_row, text="Folder…", width=70, font=fonts.small, fg_color=BORDER, hover_color=SELECTED,
            command=self._browse_folder,
        )
        self.folder_button.grid(row=0, column=2, padx=(6, 0))

        self.error_label = ctk.CTkLabel(self, text="", font=fonts.small, text_color=ERROR, wraplength=460, justify="left")
        self.error_label.grid(row=8, column=0, sticky="w", padx=PAD, pady=(GAP, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=9, column=0, sticky="e", padx=PAD, pady=PAD)
        ctk.CTkButton(
            buttons, text="Cancel", width=90, font=fonts.body, fg_color=SURFACE, hover_color=BORDER,
            command=self.close,
        ).grid(row=0, column=0, padx=(0, GAP))
        ctk.CTkButton(
            buttons, text="Save", width=90, font=fonts.body, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self.submit,
        ).grid(row=0, column=1)

        self._fill(command)
        self.bind("<Return>", lambda _event: self.submit())
        self.after(200, self.name_entry.focus_set)

    def _add_field(self, row: int, label: str, fonts: Fonts) -> ctk.CTkEntry:
        ctk.CTkLabel(self, text=label, font=fonts.body, text_color=MUTED).grid(
            row=row, column=0, sticky="w", padx=PAD, pady=(PAD if row == 0 else GAP, 2)
        )
        entry = ctk.CTkEntry(self, font=fonts.body, fg_color=SURFACE, border_color=BORDER)
        entry.grid(row=row + 1, column=0, sticky="ew", padx=PAD)
        return entry

    def _fill(self, command: Command | None) -> None:
        type_ = command.type if command else CommandType.APP
        if command:
            self.name_entry.insert(0, command.name)
            self.description_entry.insert(0, command.description)
            self.target_entry.insert(0, command.target)
        self.type_selector.set(type_.label)
        self._on_type_change()

    @property
    def selected_type(self) -> CommandType:
        return TYPE_BY_LABEL[self.type_selector.get()]

    def _on_type_change(self) -> None:
        type_ = self.selected_type
        self.target_entry.configure(placeholder_text=TARGET_HINTS[type_])
        self.file_button.configure(state="disabled" if type_ is CommandType.URL else "normal")
        self.folder_button.configure(state="normal" if type_ is CommandType.PATH else "disabled")

    def _browse_file(self) -> None:
        if self.selected_type is CommandType.APP:
            path = filedialog.askopenfilename(parent=self, filetypes=[("Programs", "*.exe")])
        else:
            path = filedialog.askopenfilename(parent=self)
        self._set_target(path)

    def _browse_folder(self) -> None:
        self._set_target(filedialog.askdirectory(parent=self))

    def _set_target(self, path: str) -> None:
        if path:
            self.target_entry.delete(0, "end")
            self.target_entry.insert(0, path.replace("/", "\\") if "\\" not in path else path)
        self._activate()

    def submit(self) -> None:
        values = (
            self.name_entry.get(),
            self.description_entry.get(),
            self.selected_type,
            self.target_entry.get(),
        )
        try:
            command = self.command.edited(*values) if self.command else Command.create(*values)
        except ValidationError as error:
            self.error_label.configure(text=str(error))
            return
        if self.on_submit(command):
            self.close()
        else:
            self.error_label.configure(text="The command could not be saved. See the message in the main window.")


# --- Start ------------------------------------------------------------------


def run() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    config_dir = default_config_dir()
    builtins = builtin_commands()
    store = CommandStore(config_dir / "commands.json", builtins)
    warnings = []
    try:
        result = store.load()
        commands = result.commands
        if result.warning:
            warnings.append(result.warning)
    except StorageError as error:
        commands = builtins
        warnings.append(f"{error}\n\nQuickDesk started with the default commands.")

    settings_path = config_dir / "settings.json"
    settings, settings_warning = load_settings(settings_path, DEFAULT_SETTINGS)
    if settings_warning:
        warnings.append(settings_warning)

    library = CommandLibrary(merge_builtins(commands, builtins))
    QuickDeskApp(
        store,
        library,
        "\n\n".join(warnings) or None,
        hotkey=settings["hotkey"],
        settings_path=settings_path,
    ).mainloop()
