# -*- coding: utf-8 -*-
import os.path
import sys
import tkinter as tk
import tokenize
import traceback
from logging import exception
from tkinter import messagebox, ttk
from tkinter.messagebox import askyesno

from thonny import get_workbench, ui_utils, get_runner
from thonny.codeview import CodeView
from thonny.common import (
    TextRange,
    ToplevelResponse,
    normpath_with_actual_case,
    is_same_path,
    InlineCommand,
)
from thonny.tktextext import rebind_control_a
from thonny.ui_utils import askopenfilename, asksaveasfilename, select_sequence
from thonny.misc_utils import running_on_windows
from _tkinter import TclError
from thonny.base_file_browser import choose_node_for_file_operations, ask_backend_path

# i18n #
import gettext
gettext.install('thonny', os.path.dirname(__file__))

_dialog_filetypes = [(_("Python files"), ".py .pyw"), (_("text files"), ".txt"), (_("all files"), ".*")]

REMOTE_PATH_MARKER = " :: "


class Editor(ttk.Frame):
    def __init__(self, master):

        ttk.Frame.__init__(self, master)
        assert isinstance(master, EditorNotebook)

        # parent of codeview will be workbench so that it can be maximized
        self._code_view = CodeView(
            get_workbench(), propose_remove_line_numbers=True, font="EditorFont"
        )
        get_workbench().event_generate(
            "EditorTextCreated", editor=self, text_widget=self.get_text_widget()
        )

        self._code_view.grid(row=0, column=0, sticky=tk.NSEW, in_=self)
        self._code_view.home_widget = self  # don't forget home
        self.maximizable_widget = self._code_view

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._newlines = None
        self._filename = None
        self._last_known_mtime = None
        self._asking_about_external_change = False
        self._loading = False
        self._waiting_write_completion = False

        self._code_view.text.bind("<<Modified>>", self._on_text_modified, True)
        self._code_view.text.bind("<<TextChange>>", self._on_text_change, True)
        self._code_view.text.bind("<Control-Tab>", self._control_tab, True)

        get_workbench().bind("DebuggerResponse", self._listen_debugger_progress, True)
        get_workbench().bind("ToplevelResponse", self._listen_for_toplevel_response, True)
        get_workbench().bind("read_file_response", self._complete_loading_remote_file, True)
        get_workbench().bind("write_file_response", self._complete_writing_remote_file, True)

        self.update_appearance()

    def get_text_widget(self):
        return self._code_view.text

    def get_code_view(self):
        # TODO: try to get rid of this
        return self._code_view

    def get_filename(self, try_hard=False):
        if self._filename is None and try_hard:
            self.save_file()

        return self._filename

    def get_title(self):
        if self.get_filename() is None:
            result = _("<untitled>")
        elif is_remote_path(self.get_filename()):
            path = extract_target_path(self.get_filename())
            name = path.split("/")[-1]
            result = "[ " + name + " ]"
        else:
            result = os.path.basename(self.get_filename())

        if self._loading:
            result += " ..."
        elif self.is_modified():
            result += " *"

        return result

    def check_for_external_changes(self):
        if self._asking_about_external_change:
            # otherwise method will be re-entered when focus
            # changes because of message box
            return

        if self._filename is None:
            return

        if is_remote_path(self._filename):
            return

        try:
            self._asking_about_external_change = True

            if self._last_known_mtime is None:
                return

            elif not os.path.exists(self._filename):
                self.master.select(self)

                if messagebox.askyesno(
                    _("File is gone"),
                    _("Looks like '%s' was deleted or moved outside Thonny.\n\n") % self._filename
                    + _("Do you want to also close this editor?"),
                    parent=get_workbench(),
                ):
                    self.master.close_editor(self)
                else:
                    self.get_text_widget().edit_modified(True)
                    self._last_known_mtime = None

            elif os.path.getmtime(self._filename) != self._last_known_mtime:
                self.master.select(self)

                if messagebox.askyesno(
                    _("External modification"),
                    _("Looks like '%s' was modified outside Thonny.\n\n") % self._filename
                    + _("Do you want to discard current editor content and reload the file from disk?"),
                    parent=get_workbench(),
                ):
                    self._load_file(self._filename, keep_undo=True)
                else:
                    self._last_known_mtime = os.path.getmtime(self._filename)
        finally:
            self._asking_about_external_change = False

    def get_long_description(self):

        if self._filename is None:
            result = _("<untitled>")
        else:
            result = self._filename

        try:
            index = self._code_view.text.index("insert")
            if index and "." in index:
                line, col = index.split(".")
                result += "  @  {} : {}".format(line, int(col) + 1)
        except Exception:
            exception(_("Finding cursor location"))

        return result

    def _load_file(self, filename, keep_undo=False):
        self._waiting_write_completion = False

        if is_remote_path(filename):
            self._start_loading_remote_file(filename)
        else:
            self._load_local_file(filename, keep_undo)

        self.update_appearance()

    def _load_local_file(self, filename, keep_undo=False):
        with tokenize.open(filename) as fp:  # TODO: support also text files
            source = fp.read()

        # get the file file format (DOS/UNIX)
        self._newlines = fp.newlines

        # Make sure Windows filenames have proper format
        filename = normpath_with_actual_case(filename)
        self._filename = filename
        self._last_known_mtime = os.path.getmtime(self._filename)

        get_workbench().event_generate("Open", editor=self, filename=filename)
        self._code_view.set_content(source, keep_undo)
        self.get_text_widget().edit_modified(False)
        self._code_view.focus_set()
        self.master.remember_recent_file(filename)
        self._loading = False

    def _start_loading_remote_file(self, filename):
        self._loading = True
        self._filename = filename
        self._newlines = None
        self._code_view.set_content("")
        self._code_view.text.set_read_only(True)

        target_filename = extract_target_path(self._filename)

        get_runner().send_command(InlineCommand("read_file", path=target_filename))
        self.update_title()

    def _complete_loading_remote_file(self, msg):
        if not self._filename or not self._filename.endswith(msg["path"]):
            return

        content = msg["content_bytes"]

        if msg.get("error"):
            # TODO: make it softer
            raise RuntimeError(msg["error"])

        if content.count(b"\r\n") > content.count(b"\n") / 2:
            self._newlines = "\r\n"
        else:
            self._newlines = "\n"

        self._code_view.text.set_read_only(False)
        self._code_view.set_content_as_bytes(content)
        self.get_text_widget().edit_modified(False)
        self._loading = False
        self.update_title()

    def is_modified(self):
        return self._code_view.text.edit_modified()

    def save_file_enabled(self):
        return self.is_modified() or not self.get_filename()

    def save_file(self, ask_filename=False):
        if self._filename is not None and not ask_filename:
            get_workbench().event_generate("Save", editor=self, filename=self._filename)
        else:
            new_filename = self.ask_new_path()
            if not new_filename:
                return None

            self._filename = new_filename
            get_workbench().event_generate("SaveAs", editor=self, filename=self._filename)

        content_bytes = self._code_view.get_content_as_bytes(self._newlines)

        if is_remote_path(self._filename):
            return self.write_remote_file(content_bytes)
        else:
            return self.write_local_file(content_bytes)

    def write_local_file(self, content_bytes):
        try:
            f = open(self._filename, mode="wb")
            f.write(content_bytes)
            f.flush()
            # Force writes on disk, see https://learn.adafruit.com/adafruit-circuit-playground-express/creating-and-editing-code#1-use-an-editor-that-writes-out-the-file-completely-when-you-save-it
            os.fsync(f)
            f.close()
            self._last_known_mtime = os.path.getmtime(self._filename)
            get_workbench().event_generate(
                "LocalFileOperation", path=self._filename, operation="save"
            )
        except PermissionError:
            if askyesno(
                _("Permission Error"),
                _("Looks like this file or folder is not writable.\n\n")
                + _("Do you want to save under another folder and/or filename?"),
                parent=get_workbench(),
            ):
                return self.save_file(True)
            else:
                return None

        self.master.remember_recent_file(self._filename)

        self._waiting_write_completion = False
        self._code_view.text.edit_modified(False)

        return self._filename

    def write_remote_file(self, content_bytes):
        if get_runner().can_do_file_operations():
            target_filename = extract_target_path(self._filename)
            self._waiting_write_completion = True
            get_runner().send_command(
                InlineCommand("write_file", path=target_filename, content_bytes=content_bytes)
            )

            # NB! edit_modified is not falsed yet!
            get_workbench().event_generate(
                "RemoteFileOperation", path=extract_target_path(self._filename), operation="save"
            )
            return self._filename
        else:
            messagebox.showwarning("Can't save", "Device is busy, wait and try again!")
            return None

    def _complete_writing_remote_file(self, msg):
        if (
            self._waiting_write_completion
            and self._filename
            and extract_target_path(self._filename) == msg["path"]
        ):
            self._code_view.text.edit_modified(False)
            self.update_title()

    def ask_new_path(self):
        node = choose_node_for_file_operations(self.winfo_toplevel(), "Where to save to?")
        if not node:
            return None

        if node == "local":
            return self.ask_new_local_path()
        else:
            assert node == "remote"
            return self.ask_new_remote_path()

    def ask_new_remote_path(self):
        target_path = ask_backend_path(self.winfo_toplevel(), "save")
        if target_path:
            return make_remote_path(target_path)
        else:
            return None

    def ask_new_local_path(self):
        if self._filename is None:
            initialdir = get_workbench().get_cwd()
            initialfile = None
        else:
            initialdir = os.path.dirname(self._filename)
            initialfile = os.path.basename(self._filename)

        # http://tkinter.unpythonic.net/wiki/tkFileDialog
        new_filename = asksaveasfilename(
            master=get_workbench(),
            filetypes=_dialog_filetypes,
            defaultextension=".py",
            initialdir=initialdir,
            initialfile=initialfile,
        )

        # Different tkinter versions may return different values
        if new_filename in ["", (), None]:
            return None

        # Seems that in some Python versions defaultextension
        # acts funny
        if new_filename.lower().endswith(".py.py"):
            new_filename = new_filename[:-3]

        if running_on_windows():
            # may have /-s instead of \-s and wrong case
            new_filename = os.path.join(
                normpath_with_actual_case(os.path.dirname(new_filename)),
                os.path.basename(new_filename),
            )

        if new_filename.endswith(".py"):
            base = os.path.basename(new_filename)
            mod_name = base[:-3].lower()
            if running_on_windows():
                mod_name = mod_name.lower()

            if mod_name in [
                "math",
                "turtle",
                "random",
                "statistics",
                "pygame",
                "matplotlib",
                "numpy",
            ]:

                # More proper name analysis will be performed by ProgramNamingAnalyzer
                if not tk.messagebox.askyesno(
                    _("Potential problem"),
                    _("If you name your script '%s', ") % base
                    +  _("you won't be able to import the library module named '%s'") % mod_name
                    + ".\n\n"
                    +  _("Do you still want to use this name for your script?"),
                    parent=get_workbench(),
                ):
                    return self.ask_new_local_path()

        return new_filename

    def show(self):
        self.master.select(self)

    def update_appearance(self):
        self._code_view.set_gutter_visibility(
            get_workbench().get_option("view.show_line_numbers")
            or get_workbench().in_simple_mode()
        )
        self._code_view.set_line_length_margin(
            get_workbench().get_option("view.recommended_line_length")
        )
        self._code_view.text.event_generate("<<UpdateAppearance>>")

    def _listen_debugger_progress(self, event):
        # Go read-only
        # TODO: check whether this module is active?
        self._code_view.text.set_read_only(True)

    def _listen_for_toplevel_response(self, event: ToplevelResponse) -> None:
        self._code_view.text.set_read_only(False)

    def _control_tab(self, event):
        if event.state & 1:  # shift was pressed
            direction = -1
        else:
            direction = 1
        self.master.select_next_prev_editor(direction)
        return "break"

    def _shift_control_tab(self, event):
        self.master.select_next_prev_editor(-1)
        return "break"

    def select_range(self, text_range):
        self._code_view.select_range(text_range)

    def select_line(self, lineno, col_offset=None):
        self._code_view.select_range(TextRange(lineno, 0, lineno + 1, 0))
        self.see_line(lineno)

        if col_offset is None:
            col_offset = 0

        self.get_text_widget().mark_set("insert", "%d.%d" % (lineno, col_offset))

    def see_line(self, lineno):
        # first see an earlier line in order to push target line downwards
        self._code_view.text.see("%d.0" % max(lineno - 4, 1))
        self._code_view.text.see("%d.0" % lineno)

    def focus_set(self):
        self._code_view.focus_set()

    def is_focused(self):
        return self.focus_displayof() == self._code_view.text

    def _on_text_modified(self, event):
        self.update_title()
        self._waiting_write_completion = False

    def update_title(self):
        try:
            self.master.update_editor_title(self)
        except Exception:
            traceback.print_exc()

    def _on_text_change(self, event):
        self.update_title()
        self._waiting_write_completion = False

    def destroy(self):
        get_workbench().unbind("DebuggerResponse", self._listen_debugger_progress)
        get_workbench().unbind("ToplevelResponse", self._listen_for_toplevel_response)
        ttk.Frame.destroy(self)


class EditorNotebook(ui_utils.ClosableNotebook):
    """
    Manages opened files / modules
    """

    def __init__(self, master):
        super().__init__(master, padding=0)

        get_workbench().set_default("file.reopen_all_files", False)
        get_workbench().set_default("file.open_files", [])
        get_workbench().set_default("file.current_file", None)
        get_workbench().set_default("file.recent_files", [])
        get_workbench().set_default("view.highlight_current_line", False)
        get_workbench().set_default("view.show_line_numbers", True)
        get_workbench().set_default("view.recommended_line_length", 0)

        self._recent_menu = tk.Menu(
            get_workbench().get_menu("file"), postcommand=self._update_recent_menu
        )
        self._init_commands()
        self.enable_traversal()

        # open files from last session
        """ TODO: they should go only to recent files
        for filename in prefs["open_files"].split(";"):
            if os.path.exists(filename):
                self._open_file(filename)
        """

        self.update_appearance()

        # should be in the end, so that it can be detected when
        # constructor hasn't completed yet
        self.preferred_size_in_pw = None

        get_workbench().bind("WindowFocusIn", self.on_focus_window, True)

    def _init_commands(self):
        # TODO: do these commands have to be in EditorNotebook ??
        # Create a module level function install_editor_notebook ??
        # Maybe add them separately, when notebook has been installed ??

        get_workbench().add_command(
            "new_file",
            "file",
            _("New"),
            self._cmd_new_file,
            caption=_("New"),
            default_sequence=select_sequence("<Control-n>", "<Command-n>"),
            extra_sequences=["<Control-Greek_nu>"],
            group=10,
            image="new-file",
            include_in_toolbar=True,
        )

        get_workbench().add_command(
            "open_file",
            "file",
            _("Open..."),
            self._cmd_open_file,
            caption=_("Load"),
            default_sequence=select_sequence("<Control-o>", "<Command-o>"),
            extra_sequences=["<Control-Greek_omicron>"],
            group=10,
            image="open-file",
            include_in_toolbar=True,
        )

        get_workbench().add_command(
            "recents", "file", _("Recent files"), group=10, submenu=self._recent_menu
        )

        # http://stackoverflow.com/questions/22907200/remap-default-keybinding-in-tkinter
        get_workbench().bind_class("Text", "<Control-o>", self._control_o)
        get_workbench().bind_class("Text", "<Control-Greek_omicron>", self._control_o)
        rebind_control_a(get_workbench())

        get_workbench().add_command(
            "close_file",
            "file",
            _("Close"),
            self._cmd_close_file,
            default_sequence=select_sequence("<Control-w>", "<Command-w>"),
            extra_sequences=["<Control-Greek_finalsmallsigma>"],
            tester=lambda: self.get_current_editor() is not None,
            group=10,
        )

        get_workbench().add_command(
            "close_files",
            "file",
            _("Close all"),
            self.close_tabs,
            tester=lambda: self.get_current_editor() is not None,
            default_sequence=select_sequence("<Control-W>", "<Command-Alt-w>"),
            group=10,
        )

        get_workbench().add_command(
            "save_file",
            "file",
            _("Save"),
            self._cmd_save_file,
            caption=_("Save"),
            default_sequence=select_sequence("<Control-s>", "<Command-s>"),
            extra_sequences=["<Control-Greek_sigma>"],
            tester=self._cmd_save_file_enabled,
            group=10,
            image="save-file",
            include_in_toolbar=True,
        )

        get_workbench().add_command(
            "save_file_as",
            "file",
            _("Save as..."),
            self._cmd_save_file_as,
            default_sequence=select_sequence("<Control-Shift-S>", "<Command-Shift-S>"),
            extra_sequences=["<Control-Greek_SIGMA>"],
            tester=lambda: self.get_current_editor() is not None,
            group=10,
        )

        get_workbench().add_command(
            "rename_file",
            "file",
            _("Rename..."),
            self._cmd_rename_file,
            tester=self._cmd_rename_file_enabled,
            group=10,
        )

        get_workbench().createcommand("::tk::mac::OpenDocument", self._mac_open_document)

    def load_startup_files(self):
        """If no filename was sent from command line
        then load previous files (if setting allows)"""

        cmd_line_filenames = [
            os.path.abspath(name) for name in sys.argv[1:] if os.path.exists(name)
        ]

        if len(cmd_line_filenames) > 0:
            filenames = cmd_line_filenames
        elif get_workbench().get_option("file.reopen_all_files"):
            filenames = get_workbench().get_option("file.open_files")
        elif get_workbench().get_option("file.current_file"):
            filenames = [get_workbench().get_option("file.current_file")]
        else:
            filenames = []

        if len(filenames) > 0:
            for filename in filenames:
                if os.path.exists(filename):
                    self.show_file(filename)

            cur_file = get_workbench().get_option("file.current_file")
            # choose correct active file
            if len(cmd_line_filenames) > 0:
                self.show_file(cmd_line_filenames[0])
            elif cur_file and os.path.exists(cur_file):
                self.show_file(cur_file)
            else:
                self._cmd_new_file()
        else:
            self._cmd_new_file()

    def save_all_named_editors(self):
        all_saved = True
        for editor in self.winfo_children():
            if editor.get_filename() and editor.is_modified():
                success = editor.save_file()
                all_saved = all_saved and success

        return all_saved

    def remember_recent_file(self, filename):
        recents = get_workbench().get_option("file.recent_files")
        if filename in recents:
            recents.remove(filename)
        recents.insert(0, filename)
        relevant_recents = [name for name in recents if os.path.exists(name)][:15]
        get_workbench().set_option("file.recent_files", relevant_recents)
        self._update_recent_menu()

    def _update_recent_menu(self):
        recents = get_workbench().get_option("file.recent_files")
        relevant_recents = [
            path for path in recents if os.path.exists(path) and not self.file_is_opened(path)
        ]
        self._recent_menu.delete(0, "end")
        for path in relevant_recents:

            def load(path=path):
                self.show_file(path)

            self._recent_menu.insert_command("end", label=path, command=load)

    def remember_open_files(self):
        if (
            self.get_current_editor() is not None
            and self.get_current_editor().get_filename() is not None
        ):
            current_file = self.get_current_editor().get_filename()
        else:
            current_file = None

        get_workbench().set_option("file.current_file", current_file)

        open_files = [
            editor.get_filename() for editor in self.winfo_children() if editor.get_filename()
        ]
        get_workbench().set_option("file.open_files", open_files)

    def _cmd_new_file(self):
        new_editor = Editor(self)
        get_workbench().event_generate("NewFile", editor=new_editor)
        self.add(new_editor, text=new_editor.get_title())
        self.select(new_editor)
        new_editor.focus_set()

    def _cmd_open_file(self):
        node = choose_node_for_file_operations(self.winfo_toplevel(), "Where to open from?")
        if not node:
            return None

        if node == "local":
            path = askopenfilename(
                master=get_workbench(),
                filetypes=_dialog_filetypes,
                initialdir=get_workbench().get_cwd(),
            )
        else:
            assert node == "remote"
            target_path = ask_backend_path(self.winfo_toplevel(), "open")
            if not target_path:
                return None

            path = make_remote_path(target_path)

        if path:
            # self.close_single_untitled_unmodified_editor()
            self.show_file(path)

    def _control_o(self, event):
        # http://stackoverflow.com/questions/22907200/remap-default-keybinding-in-tkinter
        self._cmd_open_file()
        return "break"

    def _close_files(self, except_index=None):

        for tab_index in reversed(range(len(self.winfo_children()))):
            if except_index is not None and tab_index == except_index:
                continue
            else:
                editor = self.get_child_by_index(tab_index)
                if self.check_allow_closing(editor):
                    self.forget(editor)
                    editor.destroy()

    def _cmd_close_file(self):
        self.close_tab(self.index(self.select()))

    def close_tab(self, index):
        editor = self.get_child_by_index(index)

        if editor:
            self.close_editor(editor)

    def close_editor(self, editor, force=False):
        if not force and not self.check_allow_closing(editor):
            return
        self.forget(editor)
        editor.destroy()

    def _cmd_save_file(self):
        if self.get_current_editor():
            self.get_current_editor().save_file()
            self.update_editor_title(self.get_current_editor())

    def _cmd_save_file_enabled(self):
        return self.get_current_editor() and self.get_current_editor().save_file_enabled()

    def _cmd_save_file_as(self):
        if not self.get_current_editor():
            return

        self.get_current_editor().save_file(ask_filename=True)
        self.update_editor_title(self.get_current_editor())
        get_workbench().update_title()

    def _cmd_save_file_as_enabled(self):
        return self.get_current_editor() is not None

    def _cmd_rename_file(self):
        editor = self.get_current_editor()
        old_filename = editor.get_filename()
        assert old_filename is not None

        self._cmd_save_file_as()

        if editor.get_filename() != old_filename:
            os.remove(old_filename)

    def _cmd_rename_file_enabled(self):
        return self.get_current_editor() and self.get_current_editor().get_filename() is not None

    def close_single_untitled_unmodified_editor(self):
        editors = self.winfo_children()
        if len(editors) == 1 and not editors[0].is_modified() and not editors[0].get_filename():
            self._cmd_close_file()

    def _mac_open_document(self, *args):
        for arg in args:
            if isinstance(arg, str) and os.path.exists(arg):
                self.show_file(arg)
        get_workbench().become_active_window()

    def get_current_editor(self):
        return self.get_current_child()

    def get_all_editors(self):
        # When workspace is closing, self.winfo_children()
        # may return an unexplainable tkinter.Frame
        return [child for child in self.winfo_children() if isinstance(child, Editor)]

    def select_next_prev_editor(self, direction):
        cur_index = self.index(self.select())
        next_index = (cur_index + direction) % len(self.tabs())
        self.select(self.get_child_by_index(next_index))

    def file_is_opened(self, path):
        for editor in self.get_all_editors():
            if editor.get_filename() and is_same_path(path, editor.get_filename()):
                return True

        return False

    def show_file(self, filename, text_range=None, set_focus=True):
        # self.close_single_untitled_unmodified_editor()
        editor = self.get_editor(filename, True)
        assert editor is not None

        self.select(editor)
        if set_focus:
            editor.focus_set()

        if text_range is not None:
            editor.select_range(text_range)

        return editor

    def show_remote_file(self, target_filename):
        if not get_runner().can_do_file_operations():
            messagebox.showwarning(
                "Can't open",
                "Device is busy, can't read file content.\n" + "Please try again later!",
            )
            return None
        else:
            return self.show_file(make_remote_path(target_filename))

    def show_file_at_line(self, filename, lineno, col_offset=None):
        editor = self.show_file(filename)
        editor.select_line(lineno, col_offset)

    def update_appearance(self):
        for editor in self.winfo_children():
            editor.update_appearance()

    def update_editor_title(self, editor, title=None):
        if title is None:
            title = editor.get_title()
        try:
            self.tab(editor, text=title)
        except TclError:
            pass

    def _open_file(self, filename):
        editor = Editor(self)
        editor._load_file(filename)
        self.add(editor, text=editor.get_title())

        return editor

    def get_editor(self, filename, open_when_necessary=False):
        for child in self.winfo_children():
            child_filename = child.get_filename(False)
            if child_filename == filename:
                return child

        if open_when_necessary:
            return self._open_file(filename)
        else:
            return None

    def check_allow_closing(self, editor=None):
        if not editor:
            modified_editors = [e for e in self.winfo_children() if e.is_modified()]
        else:
            if not editor.is_modified():
                return True
            else:
                modified_editors = [editor]
        if len(modified_editors) == 0:
            return True

        message = _("Do you want to save files before closing?")
        if editor:
            message = _("Do you want to save file before closing?")

        confirm = messagebox.askyesnocancel(
            title=_("Save On Close"),
            message=message,
            default=messagebox.YES,
            master=get_workbench(),
            parent=get_workbench(),
        )

        if confirm:
            for editor_ in modified_editors:
                if editor_.get_filename(True):
                    editor_.save_file()
                else:
                    return False
            return True

        elif confirm is None:
            return False
        else:
            return True

    def on_focus_window(self, event=None):
        for editor in self.get_all_editors():
            editor.check_for_external_changes()


def get_current_breakpoints():
    result = {}

    for editor in get_workbench().get_editor_notebook().get_all_editors():
        filename = editor.get_filename()
        if filename:
            linenos = editor.get_code_view().get_breakpoint_line_numbers()
            if linenos:
                result[filename] = linenos

    return result


def get_saved_current_script_filename(force=True):
    editor = get_workbench().get_editor_notebook().get_current_editor()
    if not editor:
        return

    filename = editor.get_filename(force)
    if not filename:
        return

    if editor.is_modified():
        filename = editor.save_file()

    return filename


def is_remote_path(s):
    return REMOTE_PATH_MARKER in s


def extract_target_path(s):
    assert is_remote_path(s)
    return s[s.find(REMOTE_PATH_MARKER) + len(REMOTE_PATH_MARKER) :]


def make_remote_path(target_path):
    return get_runner().get_node_label() + REMOTE_PATH_MARKER + target_path
