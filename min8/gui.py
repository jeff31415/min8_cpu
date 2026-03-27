"""Tkinter-based GUI simulator/debugger for Min8."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .cpu import StepResult
from .exceptions import IllegalInstruction, MachineHalted
from .isa import decode_opcode
from .session import Min8Session

MONO_FONT = ("Courier New", 10)
MONO_FONT_SMALL = ("Courier New", 9)

SOURCE_NUMBER_RE = re.compile(r"0x[0-9A-Fa-f]+|0b[01]+|\b\d+\b|'[^']'")
REGISTER_RE = re.compile(r"\bR[0-7]\b", re.IGNORECASE)
LABEL_RE = re.compile(r"\s*([A-Za-z_.$][A-Za-z0-9_.$]*:)")
TOKEN_RE = re.compile(r"\S+")
DISASM_LINE_RE = re.compile(r"^([0-9A-F]{2}:)\s+([0-9A-F]{2})\s+([^;]+)(.*)$")

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


class Min8Gui(tk.Tk):
    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.title("Min8 GUI Simulator")
        self.geometry("1460x900")
        self.minsize(1280, 780)

        self.session = Min8Session()
        self.running = False
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

        self.field_value_labels: dict[str, tk.Label] = {}
        self.field_base_colors: dict[str, str] = {}
        self.memory_cells: dict[int, tk.Label] = {}
        self.body_pane: ttk.PanedWindow | None = None
        self.left_detail_pane: ttk.PanedWindow | None = None
        self.right_detail_pane: ttk.PanedWindow | None = None

        self._build_ui()
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
        ttk.Button(toolbar, text="Pause", command=self.on_pause).pack(side=tk.LEFT, padx=2)

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
        notebook.add(source_tab, text="Source")
        notebook.add(disasm_tab, text="Disassembly")

        self.source_text = self._make_text_widget(source_tab)
        self.source_text.bind("<Double-Button-1>", self.on_source_double_click)
        self.disasm_text = self._make_text_widget(disasm_tab)
        self.disasm_text.bind("<Double-Button-1>", self.on_disasm_double_click)

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
        self.running = False
        self.session.reset()
        self._set_status("CPU reset")
        self.refresh_all()

    def on_step(self) -> None:
        self.running = False
        self._run_single_step()

    def on_run(self) -> None:
        self.running = True
        self._run_tick()

    def on_pause(self) -> None:
        self.running = False
        self._set_status("Paused")

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
        self.running = False
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
        self._handle_result(result)

    def _run_tick(self) -> None:
        if not self.running:
            return
        try:
            results = self.session.run_batch(max_steps=64)
        except (IllegalInstruction, MachineHalted) as exc:
            self.running = False
            self._set_status(str(exc))
            self.refresh_all()
            return

        if results:
            self._handle_result(results[-1], refresh=False)
        else:
            self._handle_stop_without_step()

        if self.session.last_stop_reason in {"breakpoint", "blocked", "halted", "error"}:
            self.running = False

        self.refresh_all()
        if self.running:
            self.after(20, self._run_tick)

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
