import textwrap
import tkinter as tk
from tkinter import font as tk_font
from tkinter import ttk

from thonny import get_workbench
from thonny.codeview import CodeView, get_syntax_options_for_tag
from thonny.config_ui import ConfigurationPage
from thonny.ui_utils import create_string_var


class ThemeAndFontConfigurationPage(ConfigurationPage):
    def __init__(self, master):

        self._original_family = get_workbench().get_option("view.editor_font_family")
        self._original_size = get_workbench().get_option("view.editor_font_size")
        self._original_ui_theme = get_workbench().get_option("view.ui_theme")
        self._original_syntax_theme = get_workbench().get_option("view.syntax_theme")
        self._original_io_family = get_workbench().get_option("view.io_font_family")
        self._original_io_size = get_workbench().get_option("view.io_font_size")

        ConfigurationPage.__init__(self, master)

        self._family_variable = create_string_var(
            self._original_family, modification_listener=self._update_appearance
        )

        self._size_variable = create_string_var(
            self._original_size, modification_listener=self._update_appearance
        )

        self._ui_theme_variable = create_string_var(
            self._original_ui_theme, modification_listener=self._update_appearance
        )

        self._syntax_theme_variable = create_string_var(
            self._original_syntax_theme, modification_listener=self._update_appearance
        )
        self._io_family_variable = create_string_var(
            self._original_io_family, modification_listener=self._update_appearance
        )

        self._io_size_variable = create_string_var(
            self._original_io_size, modification_listener=self._update_appearance
        )

        ttk.Label(self, text=_("UI theme")).grid(row=1, column=0, sticky="w", pady=(10, 0))
        self._ui_theme_combo = ttk.Combobox(
            self,
            exportselection=False,
            textvariable=self._ui_theme_variable,
            state="readonly",
            height=15,
            values=get_workbench().get_usable_ui_theme_names(),
        )
        self._ui_theme_combo.grid(row=2, column=0, sticky="nsew", padx=(0, 10))

        ttk.Label(self, text=_("Syntax theme")).grid(row=1, column=1, sticky="w", pady=(10, 0))
        self._syntax_theme_combo = ttk.Combobox(
            self,
            exportselection=False,
            textvariable=self._syntax_theme_variable,
            state="readonly",
            height=15,
            values=get_workbench().get_syntax_theme_names(),
        )
        self._syntax_theme_combo.grid(row=2, column=1, sticky="nsew", padx=(0, 10))

        ttk.Label(self, text=_("Editor font")).grid(row=1, column=2, sticky="w", pady=(10, 0))
        self._family_combo = ttk.Combobox(
            self,
            exportselection=False,
            state="readonly",
            height=15,
            textvariable=self._family_variable,
            values=self._get_families_to_show(),
        )
        self._family_combo.grid(row=2, column=2, sticky=tk.NSEW, padx=(0, 10))

        ttk.Label(self, text=_("Size")).grid(row=1, column=3, sticky="w", pady=(10, 0))
        self._size_combo = ttk.Combobox(
            self,
            width=4,
            exportselection=False,
            textvariable=self._size_variable,
            state="readonly",
            height=15,
            values=[str(x) for x in range(3, 73)],
        )
        self._size_combo.grid(row=2, column=3, sticky="nsew")

        ttk.Label(self, text=_("Editor preview")).grid(
            row=3, column=0, sticky="w", pady=(10, 0), columnspan=4
        )
        self._preview_codeview = CodeView(
            self,
            height=6,
            font="EditorFont",
            # relief="sunken",
            # borderwidth=1,
        )

        self._preview_codeview.set_content(
            textwrap.dedent(
                """
            def foo(bar):
                if bar is None: # This is a comment
                    print("The answer is", 33)

            unclosed_string = "blah, blah
            """
            ).strip()
        )
        self._preview_codeview.grid(row=4, column=0, columnspan=4, sticky=tk.NSEW, pady=(0, 5))

        ttk.Label(self, text="Shell font").grid(row=5, column=2, sticky="w", pady=(10, 0))
        self._family_combo = ttk.Combobox(
            self,
            exportselection=False,
            state="readonly",
            height=15,
            textvariable=self._io_family_variable,
            values=self._get_families_to_show(),
        )
        self._family_combo.grid(row=6, column=2, sticky=tk.NSEW, padx=(0, 10))

        ttk.Label(self, text="Size").grid(row=5, column=3, sticky="w", pady=(10, 0))
        self._size_combo = ttk.Combobox(
            self,
            width=4,
            exportselection=False,
            textvariable=self._io_size_variable,
            state="readonly",
            height=15,
            values=[str(x) for x in range(3, 73)],
        )
        self._size_combo.grid(row=6, column=3, sticky="nsew")

        ttk.Label(self, text="Shell preview").grid(
            row=7, column=0, sticky="w", pady=(10, 0), columnspan=4
        )
        self._shell_preview = tk.Text(self, height=3)
        self._shell_preview.grid(row=8, column=0, columnspan=4, sticky=tk.NSEW, pady=(0, 5))
        self._insert_shell_text()

        ttk.Label(self, text=_("NB! Some style elements change only after restarting Thonny")).grid(
            row=9, column=0, columnspan=4, sticky="w", pady=(0, 5)
        )

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)
        self.columnconfigure(3, weight=1)

    def apply(self):
        # don't do anything, as preview already did the thing
        return

    def cancel(self):
        if (
            getattr(self._family_variable, "modified")
            or getattr(self._size_variable, "modified")
            or getattr(self._ui_theme_variable, "modified")
            or getattr(self._syntax_theme_variable, "modified")
        ):
            get_workbench().set_option("view.ui_theme", self._original_ui_theme)
            get_workbench().set_option("view.syntax_theme", self._original_syntax_theme)
            get_workbench().set_option("view.editor_font_size", self._original_size)
            get_workbench().set_option("view.editor_font_family", self._original_family)
            get_workbench().set_option("view.io_font_size", self._original_io_size)
            get_workbench().set_option("view.io_font_family", self._original_io_family)
            get_workbench().reload_themes()
            get_workbench().update_fonts()

    def _update_appearance(self):
        get_workbench().set_option("view.ui_theme", self._ui_theme_variable.get())
        get_workbench().set_option("view.syntax_theme", self._syntax_theme_variable.get())
        get_workbench().set_option("view.editor_font_size", int(self._size_variable.get()))
        get_workbench().set_option("view.editor_font_family", self._family_variable.get())
        get_workbench().set_option("view.io_font_size", int(self._io_size_variable.get()))
        get_workbench().set_option("view.io_font_family", self._io_family_variable.get())
        get_workbench().reload_themes()
        get_workbench().update_fonts()
        self._update_shell_appearance()

    def _insert_shell_text(self):
        self._shell_preview.configure(font="IOFont")
        self._update_shell_appearance()
        self._shell_preview.insert("1.0", "Output from a print statement.\n", "stdout")
        self._shell_preview.insert(tk.END, "Input from a user.\n", "stdin")
        self._shell_preview.insert(tk.END, "A Python exception.", "stderr")

    def _update_shell_appearance(self):
        background = get_syntax_options_for_tag("TEXT")["background"]
        stderr_fg = get_syntax_options_for_tag("stderr")["foreground"]
        stdin_fg = get_syntax_options_for_tag("stdin")["foreground"]
        stdout_fg = get_syntax_options_for_tag("stdout")["foreground"]

        self._shell_preview.configure(background=background)
        self._shell_preview.tag_configure("stderr", foreground=stderr_fg)
        self._shell_preview.tag_configure("stdin", foreground=stdin_fg)
        self._shell_preview.tag_configure("stdout", foreground=stdout_fg)

    def _get_families_to_show(self):
        # In Linux, families may contain duplicates (actually different fonts get same names)
        return sorted(set(filter(lambda name: name[0].isalpha(), tk_font.families())))


def load_plugin() -> None:
    get_workbench().add_configuration_page(_("Theme & Font"), ThemeAndFontConfigurationPage)
