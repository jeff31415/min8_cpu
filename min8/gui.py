"""Tkinter-based GUI simulator/debugger for Min8."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import pprint
import re
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .cpu import StepResult
from .exceptions import IllegalInstruction, MachineHalted
from .host_audio import HostAudioPlaybackManager
from .io import AudioOutputDevice, FILOStackDevice, PS2KeyboardDevice, WS2812Device
from .isa import decode_opcode
from .session import Min8Session

MONO_FONT = ("Courier New", 10)
MONO_FONT_SMALL = ("Courier New", 9)

SOURCE_NUMBER_RE = re.compile(r"0x[0-9A-Fa-f]+|0b[01]+|\b\d+\b|'[^']'")
REGISTER_RE = re.compile(r"\bR[0-7]\b", re.IGNORECASE)
LABEL_RE = re.compile(r"\s*([A-Za-z_.$][A-Za-z0-9_.$]*:)")
TOKEN_RE = re.compile(r"\S+")
DISASM_LINE_RE = re.compile(r"^([0-9A-F]{2}:)\s+([0-9A-F]{2})\s+([^;]+)(.*)$")

TEXT_INPUT_WIDGETS = tuple(
    widget
    for widget in (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, tk.Spinbox, getattr(ttk, "Spinbox", None))
    if widget is not None
)
PS2_SCANCODES = {
    "a": (0x1C,),
    "b": (0x32,),
    "c": (0x21,),
    "d": (0x23,),
    "e": (0x24,),
    "f": (0x2B,),
    "g": (0x34,),
    "h": (0x33,),
    "i": (0x43,),
    "j": (0x3B,),
    "k": (0x42,),
    "l": (0x4B,),
    "m": (0x3A,),
    "n": (0x31,),
    "o": (0x44,),
    "p": (0x4D,),
    "q": (0x15,),
    "r": (0x2D,),
    "s": (0x1B,),
    "t": (0x2C,),
    "u": (0x3C,),
    "v": (0x2A,),
    "w": (0x1D,),
    "x": (0x22,),
    "y": (0x35,),
    "z": (0x1A,),
    "0": (0x45,),
    "1": (0x16,),
    "2": (0x1E,),
    "3": (0x26,),
    "4": (0x25,),
    "5": (0x2E,),
    "6": (0x36,),
    "7": (0x3D,),
    "8": (0x3E,),
    "9": (0x46,),
    "space": (0x29,),
    "return": (0x5A,),
    "backspace": (0x66,),
    "tab": (0x0D,),
    "escape": (0x76,),
    "minus": (0x4E,),
    "equal": (0x55,),
    "bracketleft": (0x54,),
    "bracketright": (0x5B,),
    "backslash": (0x5D,),
    "semicolon": (0x4C,),
    "apostrophe": (0x52,),
    "comma": (0x41,),
    "period": (0x49,),
    "slash": (0x4A,),
    "grave": (0x0E,),
    "shift_l": (0x12,),
    "shift_r": (0x59,),
    "control_l": (0x14,),
    "alt_l": (0x11,),
    "up": (0xE0, 0x75),
    "down": (0xE0, 0x72),
    "left": (0xE0, 0x6B),
    "right": (0xE0, 0x74),
    "insert": (0xE0, 0x70),
    "delete": (0xE0, 0x71),
    "home": (0xE0, 0x6C),
    "end": (0xE0, 0x69),
    "prior": (0xE0, 0x7D),
    "next": (0xE0, 0x7A),
}
PS2_KEY_ALIASES = {
    "exclam": "1",
    "at": "2",
    "numbersign": "3",
    "dollar": "4",
    "percent": "5",
    "asciicircum": "6",
    "ampersand": "7",
    "asterisk": "8",
    "parenleft": "9",
    "parenright": "0",
    "underscore": "minus",
    "plus": "equal",
    "braceleft": "bracketleft",
    "braceright": "bracketright",
    "bar": "backslash",
    "colon": "semicolon",
    "quotedbl": "apostrophe",
    "less": "comma",
    "greater": "period",
    "question": "slash",
    "asciitilde": "grave",
    "kp_enter": "return",
}

REGISTER_GROUPS = (
    ("ALU Path", ("R0", "R1", "R2"), {"frame": "#18324A", "title": "#D5ECFF", "text": "#EAF6FF"}),
    ("General", ("R3", "R4", "R5", "R6"), {"frame": "#2C2A4A", "title": "#E4DEFF", "text": "#F1EEFF"}),
    ("Address / I/O", ("R7", "PC", "IOSEL", "Pending"), {"frame": "#214336", "title": "#DCFBEA", "text": "#EDFFF5"}),
    ("Flags", ("Z", "C"), {"frame": "#4A311A", "title": "#FFE8C7", "text": "#FFF4E5"}),
)

MEMORY_COLORS = {
    "default_bg": "#0F1720",
    "default_fg": "#D7E3EE",
    "changed_bg": "#F4D35E",
    "changed_fg": "#201A0E",
    "current_bg": "#285E8E",
    "current_fg": "#F7FBFF",
    "breakpoint_bg": "#7A1F45",
    "breakpoint_fg": "#FFF0F6",
    "pointer_bg": "#2A6A46",
    "pointer_fg": "#F3FFF7",
    "selected_bg": "#39424C",
    "selected_fg": "#F7FBFF",
}

SLOW_RUN_BATCH_STEPS = 64
SLOW_RUN_FRAME_BATCHES = 8
FAST_RUN_BATCH_STEPS = 4096
FAST_RUN_MAX_BUDGET_STEPS = FAST_RUN_BATCH_STEPS * 8


class Min8Gui(tk.Tk):
    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.title("Min8 GUI Simulator")
        self.geometry("1460x900")
        self.minsize(1280, 780)

        self.session = Min8Session()
        self.running = False
        self.fast_running = False
        self.selected_memory_address: int | None = None

        self.status_var = tk.StringVar(value="No program loaded")
        self.current_instr_var = tk.StringVar(value="-")
        self.channel_var = tk.StringVar(value="0")
        self.rx_input_var = tk.StringVar(value="")
        self.breakpoint_var = tk.StringVar(value="0x00")
        self.edit_target_var = tk.StringVar(value="R0")
        self.edit_value_var = tk.StringVar(value="0x00")
        self.mem_addr_var = tk.StringVar(value="0x00")
        self.mem_value_var = tk.StringVar(value="0x00")
        self.fast_cpu_hz_var = tk.StringVar(value="1000000")
        self.peripheral_audio_rate_var = tk.StringVar(value="16000")
        self.peripheral_type_var = tk.StringVar(value="ps2")
        self.peripheral_name_var = tk.StringVar(value="keyboard0")
        self.peripheral_channel_var = tk.StringVar(value="0x10")
        self.peripheral_rx_depth_var = tk.StringVar(value="32")
        self.peripheral_tx_depth_var = tk.StringVar(value="8")
        self.peripheral_width_var = tk.StringVar(value="8")
        self.peripheral_height_var = tk.StringVar(value="8")
        self.peripheral_stack_depth_var = tk.StringVar(value="32")
        self.peripheral_bytes_var = tk.StringVar(value="")
        self.peripheral_serpentine_var = tk.BooleanVar(value=False)
        self.audio_host_playback_var = tk.BooleanVar(value=False)
        self.ps2_capture_var = tk.BooleanVar(value=False)

        self.field_value_labels: dict[str, tk.Label] = {}
        self.field_base_colors: dict[str, str] = {}
        self.memory_cells: dict[int, tk.Label] = {}
        self.body_pane: ttk.PanedWindow | None = None
        self.left_detail_pane: ttk.PanedWindow | None = None
        self.right_detail_pane: ttk.PanedWindow | None = None
        self.peripheral_listbox: tk.Listbox | None = None
        self.peripheral_state_text: tk.Text | None = None
        self.peripheral_preview_canvas: tk.Canvas | None = None
        self.peripheral_type_frames: dict[str, ttk.Frame] = {}
        self.peripheral_primary_button: ttk.Button | None = None
        self.peripheral_secondary_button: ttk.Button | None = None
        self.peripheral_clear_button: ttk.Button | None = None
        self.ps2_capture_button: ttk.Checkbutton | None = None
        self.peripheral_save_button: ttk.Button | None = None
        self.audio_host_playback_button: ttk.Checkbutton | None = None
        self.audio_host_status_label: ttk.Label | None = None
        self._peripheral_list_channels: list[int] = []
        self.selected_peripheral_channel: int | None = None
        self._ps2_pressed_keys: set[str] = set()
        self._host_audio_enabled_channels: set[int] = set()
        self._slow_run_after_id: str | None = None
        self._fast_run_after_id: str | None = None
        self._fast_run_last_wallclock_s: float | None = None
        self._fast_run_step_credit = 0.0
        self._host_audio = HostAudioPlaybackManager()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind_all("<KeyPress>", self.on_key_press, add="+")
        self.bind_all("<KeyRelease>", self.on_key_release, add="+")
        self.after_idle(self._set_initial_layout)
        if initial_path:
            self._load_path(Path(initial_path))
        else:
            self.refresh_all()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Load ASM", command=self.on_load_asm).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Load BIN", command=self.on_load_bin).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Reset", command=self.on_reset).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Step", command=self.on_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Run", command=self.on_run).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Fast Run", command=self.on_fast_run).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Pause", command=self.on_pause).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(toolbar, text="CPU Hz").pack(side=tk.LEFT)
        ttk.Entry(toolbar, textvariable=self.fast_cpu_hz_var, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(toolbar, text="Breakpoint").pack(side=tk.LEFT)
        ttk.Entry(toolbar, textvariable=self.breakpoint_var, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Toggle BP", command=self.on_toggle_breakpoint).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clear BPs", command=self.on_clear_breakpoints).pack(side=tk.LEFT, padx=2)

        status_bar = ttk.Frame(self, padding=(8, 0, 8, 8))
        status_bar.pack(fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(status_bar, textvariable=self.current_instr_var).pack(side=tk.RIGHT)

        body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.body_pane = body

        left = ttk.Frame(body, padding=6)
        right = ttk.Frame(body, padding=6)
        body.add(left, weight=2)
        body.add(right, weight=3)

        self._build_left_panel(left)
        self._build_right_panel(right)

    def _set_initial_layout(self) -> None:
        if self.body_pane is not None:
            width = self.body_pane.winfo_width()
            if width > 0:
                self.body_pane.sashpos(0, int(width * 0.42))
        if self.left_detail_pane is not None:
            height = self.left_detail_pane.winfo_height()
            if height > 0:
                self.left_detail_pane.sashpos(0, int(height * 0.74))

    def _build_left_panel(self, parent: ttk.Frame) -> None:
        detail_pane = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        detail_pane.pack(fill=tk.BOTH, expand=True)
        self.left_detail_pane = detail_pane

        source_host = ttk.Frame(detail_pane)
        io_host = ttk.Frame(detail_pane)
        detail_pane.add(source_host, weight=4)
        detail_pane.add(io_host, weight=1)

        self._build_source_tabs(source_host)
        self._build_io_frame(io_host)

    def _build_source_tabs(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True)

        source_tab = ttk.Frame(notebook)
        disasm_tab = ttk.Frame(notebook)
        peripherals_tab = ttk.Frame(notebook)
        notebook.add(source_tab, text="Source")
        notebook.add(disasm_tab, text="Disassembly")
        notebook.add(peripherals_tab, text="Peripherals")

        self.source_text = self._make_text_widget(source_tab)
        self.source_text.bind("<Double-Button-1>", self.on_source_double_click)
        self.disasm_text = self._make_text_widget(disasm_tab)
        self.disasm_text.bind("<Double-Button-1>", self.on_disasm_double_click)
        self._build_peripherals_tab(peripherals_tab)

    def _make_text_widget(self, parent: ttk.Frame) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)
        text = tk.Text(frame, wrap="none", font=MONO_FONT, height=30, background="#10161D", foreground="#DDE8F1")
        x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
        y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        text.configure(state=tk.DISABLED)
        self._configure_text_tags(text)
        return text

    def _configure_text_tags(self, text: tk.Text) -> None:
        text.tag_configure("current_line", background="#234C73", foreground="#F6FBFF")
        text.tag_configure("breakpoint_line", background="#5C1B37", foreground="#FFF1F6")
        text.tag_configure("comment", foreground="#6E8AA3")
        text.tag_configure("label", foreground="#FFE08A")
        text.tag_configure("directive", foreground="#FFB28A")
        text.tag_configure("mnemonic", foreground="#9AD1FF")
        text.tag_configure("register", foreground="#B2FFB8")
        text.tag_configure("number", foreground="#FFDD95")
        text.tag_configure("address", foreground="#8FB7D9")
        text.tag_configure("opcode", foreground="#B6C9D9")
        text.tag_configure("symbol", foreground="#D2A8FF")
        text.tag_configure("illegal", foreground="#FF9797")

    def _build_right_panel(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, pady=(0, 8))

        register_root = tk.Frame(top, bg="#10161D")
        register_root.pack(fill=tk.X, pady=(0, 8))
        for group_index, (title, fields, palette) in enumerate(REGISTER_GROUPS):
            frame = self._build_field_group(register_root, title, fields, palette)
            frame.grid(row=group_index // 2, column=group_index % 2, sticky="nsew", padx=4, pady=4)
        register_root.grid_columnconfigure(0, weight=1)
        register_root.grid_columnconfigure(1, weight=1)

        self._build_edit_frame(top)
        self._build_memory_frame(parent)

    def _build_field_group(
        self,
        parent: tk.Frame,
        title: str,
        fields: tuple[str, ...],
        palette: dict[str, str],
    ) -> tk.LabelFrame:
        frame = tk.LabelFrame(
            parent,
            text=title,
            bg=palette["frame"],
            fg=palette["title"],
            font=("TkDefaultFont", 10, "bold"),
            padx=8,
            pady=6,
            bd=1,
        )
        for row, field in enumerate(fields):
            name_label = tk.Label(frame, text=field, bg=palette["frame"], fg=palette["title"], anchor="w", width=9)
            value_label = tk.Label(
                frame,
                text="00",
                bg=palette["frame"],
                fg=palette["text"],
                font=MONO_FONT,
                anchor="w",
                width=12,
                cursor="hand2" if field != "Pending" else "arrow",
            )
            name_label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            value_label.grid(row=row, column=1, sticky="w", pady=2)
            if field != "Pending":
                value_label.bind("<Button-1>", lambda _event, target=field: self.on_select_state_target(target))
            self.field_value_labels[field] = value_label
            self.field_base_colors[field] = palette["frame"]
        return frame

    def _build_edit_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Edit / Breakpoints", padding=8)
        frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame, text="State").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        ttk.Combobox(
            frame,
            textvariable=self.edit_target_var,
            values=["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "PC", "IOSEL", "Z", "C"],
            width=8,
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=2, pady=2)
        ttk.Entry(frame, textvariable=self.edit_value_var, width=10).grid(row=0, column=2, sticky="w", padx=2, pady=2)
        ttk.Button(frame, text="Apply State", command=self.on_apply_state_edit).grid(row=0, column=3, sticky="w", padx=2, pady=2)

        ttk.Label(frame, text="Memory").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(frame, textvariable=self.mem_addr_var, width=10).grid(row=1, column=1, sticky="w", padx=2, pady=2)
        ttk.Entry(frame, textvariable=self.mem_value_var, width=10).grid(row=1, column=2, sticky="w", padx=2, pady=2)
        ttk.Button(frame, text="Apply Memory", command=self.on_apply_memory_edit).grid(row=1, column=3, sticky="w", padx=2, pady=2)

        ttk.Label(frame, text="Breakpoints").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(frame, textvariable=self.breakpoint_var, width=10).grid(row=2, column=1, sticky="w", padx=2, pady=2)
        ttk.Button(frame, text="Toggle", command=self.on_toggle_breakpoint).grid(row=2, column=2, sticky="w", padx=2, pady=2)
        ttk.Button(frame, text="Clear All", command=self.on_clear_breakpoints).grid(row=2, column=3, sticky="w", padx=2, pady=2)

    def _build_memory_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Memory", padding=8)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        legend = ttk.Frame(frame)
        legend.pack(fill=tk.X, pady=(0, 6))
        for label, color in (
            ("Current", MEMORY_COLORS["current_bg"]),
            ("Breakpoint", MEMORY_COLORS["breakpoint_bg"]),
            ("R7", MEMORY_COLORS["pointer_bg"]),
            ("Changed", MEMORY_COLORS["changed_bg"]),
        ):
            swatch = tk.Label(legend, text=label, bg=color, fg="#FFFFFF" if label != "Changed" else "#2A2111", padx=6, pady=2)
            swatch.pack(side=tk.LEFT, padx=4)

        grid = tk.Frame(frame, bg="#10161D")
        grid.pack(fill=tk.BOTH, expand=True)

        tk.Label(grid, text="", bg="#10161D", fg="#7E94A7", width=4).grid(row=0, column=0, padx=1, pady=1)
        for column in range(16):
            tk.Label(grid, text=f"{column:X}", bg="#10161D", fg="#7E94A7", width=4).grid(row=0, column=column + 1, padx=1, pady=1)

        for row in range(16):
            tk.Label(grid, text=f"{row * 16:02X}", bg="#10161D", fg="#7E94A7", width=4).grid(
                row=row + 1, column=0, padx=1, pady=1
            )
            for column in range(16):
                address = row * 16 + column
                cell = tk.Label(
                    grid,
                    text="00",
                    bg=MEMORY_COLORS["default_bg"],
                    fg=MEMORY_COLORS["default_fg"],
                    width=4,
                    relief="ridge",
                    bd=1,
                    font=MONO_FONT_SMALL,
                    cursor="hand2",
                )
                cell.grid(row=row + 1, column=column + 1, padx=1, pady=1, sticky="nsew")
                cell.bind("<Button-1>", lambda _event, addr=address: self.on_select_memory_address(addr))
                self.memory_cells[address] = cell

    def _build_io_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="I/O", padding=8)
        frame.pack(fill=tk.BOTH, expand=True)
        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X, pady=(0, 6))
        controls.grid_columnconfigure(3, weight=1)

        ttk.Label(controls, text="Channel").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(controls, from_=0, to=255, textvariable=self.channel_var, width=6).grid(
            row=0, column=1, sticky="w", padx=(4, 12)
        )
        ttk.Label(controls, text="RX bytes").grid(row=0, column=2, sticky="w")
        ttk.Entry(controls, textvariable=self.rx_input_var).grid(row=0, column=3, sticky="ew", padx=(4, 0))
        ttk.Button(controls, text="Queue RX", command=self.on_queue_rx).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0), padx=(0, 6)
        )
        ttk.Button(controls, text="Drain TX", command=self.on_drain_tx).grid(
            row=1, column=2, columnspan=2, sticky="ew", pady=(6, 0)
        )

        self.io_text = tk.Text(frame, wrap="word", font=MONO_FONT, height=10, background="#10161D", foreground="#DDE8F1")
        self.io_text.pack(fill=tk.BOTH, expand=True)
        self.io_text.configure(state=tk.DISABLED)

    def _build_peripherals_tab(self, parent: ttk.Frame) -> None:
        root = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        root.pack(fill=tk.BOTH, expand=True)

        list_frame = ttk.Frame(root, padding=6)
        detail_frame = ttk.Frame(root, padding=6)
        root.add(list_frame, weight=1)
        root.add(detail_frame, weight=3)

        list_actions = ttk.Frame(list_frame)
        list_actions.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(list_actions, text="New", command=self.on_new_peripheral).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(list_actions, text="Remove", command=self.on_remove_peripheral).pack(side=tk.LEFT)

        config_actions = ttk.Frame(list_frame)
        config_actions.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(config_actions, text="Load Config", command=self.on_load_peripheral_config).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(config_actions, text="Save Config", command=self.on_save_peripheral_config).pack(side=tk.LEFT)

        list_host = ttk.Frame(list_frame)
        list_host.pack(fill=tk.BOTH, expand=True)
        self.peripheral_listbox = tk.Listbox(
            list_host,
            font=MONO_FONT_SMALL,
            activestyle="none",
            background="#10161D",
            foreground="#DDE8F1",
            selectbackground="#285E8E",
            selectforeground="#F7FBFF",
        )
        list_scroll = ttk.Scrollbar(list_host, orient=tk.VERTICAL, command=self.peripheral_listbox.yview)
        self.peripheral_listbox.configure(yscrollcommand=list_scroll.set)
        self.peripheral_listbox.grid(row=0, column=0, sticky="nsew")
        list_scroll.grid(row=0, column=1, sticky="ns")
        list_host.grid_rowconfigure(0, weight=1)
        list_host.grid_columnconfigure(0, weight=1)
        self.peripheral_listbox.bind("<<ListboxSelect>>", self.on_peripheral_select)

        form_frame = ttk.LabelFrame(detail_frame, text="Device Config", padding=8)
        form_frame.pack(fill=tk.X, pady=(0, 8))
        form_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(form_frame, text="Type").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        type_combo = ttk.Combobox(
            form_frame,
            textvariable=self.peripheral_type_var,
            values=["ps2", "audio8", "ws2812", "filo"],
            width=12,
            state="readonly",
        )
        type_combo.grid(row=0, column=1, sticky="w", padx=2, pady=2)
        type_combo.bind("<<ComboboxSelected>>", self.on_peripheral_type_change)

        ttk.Label(form_frame, text="Name").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(form_frame, textvariable=self.peripheral_name_var).grid(row=1, column=1, sticky="ew", padx=2, pady=2)

        ttk.Label(form_frame, text="Channel").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(form_frame, textvariable=self.peripheral_channel_var, width=12).grid(
            row=2, column=1, sticky="w", padx=2, pady=2
        )

        options_host = ttk.Frame(form_frame)
        options_host.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        options_host.grid_columnconfigure(1, weight=1)

        ps2_frame = ttk.Frame(options_host)
        ttk.Label(ps2_frame, text="RX Depth").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(ps2_frame, textvariable=self.peripheral_rx_depth_var, width=12).grid(row=0, column=1, sticky="w", padx=2, pady=2)
        ttk.Label(ps2_frame, text="TX Depth").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(ps2_frame, textvariable=self.peripheral_tx_depth_var, width=12).grid(row=1, column=1, sticky="w", padx=2, pady=2)
        self.peripheral_type_frames["ps2"] = ps2_frame

        audio_frame = ttk.Frame(options_host)
        ttk.Label(audio_frame, text="TX Depth").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(audio_frame, textvariable=self.peripheral_tx_depth_var, width=12).grid(
            row=0, column=1, sticky="w", padx=2, pady=2
        )
        ttk.Label(audio_frame, text="Rate").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(audio_frame, textvariable=self.peripheral_audio_rate_var, width=12).grid(
            row=1, column=1, sticky="w", padx=2, pady=2
        )
        self.peripheral_type_frames["audio8"] = audio_frame

        ws_frame = ttk.Frame(options_host)
        ttk.Label(ws_frame, text="TX Depth").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(ws_frame, textvariable=self.peripheral_tx_depth_var, width=12).grid(row=0, column=1, sticky="w", padx=2, pady=2)
        ttk.Label(ws_frame, text="Width").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(ws_frame, textvariable=self.peripheral_width_var, width=12).grid(row=1, column=1, sticky="w", padx=2, pady=2)
        ttk.Label(ws_frame, text="Height").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(ws_frame, textvariable=self.peripheral_height_var, width=12).grid(row=2, column=1, sticky="w", padx=2, pady=2)
        ttk.Checkbutton(ws_frame, text="Serpentine", variable=self.peripheral_serpentine_var).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=2, pady=2
        )
        self.peripheral_type_frames["ws2812"] = ws_frame

        filo_frame = ttk.Frame(options_host)
        ttk.Label(filo_frame, text="Stack Depth").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(filo_frame, textvariable=self.peripheral_stack_depth_var, width=12).grid(
            row=0, column=1, sticky="w", padx=2, pady=2
        )
        self.peripheral_type_frames["filo"] = filo_frame

        actions = ttk.Frame(form_frame)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.peripheral_save_button = ttk.Button(actions, text="Add Device", command=self.on_save_peripheral)
        self.peripheral_save_button.pack(side=tk.LEFT, padx=(0, 4))
        self.ps2_capture_button = ttk.Checkbutton(
            actions,
            text="Capture Keyboard",
            variable=self.ps2_capture_var,
            command=self.refresh_all,
        )
        self.ps2_capture_button.pack(side=tk.LEFT)

        control_frame = ttk.LabelFrame(detail_frame, text="Live Control", padding=8)
        control_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(control_frame, text="Bytes").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(control_frame, textvariable=self.peripheral_bytes_var).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        control_frame.grid_columnconfigure(1, weight=1)
        self.peripheral_primary_button = ttk.Button(control_frame, text="Inject", command=self.on_peripheral_inject)
        self.peripheral_primary_button.grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        self.peripheral_secondary_button = ttk.Button(control_frame, text="Drain", command=self.on_peripheral_drain)
        self.peripheral_secondary_button.grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        self.peripheral_clear_button = ttk.Button(control_frame, text="Clear State", command=self.on_clear_selected_peripheral)
        self.peripheral_clear_button.grid(row=1, column=2, sticky="ew", padx=2, pady=2)
        self.audio_host_playback_button = ttk.Checkbutton(
            control_frame,
            text="Host Playback",
            variable=self.audio_host_playback_var,
            command=self.on_toggle_audio_host_playback,
        )
        self.audio_host_playback_button.grid(row=2, column=0, sticky="w", padx=2, pady=(6, 2))
        self.audio_host_status_label = ttk.Label(control_frame, text="Host audio off")
        self.audio_host_status_label.grid(row=2, column=1, columnspan=2, sticky="w", padx=2, pady=(6, 2))

        preview_frame = ttk.LabelFrame(detail_frame, text="Live Preview", padding=8)
        preview_frame.pack(fill=tk.BOTH, expand=True)

        self.peripheral_preview_canvas = tk.Canvas(
            preview_frame,
            height=220,
            background="#10161D",
            highlightthickness=0,
        )
        self.peripheral_preview_canvas.pack(fill=tk.X, pady=(0, 8))
        self.peripheral_state_text = tk.Text(
            preview_frame,
            wrap="word",
            font=MONO_FONT_SMALL,
            height=12,
            background="#10161D",
            foreground="#DDE8F1",
        )
        self.peripheral_state_text.pack(fill=tk.BOTH, expand=True)
        self.peripheral_state_text.configure(state=tk.DISABLED)
        self._show_peripheral_type_frame(self.peripheral_type_var.get())

    def on_load_asm(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Min8 Assembly",
            filetypes=[("Min8 assembly", "*.asm *.s *.min8"), ("All files", "*.*")],
        )
        if path:
            self._load_path(Path(path))

    def on_load_bin(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Min8 Binary Image",
            filetypes=[("Binary image", "*.bin"), ("All files", "*.*")],
        )
        if path:
            self._load_path(Path(path))

    def on_reset(self) -> None:
        self._cancel_run_callbacks()
        self.running = False
        self.fast_running = False
        self._ps2_pressed_keys.clear()
        self.session.reset()
        self._restart_host_audio_streams()
        self._sync_host_audio_playback()
        self._set_status("CPU reset")
        self.refresh_all()

    def on_step(self) -> None:
        self._cancel_run_callbacks()
        self.running = False
        self.fast_running = False
        self._run_single_step()

    def on_run(self) -> None:
        try:
            self._cpu_hz()
        except ValueError as exc:
            messagebox.showerror("Invalid CPU Rate", str(exc))
            return
        self._cancel_run_callbacks()
        self.fast_running = False
        self.running = True
        self._set_status("Running")
        self._run_tick()

    def on_fast_run(self) -> None:
        try:
            self._cpu_hz()
        except ValueError as exc:
            messagebox.showerror("Invalid CPU Rate", str(exc))
            return
        self._cancel_run_callbacks()
        self.running = False
        self.fast_running = True
        self._fast_run_last_wallclock_s = time.monotonic()
        self._fast_run_step_credit = 0.0
        self._set_status("Fast running")
        self._run_fast_tick()

    def on_pause(self) -> None:
        self._cancel_run_callbacks()
        self.running = False
        self.fast_running = False
        self._set_status("Paused")

    def on_close(self) -> None:
        self._cancel_run_callbacks()
        self._host_audio.close()
        self.destroy()

    def on_toggle_breakpoint(self) -> None:
        try:
            address = self._parse_byte(self.breakpoint_var.get(), allow_empty=False)
        except ValueError as exc:
            messagebox.showerror("Invalid Breakpoint", str(exc))
            return
        enabled = self.session.toggle_breakpoint(address)
        self._set_status(f"{'Added' if enabled else 'Removed'} breakpoint at 0x{address:02X}")
        self.refresh_all()

    def on_clear_breakpoints(self) -> None:
        self.session.clear_breakpoints()
        self._set_status("Cleared breakpoints")
        self.refresh_all()

    def on_apply_state_edit(self) -> None:
        try:
            value = self._parse_byte(self.edit_value_var.get(), allow_empty=False)
            self.session.edit_state(self.edit_target_var.get(), value)
        except ValueError as exc:
            messagebox.showerror("Invalid State Edit", str(exc))
            return
        self._set_status(f"Updated {self.edit_target_var.get().upper()} to 0x{value:02X}")
        self.refresh_all()

    def on_apply_memory_edit(self) -> None:
        try:
            address = self._parse_byte(self.mem_addr_var.get(), allow_empty=False)
            value = self._parse_byte(self.mem_value_var.get(), allow_empty=False)
            self.session.edit_memory(address, value)
        except ValueError as exc:
            messagebox.showerror("Invalid Memory Edit", str(exc))
            return
        self.selected_memory_address = address
        self._set_status(f"Updated memory[0x{address:02X}] = 0x{value:02X}")
        self.refresh_all()

    def on_queue_rx(self) -> None:
        try:
            channel = self._selected_channel()
            values = self._parse_byte_tokens(self.rx_input_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid RX Bytes", str(exc))
            return
        self.session.queue_rx(channel, values)
        self.rx_input_var.set("")
        self._append_io_log(f"RX[{channel:02X}] <= {self._format_bytes(values)}")
        self.refresh_all()

    def on_drain_tx(self) -> None:
        channel = self._selected_channel()
        values = self.session.drain_tx(channel)
        self._append_io_log(f"TX[{channel:02X}] => {self._format_bytes(values)}")
        self.refresh_all()

    def on_new_peripheral(self) -> None:
        if self.peripheral_listbox is not None:
            self.peripheral_listbox.selection_clear(0, tk.END)
        self.selected_peripheral_channel = None
        self._load_default_peripheral_form(device_type=self.peripheral_type_var.get())
        self.refresh_all()

    def on_remove_peripheral(self) -> None:
        if self.selected_peripheral_channel is None:
            return
        config = self.session.dump_peripheral_config().to_dict()
        config["devices"] = [
            entry for entry in config["devices"] if int(entry["channel"]) != self.selected_peripheral_channel
        ]
        try:
            self.session.load_peripheral_config(config)
        except Exception as exc:
            messagebox.showerror("Remove Peripheral Failed", str(exc))
            return
        removed_channel = self.selected_peripheral_channel
        self.selected_peripheral_channel = None
        self._ps2_pressed_keys.clear()
        self._sync_host_audio_playback()
        self._append_io_log(f"Removed peripheral on channel 0x{removed_channel:02X}")
        self._select_first_peripheral()
        self.refresh_all()

    def on_save_peripheral(self) -> None:
        try:
            entry = self._build_peripheral_entry_from_form()
        except ValueError as exc:
            messagebox.showerror("Invalid Peripheral Config", str(exc))
            return
        config = self.session.dump_peripheral_config().to_dict()
        devices = list(config["devices"])
        if self.selected_peripheral_channel is not None:
            devices = [item for item in devices if int(item["channel"]) != self.selected_peripheral_channel]
        devices.append(entry)
        config["devices"] = devices
        try:
            self.session.load_peripheral_config(config)
        except Exception as exc:
            messagebox.showerror("Save Peripheral Failed", str(exc))
            return
        self.selected_peripheral_channel = int(entry["channel"]) & 0xFF
        self._sync_host_audio_playback()
        self._append_io_log(
            f"Configured {entry['type']} {entry['name']} on channel 0x{self.selected_peripheral_channel:02X}"
        )
        self._select_peripheral_channel(self.selected_peripheral_channel)
        self.refresh_all()

    def on_load_peripheral_config(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Peripheral Config",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self.session.load_peripheral_config(payload)
        except Exception as exc:
            messagebox.showerror("Load Peripheral Config Failed", str(exc))
            return
        self.selected_peripheral_channel = None
        self._ps2_pressed_keys.clear()
        self._restart_host_audio_streams()
        self._sync_host_audio_playback(clear_missing=True)
        self._set_status(f"Loaded peripheral config {path}")
        self._select_first_peripheral()
        self.refresh_all()

    def on_save_peripheral_config(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save Peripheral Config",
            defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        payload = self.session.dump_peripheral_config().to_dict()
        Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self._set_status(f"Saved peripheral config to {path}")

    def on_peripheral_select(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self.peripheral_listbox is None:
            return
        selection = self.peripheral_listbox.curselection()
        if not selection:
            self.selected_peripheral_channel = None
            self.refresh_all()
            return
        index = int(selection[0])
        if not 0 <= index < len(self._peripheral_list_channels):
            return
        self.selected_peripheral_channel = self._peripheral_list_channels[index]
        device = self.session.io.get_device(self.selected_peripheral_channel)
        if device is not None:
            self._populate_peripheral_form(device)
        self.refresh_all()

    def on_peripheral_type_change(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self._show_peripheral_type_frame(self.peripheral_type_var.get())
        if self.selected_peripheral_channel is None:
            self.peripheral_name_var.set(self._default_peripheral_name(self.peripheral_type_var.get()))
        self.refresh_all()

    def on_peripheral_inject(self) -> None:
        device = self._selected_peripheral_device()
        if device is None:
            return
        if not isinstance(device, (PS2KeyboardDevice, FILOStackDevice)):
            return
        try:
            values = self._parse_byte_tokens(self.peripheral_bytes_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid Peripheral Bytes", str(exc))
            return
        self.session.queue_rx(device.channel, values)
        self.peripheral_bytes_var.set("")
        label = "PS2" if isinstance(device, PS2KeyboardDevice) else "FILO"
        self._append_io_log(f"{label}[{device.channel:02X}] <= {self._format_bytes(values)}")
        self.refresh_all()

    def on_peripheral_drain(self) -> None:
        device = self._selected_peripheral_device()
        if device is None:
            return
        values = self.session.drain_tx(device.channel)
        if isinstance(device, PS2KeyboardDevice):
            label = "PS2 CMD"
        elif isinstance(device, AudioOutputDevice):
            label = "AUDIO BUF"
        elif isinstance(device, WS2812Device):
            label = "WS2812 BUF"
        else:
            label = "DRAIN"
        self._append_io_log(f"{label}[{device.channel:02X}] => {self._format_bytes(values)}")
        self.refresh_all()

    def on_clear_selected_peripheral(self) -> None:
        device = self._selected_peripheral_device()
        if device is None:
            return
        device.clear()
        self._ps2_pressed_keys.clear()
        self._append_io_log(f"CLEARED[{device.channel:02X}] {device.device_type}")
        self.refresh_all()

    def on_toggle_audio_host_playback(self) -> None:
        device = self._selected_peripheral_device()
        if not isinstance(device, AudioOutputDevice):
            self.audio_host_playback_var.set(False)
            return
        if self.audio_host_playback_var.get():
            device.set_output_tap_enabled(True)
            if self._host_audio.ensure_stream(device.channel, device.sample_rate_hz):
                self._host_audio_enabled_channels.add(device.channel)
                self._set_status(f"Host audio enabled on 0x{device.channel:02X}")
            else:
                device.set_output_tap_enabled(False)
                self._host_audio_enabled_channels.discard(device.channel)
                self.audio_host_playback_var.set(False)
                self._set_status(f"Host audio unavailable on 0x{device.channel:02X}")
        else:
            device.set_output_tap_enabled(False)
            self._host_audio_enabled_channels.discard(device.channel)
            self._host_audio.disable_stream(device.channel)
            self._set_status(f"Host audio disabled on 0x{device.channel:02X}")
        self.refresh_all()

    def on_key_press(self, event: tk.Event[tk.Misc]) -> str | None:
        return self._handle_ps2_key_event(event, pressed=True)

    def on_key_release(self, event: tk.Event[tk.Misc]) -> str | None:
        return self._handle_ps2_key_event(event, pressed=False)

    def on_source_double_click(self, event: tk.Event[tk.Misc]) -> None:
        index = self.source_text.index(f"@{event.x},{event.y}")
        line_number = int(index.split(".", 1)[0])
        address = self.session.source_address_for_line(line_number)
        if address is None:
            return
        self.breakpoint_var.set(f"0x{address:02X}")
        self.on_toggle_breakpoint()

    def on_disasm_double_click(self, event: tk.Event[tk.Misc]) -> None:
        index = self.disasm_text.index(f"@{event.x},{event.y}")
        line_number = int(index.split(".", 1)[0])
        address = self.session.disassembly_address_for_line(line_number)
        if address is None:
            return
        self.breakpoint_var.set(f"0x{address:02X}")
        self.on_toggle_breakpoint()

    def on_select_state_target(self, target: str) -> None:
        self.edit_target_var.set(target)
        value = self._field_value_for_target(target)
        if value is not None:
            self.edit_value_var.set(f"0x{value:02X}" if target not in {"Z", "C"} else str(value))

    def on_select_memory_address(self, address: int) -> None:
        self.selected_memory_address = address & 0xFF
        self.mem_addr_var.set(f"0x{address:02X}")
        self.mem_value_var.set(f"0x{self.session.cpu.state.memory[address & 0xFF]:02X}")
        self.breakpoint_var.set(f"0x{address:02X}")
        self.refresh_all()

    def _load_path(self, path: Path) -> None:
        try:
            if path.suffix.lower() == ".bin":
                self.session.load_image_file(path)
            else:
                self.session.load_assembly_file(path)
        except Exception as exc:
            messagebox.showerror("Load Failed", str(exc))
            return
        self._cancel_run_callbacks()
        self.running = False
        self.fast_running = False
        self._restart_host_audio_streams()
        self._sync_host_audio_playback()
        self.title(f"Min8 GUI Simulator - {path.name}")
        self._set_status(f"Loaded {path}")
        self.refresh_all()

    def _run_single_step(self) -> None:
        try:
            result = self.session.step()
        except (IllegalInstruction, MachineHalted) as exc:
            self._set_status(str(exc))
            self.refresh_all()
            return
        self._advance_observed_io(result)
        self._handle_result(result)

    def _run_tick(self) -> None:
        self._slow_run_after_id = None
        if not self.running:
            return
        try:
            sim_cpu_hz = self._cpu_hz()
        except ValueError as exc:
            self.running = False
            messagebox.showerror("Invalid CPU Rate", str(exc))
            self._set_status("Paused")
            self.refresh_all()
            return

        last_result: StepResult | None = None
        made_progress = False
        unresolved_block = False
        for _ in range(SLOW_RUN_FRAME_BATCHES):
            try:
                results = self.session.run_batch(max_steps=SLOW_RUN_BATCH_STEPS)
            except (IllegalInstruction, MachineHalted) as exc:
                self.running = False
                self._set_status(str(exc))
                self.refresh_all()
                return

            if results:
                made_progress = True
                last_result = results[-1]
                self._advance_simulated_io(results, sim_cpu_hz)

            if self.session.last_stop_reason == "blocked" and last_result is not None and last_result.blocked_on is not None:
                if self._resume_time_driven_output(last_result.blocked_on.channel, last_result.blocked_on.direction):
                    continue
                unresolved_block = True
                break

            if self.session.last_stop_reason != "max_steps":
                break

        if unresolved_block and last_result is not None:
            self._handle_result(last_result, refresh=False)
        elif self.session.last_stop_reason in {"breakpoint", "max_steps"}:
            self._handle_stop_without_step()
        elif last_result is not None:
            self._handle_result(last_result, refresh=False)
        elif not made_progress:
            self._handle_stop_without_step()

        if self.session.last_stop_reason in {"breakpoint", "halted", "error"}:
            self.running = False
        elif unresolved_block:
            self.running = False

        self.refresh_all()
        if self.running:
            self._schedule_slow_run_tick()

    def _run_fast_tick(self) -> None:
        self._fast_run_after_id = None
        if not self.fast_running:
            return
        try:
            cpu_hz = self._cpu_hz()
        except ValueError as exc:
            self.fast_running = False
            messagebox.showerror("Invalid CPU Rate", str(exc))
            self._set_status("Paused")
            self.refresh_all()
            return

        elapsed_s = self._advance_fast_wallclock_io()
        step_budget = self._accrue_fast_step_budget(cpu_hz, elapsed_s)
        if step_budget <= 0:
            self._schedule_fast_run_tick()
            return

        last_result: StepResult | None = None
        remaining_budget = step_budget
        while remaining_budget > 0:
            batch_budget = min(FAST_RUN_BATCH_STEPS, remaining_budget)
            try:
                results = self.session.run_batch(max_steps=batch_budget)
            except (IllegalInstruction, MachineHalted) as exc:
                self.fast_running = False
                self._set_status(str(exc))
                self.refresh_all()
                return

            retired_count = sum(1 for result in results if result.retired)
            remaining_budget = max(0, remaining_budget - retired_count)
            if results:
                last_result = results[-1]

            if self.session.last_stop_reason != "max_steps":
                break

        if self.session.last_stop_reason == "max_steps":
            self._schedule_fast_run_tick()
            return

        if (
            self.session.last_stop_reason == "blocked"
            and last_result is not None
            and last_result.blocked_on is not None
            and self._is_time_driven_output_block(last_result.blocked_on.channel, last_result.blocked_on.direction)
        ):
            self._schedule_fast_run_tick()
            return

        self.fast_running = False
        if last_result is not None:
            self._handle_result(last_result, refresh=False)
        else:
            self._handle_stop_without_step()
        self.refresh_all()

    def _handle_result(self, result: StepResult, *, refresh: bool = True) -> None:
        if result.status == "blocked" and result.blocked_on is not None:
            self._set_status(f"Blocked on {result.blocked_on.direction} channel 0x{result.blocked_on.channel:02X}")
        elif result.status == "halted":
            self._set_status("Program halted")
        else:
            self._set_status(f"Executed {result.instruction_text}")
        if result.io_transfer is not None:
            self._append_io_log(
                f"{result.io_transfer.direction.upper()}[{result.io_transfer.channel:02X}] {self._format_bytes([result.io_transfer.value or 0])}"
            )
        if refresh:
            self.refresh_all()

    def _handle_stop_without_step(self) -> None:
        if self.session.last_stop_reason == "breakpoint" and self.session.last_stop_address is not None:
            self._set_status(f"Breakpoint at 0x{self.session.last_stop_address:02X}")
        elif self.session.last_stop_reason == "max_steps":
            self._set_status("Running")

    def refresh_all(self) -> None:
        self._refresh_registers()
        self._refresh_source_text()
        self._refresh_disassembly_text()
        self._refresh_memory()
        self._refresh_current_instruction()
        self._refresh_peripherals()

    def _refresh_registers(self) -> None:
        values = {
            **{f"R{i}": self.session.cpu.state.registers[i] for i in range(8)},
            "PC": self.session.cpu.state.pc,
            "IOSEL": self.session.cpu.state.iosel,
            "Z": self.session.cpu.state.z,
            "C": self.session.cpu.state.c,
            "Pending": self.session.cpu.state.pending.pc_before if self.session.cpu.state.pending is not None else None,
        }
        for field, label in self.field_value_labels.items():
            value = values[field]
            text = "-" if value is None else (str(value) if field in {"Z", "C"} else f"0x{value:02X}")
            label.configure(text=text)

            base_color = self.field_base_colors[field]
            bg = base_color
            fg = "#EAF6FF"
            if field.startswith("R"):
                if int(field[1:]) in self.session.last_register_changes:
                    bg, fg = "#F4D35E", "#201A0E"
            elif field in self.session.last_special_changes:
                bg, fg = "#F4D35E", "#201A0E"
            elif field == "Pending" and self.session.cpu.state.pending is not None:
                bg, fg = "#6D5A2B", "#FFF4D7"
            label.configure(bg=bg, fg=fg)

    def _refresh_source_text(self) -> None:
        self._render_text_widget(
            widget=self.source_text,
            text=self.session.source_text,
            current_line=self.session.source_line_for_address(self.session.current_address),
            breakpoint_lines={
                line
                for line in (self.session.source_line_for_address(address) for address in self.session.breakpoints)
                if line is not None
            },
            syntax_mode="source",
        )

    def _refresh_disassembly_text(self) -> None:
        self._render_text_widget(
            widget=self.disasm_text,
            text=self.session.disassembly_text,
            current_line=self.session.disassembly_line_for_address(self.session.current_address),
            breakpoint_lines={
                line
                for line in (self.session.disassembly_line_for_address(address) for address in self.session.breakpoints)
                if line is not None
            },
            syntax_mode="disasm",
        )

    def _render_text_widget(
        self,
        *,
        widget: tk.Text,
        text: str,
        current_line: int | None,
        breakpoint_lines: set[int],
        syntax_mode: str,
    ) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        for tag in widget.tag_names():
            if tag not in {
                "current_line",
                "breakpoint_line",
                "comment",
                "label",
                "directive",
                "mnemonic",
                "register",
                "number",
                "address",
                "opcode",
                "symbol",
                "illegal",
            }:
                continue
            widget.tag_remove(tag, "1.0", tk.END)
        if syntax_mode == "source":
            self._highlight_source(widget, text)
        else:
            self._highlight_disassembly(widget, text)

        for line_number in breakpoint_lines:
            widget.tag_add("breakpoint_line", f"{line_number}.0", f"{line_number}.end")
        if current_line is not None:
            widget.tag_add("current_line", f"{current_line}.0", f"{current_line}.end")
            widget.see(f"{current_line}.0")

        widget.tag_raise("breakpoint_line")
        widget.tag_raise("current_line")
        widget.configure(state=tk.DISABLED)

    def _highlight_source(self, widget: tk.Text, text: str) -> None:
        for line_number, line in enumerate(text.splitlines(), start=1):
            comment_index = line.find(";")
            code = line if comment_index < 0 else line[:comment_index]
            if comment_index >= 0:
                widget.tag_add("comment", f"{line_number}.{comment_index}", f"{line_number}.end")

            label_match = LABEL_RE.match(code)
            code_offset = 0
            if label_match is not None:
                widget.tag_add("label", f"{line_number}.{label_match.start(1)}", f"{line_number}.{label_match.end(1)}")
                code_offset = label_match.end(1)

            token_match = TOKEN_RE.search(code, pos=code_offset)
            if token_match is not None:
                tag = "directive" if token_match.group(0).startswith(".") else "mnemonic"
                widget.tag_add(tag, f"{line_number}.{token_match.start()}", f"{line_number}.{token_match.end()}")

            for match in REGISTER_RE.finditer(code):
                widget.tag_add("register", f"{line_number}.{match.start()}", f"{line_number}.{match.end()}")
            for match in SOURCE_NUMBER_RE.finditer(code):
                widget.tag_add("number", f"{line_number}.{match.start()}", f"{line_number}.{match.end()}")

    def _highlight_disassembly(self, widget: tk.Text, text: str) -> None:
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = DISASM_LINE_RE.match(line)
            if match is None:
                continue
            widget.tag_add("address", f"{line_number}.0", f"{line_number}.{len(match.group(1))}")
            widget.tag_add("opcode", f"{line_number}.4", f"{line_number}.6")

            instruction_text = match.group(3)
            mnemonic = instruction_text.strip().split(None, 1)[0] if instruction_text.strip() else ""
            mnemonic_start = line.find(mnemonic, 7)
            if mnemonic:
                widget.tag_add("mnemonic", f"{line_number}.{mnemonic_start}", f"{line_number}.{mnemonic_start + len(mnemonic)}")
                if mnemonic == ".byte":
                    widget.tag_add("illegal", f"{line_number}.{mnemonic_start}", f"{line_number}.end")

            for reg_match in REGISTER_RE.finditer(line):
                widget.tag_add("register", f"{line_number}.{reg_match.start()}", f"{line_number}.{reg_match.end()}")
            for num_match in SOURCE_NUMBER_RE.finditer(line):
                widget.tag_add("number", f"{line_number}.{num_match.start()}", f"{line_number}.{num_match.end()}")

            comment_index = line.find(";")
            if comment_index >= 0:
                widget.tag_add("comment", f"{line_number}.{comment_index}", f"{line_number}.end")
                if comment_index + 2 < len(line):
                    widget.tag_add("symbol", f"{line_number}.{comment_index + 2}", f"{line_number}.end")

    def _refresh_memory(self) -> None:
        current = self.session.current_address
        pointer = self.session.cpu.state.registers[7]
        for address, label in self.memory_cells.items():
            value = self.session.cpu.state.memory[address]
            bg = MEMORY_COLORS["default_bg"]
            fg = MEMORY_COLORS["default_fg"]
            relief = "ridge"
            if address == self.selected_memory_address:
                bg, fg = MEMORY_COLORS["selected_bg"], MEMORY_COLORS["selected_fg"]
            if address in self.session.breakpoints:
                bg, fg = MEMORY_COLORS["breakpoint_bg"], MEMORY_COLORS["breakpoint_fg"]
            if address == pointer:
                bg, fg = MEMORY_COLORS["pointer_bg"], MEMORY_COLORS["pointer_fg"]
            if address == current:
                bg, fg = MEMORY_COLORS["current_bg"], MEMORY_COLORS["current_fg"]
                relief = "solid"
            if address in self.session.last_memory_changes:
                bg, fg = MEMORY_COLORS["changed_bg"], MEMORY_COLORS["changed_fg"]
                relief = "sunken"
            label.configure(text=f"{value:02X}", bg=bg, fg=fg, relief=relief)

    def _refresh_current_instruction(self) -> None:
        current = self.session.current_address
        pending = self.session.cpu.state.pending
        if pending is not None:
            self.current_instr_var.set(f"Pending @ 0x{current:02X}: {pending.decoded.instruction_text}")
            return
        if self.session.last_result is not None and self.session.last_result.status == "halted":
            self.current_instr_var.set(f"HALT @ 0x{current:02X}")
            return
        opcode = self.session.cpu.state.memory[current]
        try:
            text = decode_opcode(opcode, pc=current).instruction_text
        except IllegalInstruction:
            text = f".byte 0x{opcode:02X} ; illegal"
        self.current_instr_var.set(f"PC @ 0x{current:02X}: {text}")

    def _append_io_log(self, message: str) -> None:
        self.io_text.configure(state=tk.NORMAL)
        self.io_text.insert(tk.END, message + "\n")
        self.io_text.see(tk.END)
        self.io_text.configure(state=tk.DISABLED)

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _selected_channel(self) -> int:
        return int(self.channel_var.get(), 0) & 0xFF

    def _selected_peripheral_device(self) -> PS2KeyboardDevice | AudioOutputDevice | WS2812Device | FILOStackDevice | None:
        if self.selected_peripheral_channel is None:
            return None
        device = self.session.io.get_device(self.selected_peripheral_channel)
        if isinstance(device, (PS2KeyboardDevice, AudioOutputDevice, WS2812Device, FILOStackDevice)):
            return device
        return None

    def _refresh_peripherals(self) -> None:
        self._refresh_peripheral_list()
        self._refresh_peripheral_controls()
        self._refresh_peripheral_state()

    def _refresh_peripheral_list(self) -> None:
        if self.peripheral_listbox is None:
            return
        devices = list(self.session.io.devices())
        self._peripheral_list_channels = [device.channel for device in devices]
        selected_channel = self.selected_peripheral_channel
        self.peripheral_listbox.delete(0, tk.END)
        for device in devices:
            label = f"0x{device.channel:02X}  {device.device_type:<7}  {device.name}"
            self.peripheral_listbox.insert(tk.END, label)
        if selected_channel is not None and selected_channel in self._peripheral_list_channels:
            self._select_peripheral_channel(selected_channel)

    def _refresh_peripheral_controls(self) -> None:
        device = self._selected_peripheral_device()
        is_ps2 = isinstance(device, PS2KeyboardDevice)
        is_audio = isinstance(device, AudioOutputDevice)
        supports_inject = isinstance(device, (PS2KeyboardDevice, FILOStackDevice))
        supports_drain = isinstance(device, (PS2KeyboardDevice, AudioOutputDevice, WS2812Device))

        if self.peripheral_save_button is not None:
            self.peripheral_save_button.configure(text="Update Device" if device is not None else "Add Device")
        if self.peripheral_primary_button is not None:
            self.peripheral_primary_button.configure(
                text="Inject RX" if is_ps2 else ("Push Bytes" if isinstance(device, FILOStackDevice) else "Inject"),
                state=tk.NORMAL if supports_inject else tk.DISABLED,
            )
        if self.peripheral_secondary_button is not None:
            self.peripheral_secondary_button.configure(
                text="Drain Cmds"
                if is_ps2
                else ("Drain Buffer" if isinstance(device, (AudioOutputDevice, WS2812Device)) else "Drain"),
                state=tk.NORMAL if supports_drain else tk.DISABLED,
            )
        if self.peripheral_clear_button is not None:
            self.peripheral_clear_button.configure(state=tk.NORMAL if device is not None else tk.DISABLED)
        if self.ps2_capture_button is not None:
            self.ps2_capture_button.configure(state=tk.NORMAL if is_ps2 else tk.DISABLED)
        if self.audio_host_playback_button is not None:
            self.audio_host_playback_var.set(bool(is_audio and device.channel in self._host_audio_enabled_channels))
            self.audio_host_playback_button.configure(state=tk.NORMAL if is_audio else tk.DISABLED)
        if self.audio_host_status_label is not None:
            if is_audio:
                self.audio_host_status_label.configure(text=f"Host audio: {self._host_audio.describe(device.channel)}")
            else:
                backend = self._host_audio.backend_name or "unavailable"
                self.audio_host_status_label.configure(text=f"Host audio: {backend}")
        if not is_ps2 and self.ps2_capture_var.get():
            self.ps2_capture_var.set(False)

    def _refresh_peripheral_state(self) -> None:
        if self.peripheral_state_text is None or self.peripheral_preview_canvas is None:
            return
        device = self._selected_peripheral_device()
        if device is None:
            self._set_text_widget(self.peripheral_state_text, "No configured peripheral selected.\n")
            self._draw_empty_preview("No peripheral selected")
            return
        snapshot = device.snapshot()
        if isinstance(device, AudioOutputDevice):
            snapshot = dict(snapshot)
            snapshot["host_audio_status"] = self._host_audio.describe(device.channel)
        rendered = pprint.pformat(snapshot, width=100, compact=False, sort_dicts=False)
        self._set_text_widget(self.peripheral_state_text, rendered + "\n")
        self._draw_peripheral_preview(device, snapshot)

    def _set_text_widget(self, widget: tk.Text, text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state=tk.DISABLED)

    def _draw_empty_preview(self, message: str) -> None:
        if self.peripheral_preview_canvas is None:
            return
        canvas = self.peripheral_preview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        canvas.create_rectangle(0, 0, width, height, fill="#10161D", outline="")
        canvas.create_text(width / 2, height / 2, text=message, fill="#8FB7D9", font=("TkDefaultFont", 12))

    def _draw_peripheral_preview(self, device: object, snapshot: dict[str, object]) -> None:
        if self.peripheral_preview_canvas is None:
            return
        if isinstance(device, WS2812Device):
            self._draw_ws2812_preview(snapshot)
        elif isinstance(device, AudioOutputDevice):
            self._draw_audio_preview(snapshot)
        elif isinstance(device, FILOStackDevice):
            self._draw_filo_preview(snapshot)
        elif isinstance(device, PS2KeyboardDevice):
            self._draw_ps2_preview(snapshot)
        else:
            self._draw_empty_preview("Unsupported preview")

    def _draw_ws2812_preview(self, snapshot: dict[str, object]) -> None:
        if self.peripheral_preview_canvas is None:
            return
        canvas = self.peripheral_preview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        canvas.create_rectangle(0, 0, width, height, fill="#10161D", outline="")
        matrix = snapshot.get("matrix", ())
        if not matrix:
            self._draw_empty_preview("No LED matrix")
            return
        rows = len(matrix)
        cols = len(matrix[0]) if rows else 0
        if cols == 0:
            self._draw_empty_preview("No LED matrix")
            return
        margin = 16
        cell = min((width - margin * 2) / max(cols, 1), (height - margin * 2) / max(rows, 1))
        for row_index, row in enumerate(matrix):
            for col_index, pixel in enumerate(row):
                x0 = margin + col_index * cell
                y0 = margin + row_index * cell
                x1 = x0 + cell - 4
                y1 = y0 + cell - 4
                r, g, b = pixel
                canvas.create_rectangle(
                    x0,
                    y0,
                    x1,
                    y1,
                    fill=f"#{r:02X}{g:02X}{b:02X}",
                    outline="#202830",
                )
        canvas.create_text(12, 12, anchor="nw", text=f"{cols}x{rows}  frames={snapshot.get('frame_count', 0)}", fill="#DDE8F1")

    def _draw_audio_preview(self, snapshot: dict[str, object]) -> None:
        if self.peripheral_preview_canvas is None:
            return
        canvas = self.peripheral_preview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        canvas.create_rectangle(0, 0, width, height, fill="#10161D", outline="")
        sample_rate_hz = max(1, int(snapshot.get("sample_rate_hz", 16_000)))
        recent_samples = list(snapshot.get("recent_samples", []))[-128:]
        plot_left = 24
        plot_right = width - 16
        plot_top = 28
        plot_bottom = height - 32
        plot_width = max(1, plot_right - plot_left)
        plot_height = max(1, plot_bottom - plot_top)
        center_y = plot_top + plot_height / 2
        canvas.create_line(plot_left, center_y, plot_right, center_y, fill="#243B53")
        canvas.create_line(plot_left, plot_bottom, plot_right, plot_bottom, fill="#243B53")
        if len(recent_samples) < 2:
            canvas.create_text(
                width / 2,
                height / 2,
                text="No waveform yet",
                fill="#8FB7D9",
                font=("TkDefaultFont", 12),
            )
            return
        span_ms = (len(recent_samples) * 1000.0) / sample_rate_hz
        tick_ms = self._audio_preview_tick_ms(span_ms)
        tick_count = int(span_ms / tick_ms) + 1
        for tick_index in range(tick_count + 1):
            tick_ms_value = min(span_ms, tick_index * tick_ms)
            x = plot_left + plot_width * (tick_ms_value / max(span_ms, 1e-9))
            canvas.create_line(x, plot_top, x, plot_bottom, fill="#182532")
            if tick_index < tick_count:
                canvas.create_text(
                    x,
                    plot_bottom + 14,
                    text=f"{tick_ms_value:.0f} ms",
                    fill="#8FB7D9",
                    font=("TkDefaultFont", 9),
                )
        points: list[float] = []
        for index, sample in enumerate(recent_samples):
            x = plot_left + plot_width * index / max(len(recent_samples) - 1, 1)
            y = plot_top + plot_height * (1 - (int(sample) / 255))
            points.extend([x, y])
        canvas.create_line(*points, fill="#F4D35E", width=2, smooth=True)
        canvas.create_text(
            12,
            12,
            anchor="nw",
            text=(
                f"played={snapshot.get('samples_played', 0)} "
                f"underflow={snapshot.get('underflow_count', 0)} "
                f"span={span_ms:.1f} ms"
            ),
            fill="#DDE8F1",
        )
        host_status = str(snapshot.get("host_audio_status", ""))
        if host_status:
            canvas.create_text(width - 12, 12, anchor="ne", text=host_status, fill="#8FB7D9", font=("TkDefaultFont", 9))

    def _draw_filo_preview(self, snapshot: dict[str, object]) -> None:
        if self.peripheral_preview_canvas is None:
            return
        canvas = self.peripheral_preview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        canvas.create_rectangle(0, 0, width, height, fill="#10161D", outline="")
        stack = list(snapshot.get("stack", ()))
        canvas.create_text(12, 12, anchor="nw", text=f"depth={len(stack)}/{snapshot.get('depth', 0)}", fill="#DDE8F1")
        if not stack:
            canvas.create_text(width / 2, height / 2, text="Stack empty", fill="#8FB7D9", font=("TkDefaultFont", 12))
            return
        bar_height = min(28, (height - 40) / max(len(stack), 1))
        for index, value in enumerate(reversed(stack[-8:])):
            y1 = height - 16 - index * bar_height
            y0 = y1 - bar_height + 4
            canvas.create_rectangle(24, y0, width - 24, y1, fill="#2A6A46", outline="#DCFBEA")
            canvas.create_text(width / 2, (y0 + y1) / 2, text=f"0x{value:02X}", fill="#F3FFF7", font=MONO_FONT_SMALL)

    def _draw_ps2_preview(self, snapshot: dict[str, object]) -> None:
        if self.peripheral_preview_canvas is None:
            return
        canvas = self.peripheral_preview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        canvas.create_rectangle(0, 0, width, height, fill="#10161D", outline="")
        rx_queue = list(snapshot.get("rx_queue", []))
        cmd_queue = list(snapshot.get("command_queue", []))
        canvas.create_text(12, 12, anchor="nw", text=f"rx={len(rx_queue)} cmds={len(cmd_queue)}", fill="#DDE8F1")
        canvas.create_text(
            24,
            52,
            anchor="nw",
            text=f"RX: {' '.join(f'{value:02X}' for value in rx_queue[:16]) or '(empty)'}",
            fill="#B2FFB8",
            font=MONO_FONT_SMALL,
        )
        canvas.create_text(
            24,
            84,
            anchor="nw",
            text=f"CMD: {' '.join(f'{value:02X}' for value in cmd_queue[:16]) or '(empty)'}",
            fill="#FFDD95",
            font=MONO_FONT_SMALL,
        )
        capture_text = "capture on" if self.ps2_capture_var.get() else "capture off"
        canvas.create_text(24, 116, anchor="nw", text=capture_text, fill="#8FB7D9", font=("TkDefaultFont", 11))

    def _build_peripheral_entry_from_form(self) -> dict[str, object]:
        device_type = self.peripheral_type_var.get().strip().lower()
        if device_type not in {"ps2", "audio8", "ws2812", "filo"}:
            raise ValueError(f"Unknown peripheral type {device_type!r}")
        name = self.peripheral_name_var.get().strip()
        if not name:
            raise ValueError("peripheral name is required")
        channel = self._parse_byte(self.peripheral_channel_var.get(), allow_empty=False)
        entry: dict[str, object] = {
            "type": device_type,
            "name": name,
            "channel": channel,
        }
        if device_type == "ps2":
            entry["rx_depth"] = self._parse_positive_int(self.peripheral_rx_depth_var.get(), "RX depth")
            entry["tx_depth"] = self._parse_positive_int(self.peripheral_tx_depth_var.get(), "TX depth")
        elif device_type == "audio8":
            entry["tx_depth"] = self._parse_positive_int(self.peripheral_tx_depth_var.get(), "TX depth")
            entry["sample_rate_hz"] = self._parse_positive_int(self.peripheral_audio_rate_var.get(), "Sample rate")
        elif device_type == "ws2812":
            entry["tx_depth"] = self._parse_positive_int(self.peripheral_tx_depth_var.get(), "TX depth")
            entry["width"] = self._parse_positive_int(self.peripheral_width_var.get(), "Width")
            entry["height"] = self._parse_positive_int(self.peripheral_height_var.get(), "Height")
            entry["color_order"] = "GRB"
            entry["serpentine"] = bool(self.peripheral_serpentine_var.get())
        elif device_type == "filo":
            entry["depth"] = self._parse_positive_int(self.peripheral_stack_depth_var.get(), "Stack depth")
        return entry

    def _populate_peripheral_form(self, device: object) -> None:
        if isinstance(device, PS2KeyboardDevice):
            self.peripheral_type_var.set("ps2")
            self.peripheral_name_var.set(device.name)
            self.peripheral_channel_var.set(f"0x{device.channel:02X}")
            self.peripheral_rx_depth_var.set(str(device.rx_capacity))
            self.peripheral_tx_depth_var.set(str(device.tx_capacity))
        elif isinstance(device, AudioOutputDevice):
            self.peripheral_type_var.set("audio8")
            self.peripheral_name_var.set(device.name)
            self.peripheral_channel_var.set(f"0x{device.channel:02X}")
            self.peripheral_tx_depth_var.set(str(device.tx_capacity))
            self.peripheral_audio_rate_var.set(str(device.sample_rate_hz))
        elif isinstance(device, WS2812Device):
            self.peripheral_type_var.set("ws2812")
            self.peripheral_name_var.set(device.name)
            self.peripheral_channel_var.set(f"0x{device.channel:02X}")
            self.peripheral_tx_depth_var.set(str(device.tx_capacity))
            self.peripheral_width_var.set(str(device.width))
            self.peripheral_height_var.set(str(device.height))
            self.peripheral_serpentine_var.set(device.serpentine)
        elif isinstance(device, FILOStackDevice):
            self.peripheral_type_var.set("filo")
            self.peripheral_name_var.set(device.name)
            self.peripheral_channel_var.set(f"0x{device.channel:02X}")
            self.peripheral_stack_depth_var.set(str(device.capacity))
        self._show_peripheral_type_frame(self.peripheral_type_var.get())

    def _show_peripheral_type_frame(self, device_type: str) -> None:
        for key, frame in self.peripheral_type_frames.items():
            if key == device_type:
                frame.grid(row=0, column=0, sticky="w")
            else:
                frame.grid_forget()

    def _load_default_peripheral_form(self, *, device_type: str) -> None:
        defaults = {
            "ps2": ("keyboard0", "0x10"),
            "audio8": ("audio0", "0x11"),
            "ws2812": ("leds0", "0x12"),
            "filo": ("stack0", "0x13"),
        }
        name, channel = defaults.get(device_type, ("device0", f"0x{self._first_free_channel():02X}"))
        self.peripheral_type_var.set(device_type)
        self.peripheral_name_var.set(self._default_peripheral_name(device_type, fallback=name))
        self.peripheral_channel_var.set(f"0x{self._first_free_channel(start=int(channel, 0)):02X}")
        self.peripheral_rx_depth_var.set("32")
        self.peripheral_tx_depth_var.set("8" if device_type == "ps2" else ("1024" if device_type == "audio8" else "192"))
        self.peripheral_audio_rate_var.set("16000")
        self.peripheral_width_var.set("8")
        self.peripheral_height_var.set("8")
        self.peripheral_stack_depth_var.set("32")
        self.peripheral_serpentine_var.set(False)
        self._show_peripheral_type_frame(device_type)

    def _default_peripheral_name(self, device_type: str, *, fallback: str | None = None) -> str:
        existing = {device.name for device in self.session.io.devices()}
        base = fallback or {
            "ps2": "keyboard",
            "audio8": "audio",
            "ws2812": "leds",
            "filo": "stack",
        }.get(device_type, "device")
        if base not in existing:
            return base
        index = 0
        while True:
            candidate = f"{base}{index}"
            if candidate not in existing:
                return candidate
            index += 1

    def _first_free_channel(self, *, start: int = 0x10) -> int:
        used = {device.channel for device in self.session.io.devices()}
        for offset in range(256):
            channel = (start + offset) & 0xFF
            if channel not in used:
                return channel
        return start & 0xFF

    def _select_first_peripheral(self) -> None:
        devices = list(self.session.io.devices())
        if not devices:
            self._load_default_peripheral_form(device_type=self.peripheral_type_var.get())
            return
        self.selected_peripheral_channel = devices[0].channel
        self._populate_peripheral_form(devices[0])

    def _select_peripheral_channel(self, channel: int) -> None:
        if self.peripheral_listbox is None:
            return
        if channel not in self._peripheral_list_channels:
            return
        index = self._peripheral_list_channels.index(channel)
        self.peripheral_listbox.selection_clear(0, tk.END)
        self.peripheral_listbox.selection_set(index)
        self.peripheral_listbox.activate(index)
        self.peripheral_listbox.see(index)

    def _advance_observed_io(self, result: StepResult) -> None:
        transfer = result.io_transfer
        if transfer is None or transfer.direction != "out":
            return
        device = self.session.io.get_device(transfer.channel)
        if isinstance(device, AudioOutputDevice):
            device.consume_samples(1)
            self._pump_host_audio_output(device.channel)
        elif isinstance(device, WS2812Device):
            device.consume_bytes(1)

    def _advance_simulated_io(self, results: list[StepResult], sim_cpu_hz: int) -> None:
        retired_count = sum(1 for result in results if result.retired)
        if retired_count:
            self.session.tick_io(retired_count / sim_cpu_hz)
            self._pump_host_audio_output()

    def _resume_time_driven_output(self, channel: int, direction: str) -> bool:
        device = self.session.io.get_device(channel)
        if direction != "out":
            return False
        if isinstance(device, AudioOutputDevice):
            if device.can_write():
                return True
            self.session.tick_io(device.sample_interval_s)
            self._pump_host_audio_output(channel)
            return device.can_write()
        if isinstance(device, WS2812Device):
            if device.can_write():
                return True
            self.session.tick_io(device.byte_interval_s)
            return device.can_write()
        return False

    def _is_time_driven_output_block(self, channel: int, direction: str) -> bool:
        device = self.session.io.get_device(channel)
        return direction == "out" and isinstance(device, (AudioOutputDevice, WS2812Device))

    def _advance_fast_wallclock_io(self) -> float:
        now = time.monotonic()
        if self._fast_run_last_wallclock_s is None:
            self._fast_run_last_wallclock_s = now
            return 0.0
        elapsed_s = min(max(0.0, now - self._fast_run_last_wallclock_s), 0.050)
        self._fast_run_last_wallclock_s = now
        if elapsed_s > 0.0:
            self.session.tick_io(elapsed_s)
            self._pump_host_audio_output()
        return elapsed_s

    def _accrue_fast_step_budget(self, cpu_hz: int, elapsed_s: float) -> int:
        self._fast_run_step_credit += elapsed_s * cpu_hz
        self._fast_run_step_credit = min(self._fast_run_step_credit, float(FAST_RUN_MAX_BUDGET_STEPS))
        step_budget = int(self._fast_run_step_credit)
        self._fast_run_step_credit -= step_budget
        return step_budget

    def _audio_preview_tick_ms(self, span_ms: float) -> float:
        if span_ms <= 8.0:
            return 1.0
        if span_ms <= 16.0:
            return 2.0
        if span_ms <= 40.0:
            return 5.0
        return 10.0

    def _cancel_run_callbacks(self) -> None:
        if self._slow_run_after_id is not None:
            try:
                self.after_cancel(self._slow_run_after_id)
            except tk.TclError:
                pass
            self._slow_run_after_id = None
        if self._fast_run_after_id is not None:
            try:
                self.after_cancel(self._fast_run_after_id)
            except tk.TclError:
                pass
            self._fast_run_after_id = None
        self._fast_run_last_wallclock_s = None
        self._fast_run_step_credit = 0.0

    def _schedule_slow_run_tick(self) -> None:
        self._slow_run_after_id = self.after(20, self._run_tick)

    def _schedule_fast_run_tick(self) -> None:
        self._fast_run_after_id = self.after(1, self._run_fast_tick)

    def _cpu_hz(self) -> int:
        token = self.fast_cpu_hz_var.get().strip()
        if not token:
            raise ValueError("CPU rate is required")
        value = int(token, 0)
        if value <= 0:
            raise ValueError("CPU rate must be positive")
        return value

    def _sync_host_audio_playback(self, *, clear_missing: bool = False) -> None:
        enabled: set[int] = set()
        for channel in list(self._host_audio_enabled_channels):
            device = self.session.io.get_device(channel)
            if not isinstance(device, AudioOutputDevice):
                self._host_audio.disable_stream(channel)
                continue
            device.set_output_tap_enabled(True)
            if self._host_audio.ensure_stream(channel, device.sample_rate_hz):
                enabled.add(channel)
            else:
                device.set_output_tap_enabled(False)
                self._host_audio.disable_stream(channel)
        if clear_missing:
            for channel in list(self._host_audio_enabled_channels - enabled):
                self._host_audio.disable_stream(channel)
        self._host_audio_enabled_channels = enabled

    def _pump_host_audio_output(self, channel: int | None = None) -> None:
        channels = [channel] if channel is not None else list(self._host_audio_enabled_channels)
        for current_channel in channels:
            if current_channel not in self._host_audio_enabled_channels:
                continue
            device = self.session.io.get_device(current_channel)
            if not isinstance(device, AudioOutputDevice):
                self._host_audio_enabled_channels.discard(current_channel)
                self._host_audio.disable_stream(current_channel)
                continue
            payload = device.drain_output_tap()
            if not payload:
                continue
            if not self._host_audio.push_samples(current_channel, device.sample_rate_hz, payload):
                self._host_audio_enabled_channels.discard(current_channel)
                device.set_output_tap_enabled(False)
                self._host_audio.disable_stream(current_channel)

    def _restart_host_audio_streams(self) -> None:
        if not self._host_audio_enabled_channels:
            return
        self._host_audio.close()
        self._host_audio = HostAudioPlaybackManager()

    def _handle_ps2_key_event(self, event: tk.Event[tk.Misc], *, pressed: bool) -> str | None:
        if not self.ps2_capture_var.get():
            return None
        device = self._selected_peripheral_device()
        if not isinstance(device, PS2KeyboardDevice):
            return None
        if self._focused_text_input():
            return None
        normalized = self._normalize_ps2_keysym(event.keysym)
        sequence = PS2_SCANCODES.get(normalized)
        if sequence is None:
            return None
        if pressed:
            if normalized in self._ps2_pressed_keys:
                return "break"
            self._ps2_pressed_keys.add(normalized)
            values = list(sequence)
        else:
            if normalized not in self._ps2_pressed_keys:
                return None
            self._ps2_pressed_keys.discard(normalized)
            if sequence[0] == 0xE0:
                values = [0xE0, 0xF0, sequence[1]]
            else:
                values = [0xF0, sequence[0]]
        self.session.queue_rx(device.channel, values)
        self._append_io_log(f"PS2[{device.channel:02X}] <= {self._format_bytes(values)}")
        self._refresh_peripherals()
        return "break"

    def _focused_text_input(self) -> bool:
        focused = self.focus_get()
        return isinstance(focused, TEXT_INPUT_WIDGETS)

    def _normalize_ps2_keysym(self, keysym: str) -> str:
        normalized = keysym.strip()
        if len(normalized) == 1 and normalized.isalpha():
            normalized = normalized.lower()
        else:
            normalized = normalized.lower()
        return PS2_KEY_ALIASES.get(normalized, normalized)

    def _field_value_for_target(self, target: str) -> int | None:
        target = target.upper()
        if target.startswith("R") and target[1:].isdigit():
            return self.session.cpu.state.registers[int(target[1:])]
        if target == "PC":
            return self.session.cpu.state.pc
        if target == "IOSEL":
            return self.session.cpu.state.iosel
        if target == "Z":
            return self.session.cpu.state.z
        if target == "C":
            return self.session.cpu.state.c
        return None

    def _parse_byte(self, text: str, *, allow_empty: bool) -> int:
        token = text.strip()
        if not token:
            if allow_empty:
                return 0
            raise ValueError("value is required")
        value = int(token, 0)
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{text!r} is out of byte range")
        return value

    def _parse_byte_tokens(self, text: str) -> list[int]:
        tokens = [token for token in text.replace(",", " ").split() if token]
        if not tokens:
            raise ValueError("enter at least one byte")
        return [self._parse_byte(token, allow_empty=False) for token in tokens]

    def _parse_positive_int(self, text: str, field_name: str) -> int:
        token = text.strip()
        if not token:
            raise ValueError(f"{field_name} is required")
        value = int(token, 0)
        if value <= 0:
            raise ValueError(f"{field_name} must be positive")
        return value

    def _format_bytes(self, values: list[int]) -> str:
        if not values:
            return "(empty)"
        hex_bytes = " ".join(f"{value:02X}" for value in values)
        ascii_text = "".join(chr(value) if 32 <= value <= 126 else "." for value in values)
        return f"{hex_bytes} | {ascii_text}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the Min8 GUI simulator")
    parser.add_argument("program", nargs="?", help="optional .asm or .bin file to load at startup")
    args = parser.parse_args(argv)
    app = Min8Gui(initial_path=args.program)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
