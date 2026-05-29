import ctypes
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional, Dict, Tuple, List, Any
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import fitz

from config import (
    APP_TITLE,
    COLORS,
    FONTS,
    UI_PADDING,
    PARAM_RANGES,
    DEFAULT_PARAMS,
    CONFIG_FILENAME,
    CONFIG_DIR_NAME,
    PREVIEW_ZOOM_MODES,
    PREVIEW_UPDATE_DELAY,
    SETTINGS_SAVE_DELAY,
    DESIGN_WINDOW_W,
    DESIGN_WINDOW_H,
    MIN_WINDOW_W,
    MIN_WINDOW_H,
    DEFAULT_WINDOW_W,
    DEFAULT_WINDOW_H,
    PANEL_WIDTH,
    PARAM_HINTS,
    LOG_HEIGHT,
)
from validators import ParamValidator, ValidationError
from cache import PreviewCache
from worker import MergePDFWorker


def enable_high_dpi_awareness():
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def normalize_text(text: Optional[str]) -> str:
    return re.sub(r"\s+", "", text or "")


def desktop_default_file() -> str:
    candidates = []
    one_drive = os.environ.get("OneDrive")
    if one_drive:
        candidates.append(Path(one_drive) / "Desktop")
    candidates.append(Path.home() / "Desktop")
    candidates.append(Path.home())

    for folder in candidates:
        if folder.exists():
            return str(folder / "merged.pdf")
    return str(Path.cwd() / "merged.pdf")


def app_config_file() -> Path:
    if sys.platform.startswith("win"):
        root = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or str(Path.home())
        )
        config_dir = Path(root) / CONFIG_DIR_NAME
    else:
        config_dir = Path.home() / ".barcode_merger_pro"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / CONFIG_FILENAME


def load_saved_params() -> Dict[str, Optional[str]]:
    defaults = DEFAULT_PARAMS.copy()
    defaults.update(
        {
            "window_width": None,
            "window_height": None,
        }
    )
    path = app_config_file()
    if not path.exists():
        return defaults

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults

    for key in defaults:
        value = data.get(key)
        if value is not None:
            defaults[key] = str(value)

    return defaults


class BarcodeMergerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.saved_params = load_saved_params()

        # 初始化缓存
        self.preview_cache = PreviewCache()

        # 线程管理
        self.merge_thread = None

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        design_w = DESIGN_WINDOW_W
        design_h = DESIGN_WINDOW_H
        if screen_w < design_w + 80 or screen_h < design_h + 80:
            design_w = min(DEFAULT_WINDOW_W, max(MIN_WINDOW_W, screen_w - 60))
            design_h = min(DEFAULT_WINDOW_H, max(MIN_WINDOW_H, screen_h - 80))

        saved_window_width = self.saved_params.get("window_width")
        saved_window_height = self.saved_params.get("window_height")
        try:
            window_w = int(saved_window_width)
            window_h = int(saved_window_height)
        except (TypeError, ValueError):
            window_w = design_w
            window_h = design_h

        window_w = max(design_w, min(window_w, max(screen_w - 40, design_w)))
        window_h = max(design_h, min(window_h, max(screen_h - 80, design_h)))

        pos_x = max((screen_w - window_w) // 2, 0)
        pos_y = max((screen_h - window_h) // 2, 0)
        self.root.geometry(f"{window_w}x{window_h}+{pos_x}+{pos_y}")
        self.root.minsize(design_w, design_h)
        self.root.resizable(True, True)

        try:
            self.root.tk.call("tk", "scaling", self.root.winfo_fpixels("1i") / 72.0)
        except Exception:
            pass

        self.preview_image = None
        self.preview_after_id = None
        self.valid_barcode_indices = []
        self.settings_save_after_id = None
        self.is_closing = False

        self.base_pdf_var = tk.StringVar()
        self.barcode_pdf_var = tk.StringVar()
        self.output_pdf_var = tk.StringVar(value=desktop_default_file())

        self.barcode_width_ratio_var = tk.StringVar(
            value=self.saved_params["barcode_width_ratio"]
        )
        self.bottom_margin_var = tk.StringVar(value=self.saved_params["bottom_margin"])
        self.max_barcode_height_var = tk.StringVar(
            value=self.saved_params["max_barcode_height"]
        )
        self.x_offset_var = tk.StringVar(value=self.saved_params["x_offset"])
        self.y_offset_var = tk.StringVar(value=self.saved_params["y_offset"])
        self.skip_keyword_var = tk.StringVar(value=self.saved_params["skip_keyword"])

        self.preview_zoom_var = tk.StringVar(value="Fit Page")
        self.preview_page_var = tk.IntVar(value=1)
        self.preview_page_text_var = tk.StringVar(value="Page 0 / 0")
        self.preview_detail_var = tk.StringVar(value="Select files to preview")

        self.setup_style()
        self.build_ui()
        self.bind_param_autosave()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log("Application started")
        self.log(f"Default output: {self.output_pdf_var.get()}")
        self.log(f"Loaded settings from: {app_config_file()}")
        self.log(f"Window size: {self.root.winfo_width()} x {self.root.winfo_height()}")

    def setup_style(self) -> None:
        # 从配置中获取颜色
        c = COLORS

        self.root.configure(bg=c["bg"])
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.option_add("*TCombobox*Listbox.background", "#E8E6DF")
        self.root.option_add("*TCombobox*Listbox.foreground", "#000000")
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#000000")

        style.configure("TFrame", background=c["bg"])
        style.configure("Panel.TFrame", background=c["panel"])
        style.configure(
            "TLabel", background=c["bg"], foreground=c["text"], font=FONTS["default"]
        )
        style.configure(
            "Muted.TLabel",
            background=c["panel"],
            foreground=c["muted"],
            font=FONTS["muted"],
        )
        style.configure(
            "Title.TLabel",
            background=c["panel"],
            foreground=c["text"],
            font=FONTS["title"],
        )
        style.configure(
            "Section.TLabel",
            background=c["panel"],
            foreground=c["accent"],
            font=FONTS["section"],
        )
        style.configure(
            "Status.TLabel",
            background=c["panel"],
            foreground=c["accent"],
            font=FONTS["status"],
        )
        style.configure("TButton", font=FONTS["default"], padding=(12, 7))
        style.map("TButton", foreground=[("disabled", "#777777")])
        style.configure("Accent.TButton", font=FONTS["semibold"], padding=(14, 8))
        style.configure("Param.TButton", font=FONTS["semibold"], padding=(8, 5))
        style.configure(
            "TEntry",
            fieldbackground=c["input_bg"],
            foreground=c["text"],
            insertcolor=c["text"],
            padding=7,
        )
        style.configure(
            "TSpinbox",
            fieldbackground=c["input_bg"],
            foreground=c["text"],
            insertcolor=c["text"],
            padding=7,
            arrowsize=18,
        )
        style.configure(
            "TCombobox",
            fieldbackground="#E8E6DF",
            foreground="#000000",
            selectforeground="#000000",
            selectbackground="#E8E6DF",
            arrowcolor="#000000",
            padding=6,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#E8E6DF")],
            foreground=[("readonly", "#000000")],
            selectforeground=[("readonly", "#000000")],
            selectbackground=[("readonly", "#E8E6DF")],
        )
        style.configure(
            "Vertical.TScrollbar",
            gripcount=0,
            background=c["panel_2"],
            darkcolor=c["panel_2"],
            lightcolor=c["panel_2"],
            troughcolor=c["bg"],
            bordercolor=c["bg"],
            arrowcolor=c["muted"],
        )
        style.configure(
            "Horizontal.TScrollbar",
            gripcount=0,
            background=c["panel_2"],
            darkcolor=c["panel_2"],
            lightcolor=c["panel_2"],
            troughcolor=c["bg"],
            bordercolor=c["bg"],
            arrowcolor=c["muted"],
        )
        style.configure(
            "Horizontal.TScale", background=c["panel"], troughcolor=c["panel_2"]
        )

    def on_close(self) -> None:
        self.is_closing = True

        # 停止合并线程
        if self.merge_thread and self.merge_thread.is_running():
            self.merge_thread.stop()
            self.merge_thread.join(timeout=2)

        # 清理缓存
        if self.preview_cache:
            self.preview_cache.clear()

        # 保存设置
        self.save_settings()
        self.root.destroy()

    def bind_param_autosave(self) -> None:
        for var in (
            self.barcode_width_ratio_var,
            self.bottom_margin_var,
            self.max_barcode_height_var,
            self.x_offset_var,
            self.y_offset_var,
            self.skip_keyword_var,
        ):
            var.trace_add("write", lambda *args: self.schedule_save_settings())

    def schedule_save_settings(self) -> None:
        if self.settings_save_after_id:
            self.root.after_cancel(self.settings_save_after_id)
        self.settings_save_after_id = self.root.after(
            SETTINGS_SAVE_DELAY, self.save_settings
        )

    def save_settings(self) -> None:
        self.settings_save_after_id = None

        # 使用验证器验证参数
        try:
            params_dict = {
                "barcode_width_ratio": self.barcode_width_ratio_var.get(),
                "bottom_margin": self.bottom_margin_var.get(),
                "max_barcode_height": self.max_barcode_height_var.get(),
                "x_offset": self.x_offset_var.get(),
                "y_offset": self.y_offset_var.get(),
            }
            ParamValidator.validate_all_params(params_dict)
        except ValidationError:
            return

        try:
            window_width = max(int(self.root.winfo_width()), 1)
            window_height = max(int(self.root.winfo_height()), 1)
        except Exception:
            window_width = None
            window_height = None

        data = {
            "barcode_width_ratio": self.barcode_width_ratio_var.get(),
            "bottom_margin": self.bottom_margin_var.get(),
            "max_barcode_height": self.max_barcode_height_var.get(),
            "x_offset": self.x_offset_var.get(),
            "y_offset": self.y_offset_var.get(),
            "skip_keyword": self.skip_keyword_var.get(),
            "window_width": window_width,
            "window_height": window_height,
        }

        try:
            app_config_file().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            if hasattr(self, "log_text"):
                self.log(f"Error saving settings: {exc}")

    def build_ui(self) -> None:
        main = ttk.Frame(self.root, style="TFrame")
        main.pack(
            fill="both", expand=True, padx=UI_PADDING["outer"], pady=UI_PADDING["outer"]
        )

        left_outer = ttk.Frame(main, style="Panel.TFrame")
        left_outer.pack(side="left", fill="y", padx=(0, UI_PADDING["inner"]))
        left_outer.configure(width=PANEL_WIDTH)
        left_outer.pack_propagate(False)

        right = ttk.Frame(main, style="TFrame")
        right.pack(side="left", fill="both", expand=True)

        left = self.create_scrollable_panel(left_outer)
        self.build_control_panel(left)
        self.build_preview_panel(right)
        self.build_log_panel(right)

    def create_scrollable_panel(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(
            parent, bg=COLORS["panel"], highlightthickness=0, borderwidth=0
        )
        scrollbar = ttk.Scrollbar(
            parent, orient="vertical", command=canvas.yview, style="Vertical.TScrollbar"
        )
        inner = ttk.Frame(canvas, style="Panel.TFrame")

        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def update_scroll_region(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window_id, width=canvas.winfo_width())

        def on_mousewheel(event):
            delta = self.wheel_delta(event)
            canvas.yview_scroll(delta, "units")

        inner.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_scroll_region)
        canvas.bind(
            "<Enter>", lambda event: self.bind_mousewheel(canvas, on_mousewheel)
        )
        canvas.bind("<Leave>", lambda event: self.unbind_mousewheel())

        return inner

    def wheel_delta(self, event: tk.Event) -> int:
        if getattr(event, "num", None) == 4:
            return -1
        if getattr(event, "num", None) == 5:
            return 1
        if getattr(event, "delta", 0):
            return -int(event.delta / 120)
        return 0

    def bind_mousewheel(self, widget: tk.Widget, callback: callable) -> None:
        widget.bind_all("<MouseWheel>", callback)
        widget.bind_all("<Button-4>", callback)
        widget.bind_all("<Button-5>", callback)

    def unbind_mousewheel(self) -> None:
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")

    def build_control_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="PDF Barcode Merger", style="Title.TLabel").pack(
            anchor="w",
            padx=UI_PADDING["outer"],
            pady=(UI_PADDING["outer"], UI_PADDING["tiny"]),
        )
        tk.Label(
            parent,
            text="Select files, adjust placement, preview, then merge.",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            justify="left",
            anchor="w",
            wraplength=360,
            font=FONTS["muted"],
        ).pack(
            anchor="w",
            fill="x",
            padx=UI_PADDING["outer"],
            pady=(0, UI_PADDING["outer"]),
        )

        self.section(parent, "Files")
        self.file_row(parent, "Base PDF", self.base_pdf_var, self.choose_base_pdf)
        self.file_row(
            parent, "Barcode PDF", self.barcode_pdf_var, self.choose_barcode_pdf
        )
        self.file_row(
            parent, "Output PDF", self.output_pdf_var, self.choose_output_pdf
        )

        self.section(parent, "Barcode Settings")

        # 使用PARAM_RANGES动态构建参数行
        for param_name, config in PARAM_RANGES.items():
            var = getattr(self, f"{param_name}_var")
            self.param_row(
                parent,
                param_name,
                var,
                config["min"],
                config["max"],
                config["step"],
                config["format"],
            )

        # 添加筛选关键词输入框
        self.section(parent, "Filter Settings")
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="x", padx=UI_PADDING["outer"], pady=(0, UI_PADDING["small"]))
        ttk.Label(frame, text="Skip Keyword", style="Muted.TLabel").pack(
            anchor="w", pady=(0, UI_PADDING["tiny"])
        )
        row = ttk.Frame(frame, style="Panel.TFrame")
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=self.skip_keyword_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<KeyRelease>", lambda event: self.schedule_preview())
        entry.bind("<Return>", lambda event: self.update_preview())
        entry.bind("<FocusOut>", lambda event: self.update_preview())

        hint = tk.Label(
            parent,
            text=PARAM_HINTS,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            justify="left",
            font=FONTS["muted"],
        )
        hint.pack(
            anchor="w",
            padx=UI_PADDING["outer"],
            pady=(UI_PADDING["small"], UI_PADDING["inner"]),
        )

        btn_frame = ttk.Frame(parent, style="Panel.TFrame")
        btn_frame.pack(
            fill="x",
            padx=UI_PADDING["outer"],
            pady=(UI_PADDING["small"], UI_PADDING["outer"]),
        )

        ttk.Button(
            btn_frame, text="Clear Selected Files", command=self.clear_selected_files
        ).pack(fill="x", pady=(0, UI_PADDING["small"]))
        ttk.Button(btn_frame, text="Refresh Preview", command=self.update_preview).pack(
            fill="x", pady=(0, UI_PADDING["small"])
        )
        ttk.Button(
            btn_frame, text="Merge PDF", style="Accent.TButton", command=self.merge_pdf
        ).pack(fill="x")

    def build_preview_panel(self, parent: ttk.Frame) -> None:
        preview_panel = ttk.Frame(parent, style="Panel.TFrame")
        preview_panel.pack(fill="both", expand=True)

        top = ttk.Frame(preview_panel, style="Panel.TFrame")
        top.pack(
            fill="x",
            padx=UI_PADDING["outer"],
            pady=(UI_PADDING["small"], UI_PADDING["tiny"]),
        )
        ttk.Label(top, text="Live Preview", style="Title.TLabel").pack(side="left")
        ttk.Label(
            top, textvariable=self.preview_page_text_var, style="Status.TLabel"
        ).pack(side="right")

        controls = ttk.Frame(preview_panel, style="Panel.TFrame")
        controls.pack(
            fill="x",
            padx=UI_PADDING["outer"],
            pady=(UI_PADDING["tiny"], UI_PADDING["small"]),
        )

        ttk.Label(controls, text="Zoom", style="Muted.TLabel").pack(
            side="left", padx=(0, UI_PADDING["small"])
        )
        zoom_box = ttk.Combobox(
            controls,
            textvariable=self.preview_zoom_var,
            values=PREVIEW_ZOOM_MODES,
            state="readonly",
            width=12,
        )
        zoom_box.pack(side="left", padx=(0, UI_PADDING["inner"]))
        zoom_box.bind("<<ComboboxSelected>>", lambda event: self.update_preview())

        ttk.Button(controls, text="Prev", command=self.prev_preview_page).pack(
            side="left", padx=(0, UI_PADDING["tiny"])
        )
        self.preview_page_spin = ttk.Entry(
            controls,
            textvariable=self.preview_page_var,
            width=6,
        )
        self.preview_page_spin.pack(side="left", padx=(0, UI_PADDING["tiny"]))
        self.preview_page_spin.bind(
            "<Return>", lambda event: self.preview_page_changed()
        )
        self.preview_page_spin.bind(
            "<FocusOut>", lambda event: self.preview_page_changed()
        )
        ttk.Button(controls, text="Next", command=self.next_preview_page).pack(
            side="left", padx=(0, UI_PADDING["inner"])
        )

        self.preview_page_scale = ttk.Scale(
            controls,
            from_=1,
            to=1,
            orient="horizontal",
            command=self.preview_scale_changed,
        )
        self.preview_page_scale.pack(side="left", fill="x", expand=True)

        ttk.Label(
            preview_panel, textvariable=self.preview_detail_var, style="Status.TLabel"
        ).pack(anchor="w", padx=UI_PADDING["outer"], pady=(0, UI_PADDING["small"]))

        holder = ttk.Frame(preview_panel, style="Panel.TFrame")
        holder.pack(
            fill="both",
            expand=True,
            padx=UI_PADDING["outer"],
            pady=(0, UI_PADDING["outer"]),
        )
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            holder,
            bg=COLORS["preview_bg"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
        )

        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        self.preview_canvas.bind("<Configure>", lambda event: self.schedule_preview())
        self.preview_canvas.bind(
            "<Enter>",
            lambda event: self.bind_mousewheel(
                self.preview_canvas, self.preview_mousewheel
            ),
        )
        self.preview_canvas.bind("<Leave>", lambda event: self.unbind_mousewheel())
        self.draw_preview_placeholder("Select Base PDF and Barcode PDF")

    def build_log_panel(self, parent: ttk.Frame) -> None:
        log_panel = ttk.Frame(parent, style="Panel.TFrame")
        log_panel.pack(fill="both", expand=False, pady=(UI_PADDING["inner"], 0))

        header = ttk.Frame(log_panel, style="Panel.TFrame")
        header.pack(
            fill="x",
            padx=UI_PADDING["outer"],
            pady=(UI_PADDING["small"], UI_PADDING["tiny"]),
        )
        ttk.Label(header, text="Console Output", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Clear", command=self.clear_log).pack(side="right")

        text_frame = ttk.Frame(log_panel, style="Panel.TFrame")
        text_frame.pack(
            fill="both",
            expand=True,
            padx=UI_PADDING["outer"],
            pady=(0, UI_PADDING["inner"]),
        )

        self.log_text = tk.Text(
            text_frame,
            height=LOG_HEIGHT,
            bg=COLORS["preview_bg"],
            fg=COLORS["log_text"],
            insertbackground=COLORS["log_text"],
            relief="flat",
            font=FONTS["mono"],
            wrap="word",
            borderwidth=0,
        )
        log_scrollbar = ttk.Scrollbar(
            text_frame,
            orient="vertical",
            command=self.log_text.yview,
            style="Vertical.TScrollbar",
        )
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scrollbar.pack(side="right", fill="y")
        self.log_text.configure(state="disabled")

    def preview_mousewheel(self, event: tk.Event) -> None:
        delta = self.wheel_delta(event)
        if delta > 0:
            self.next_preview_page()
        elif delta < 0:
            self.prev_preview_page()

    def section(self, parent: ttk.Frame, title: str) -> None:
        ttk.Label(parent, text=title, style="Section.TLabel").pack(
            anchor="w", padx=18, pady=(10, 8)
        )

    def file_row(
        self,
        parent: ttk.Frame,
        label: str,
        var: tk.StringVar,
        command: callable,
    ) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="x", padx=UI_PADDING["outer"], pady=(0, UI_PADDING["small"]))

        ttk.Label(frame, text=label, style="Muted.TLabel").pack(
            anchor="w", pady=(0, UI_PADDING["tiny"])
        )
        row = ttk.Frame(frame, style="Panel.TFrame")
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=command).pack(
            side="left", padx=(UI_PADDING["small"], 0)
        )

    def param_row(
        self,
        parent: ttk.Frame,
        label: str,
        var: tk.StringVar,
        from_: float,
        to: float,
        increment: float,
        fmt: str,
    ) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="x", padx=UI_PADDING["outer"], pady=(0, UI_PADDING["small"]))
        ttk.Label(frame, text=label, style="Muted.TLabel").pack(
            anchor="w", pady=(0, UI_PADDING["tiny"])
        )

        row = ttk.Frame(frame, style="Panel.TFrame")
        row.pack(fill="x")

        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<KeyRelease>", lambda event: self.schedule_preview())
        entry.bind("<FocusOut>", lambda event: self.schedule_preview())
        entry.bind("<Return>", lambda event: self.update_preview())

        minus_btn = ttk.Button(
            row,
            text="−",
            width=3,
            style="Param.TButton",
            command=lambda: self.adjust_param(var, -increment, from_, to, fmt),
        )
        minus_btn.pack(side="left", padx=(UI_PADDING["small"], UI_PADDING["tiny"]))

        plus_btn = ttk.Button(
            row,
            text="+",
            width=3,
            style="Param.TButton",
            command=lambda: self.adjust_param(var, increment, from_, to, fmt),
        )
        plus_btn.pack(side="left")

    def adjust_param(
        self, var: tk.StringVar, delta: float, from_: float, to: float, fmt: str
    ) -> None:
        try:
            value = float(var.get())
        except ValueError:
            value = 0.0

        value += delta
        value = max(float(from_), min(float(to), value))

        if fmt == "%.0f":
            var.set(str(int(round(value))))
        elif fmt == "%.2f":
            var.set(f"{value:.2f}")
        else:
            var.set(str(value))

        self.save_settings()
        self.update_preview()

    def clear_selected_files(self) -> None:
        self.base_pdf_var.set("")
        self.barcode_pdf_var.set("")
        self.output_pdf_var.set(desktop_default_file())
        self.preview_page_var.set(1)
        self.valid_barcode_indices = []
        self.preview_image = None
        self.draw_preview_placeholder("Select Base PDF and Barcode PDF")
        self.log("Selected files cleared")
        self.log(f"Output PDF reset to default: {self.output_pdf_var.get()}")

    def choose_base_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Base PDF", filetypes=[("PDF files", "*.pdf")]
        )
        if path:
            self.base_pdf_var.set(path)
            self.preview_page_var.set(1)
            self.log(f"Base PDF selected: {path}")
            self.update_preview()

    def choose_barcode_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Barcode PDF", filetypes=[("PDF files", "*.pdf")]
        )
        if path:
            self.barcode_pdf_var.set(path)
            self.preview_page_var.set(1)
            self.log(f"Barcode PDF selected: {path}")
            self.update_preview()

    def choose_output_pdf(self) -> None:
        current = self.output_pdf_var.get().strip()
        initial_dir = str(Path(current).parent) if current else str(Path.home())
        initial_file = Path(current).name if current else "merged.pdf"
        path = filedialog.asksaveasfilename(
            title="Select Output PDF",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if path:
            self.output_pdf_var.set(path)
            self.log(f"Output PDF selected: {path}")

    def log(self, message: str) -> None:
        print(message)
        if hasattr(self, "log_text"):
            self.log_text.configure(state="normal")
            self.log_text.insert("end", str(message) + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
            self.root.update_idletasks()

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def draw_preview_placeholder(self, text: str) -> None:
        self.preview_canvas.delete("all")
        w = max(self.preview_canvas.winfo_width(), 1)
        h = max(self.preview_canvas.winfo_height(), 1)
        self.preview_canvas.configure(scrollregion=(0, 0, w, h))
        self.preview_canvas.create_text(
            w / 2,
            h / 2,
            text=text,
            fill=COLORS["muted"],
            font=FONTS["placeholder"],
        )
        self.preview_page_text_var.set("Page 0 / 0")
        self.preview_detail_var.set(text)

    def schedule_preview(self) -> None:
        if self.preview_after_id:
            self.root.after_cancel(self.preview_after_id)
        self.preview_after_id = self.root.after(
            PREVIEW_UPDATE_DELAY, self.update_preview
        )

    def get_params(self) -> Dict[str, float]:
        try:
            params_dict = {
                "barcode_width_ratio": self.barcode_width_ratio_var.get(),
                "bottom_margin": self.bottom_margin_var.get(),
                "max_barcode_height": self.max_barcode_height_var.get(),
                "x_offset": self.x_offset_var.get(),
                "y_offset": self.y_offset_var.get(),
            }
            return ParamValidator.validate_all_params(params_dict)
        except ValidationError as e:
            raise ValueError(f"Parameter validation failed: {str(e)}")

    def calculate_rect(
        self, base_page: fitz.Page, barcode_page: fitz.Page, params: Dict[str, float]
    ) -> Tuple[fitz.Rect, float, float]:
        page_w = base_page.rect.width
        page_h = base_page.rect.height
        br = barcode_page.rect

        target_w = page_w * params["barcode_width_ratio"]
        target_h = target_w * br.height / br.width

        if target_h > params["max_barcode_height"]:
            target_h = params["max_barcode_height"]
            target_w = target_h * br.width / br.height

        x0 = (page_w - target_w) / 2 + params["x_offset"]
        x1 = x0 + target_w
        y1 = page_h - params["bottom_margin"] + params["y_offset"]
        y0 = y1 - target_h

        return fitz.Rect(x0, y0, x1, y1), target_w, target_h

    def get_valid_barcode_indices(
        self, barcodes: fitz.Document
    ) -> Tuple[List[int], List[int]]:
        skip_keyword_normalized = normalize_text(self.skip_keyword_var.get())
        valid = []
        skipped = []
        for i in range(len(barcodes)):
            text = barcodes[i].get_text("text")
            if skip_keyword_normalized and skip_keyword_normalized in normalize_text(text):
                skipped.append(i + 1)
            else:
                valid.append(i)
        return valid, skipped

    def validate_base_page_count(
        self, base: fitz.Document, total_barcode_count: int, valid_barcode_count: int
    ) -> Optional[str]:
        if len(base) in {1, total_barcode_count, valid_barcode_count}:
            return None
        return (
            "Base PDF page count must be 1 page as a reusable template "
            f"or match the barcode page count ({total_barcode_count}) "
            f"or valid barcode page count ({valid_barcode_count}). "
            f"Current base pages: {len(base)}."
        )

    def get_base_page_index(
        self,
        base: fitz.Document,
        barcode_index: int,
        preview_page_number: int,
        total_barcode_count: int,
    ) -> int:
        if len(base) == 1:
            return 0
        if len(base) == total_barcode_count:
            return barcode_index
        return preview_page_number - 1

    def validate_files_for_preview(self) -> Tuple[Optional[str], Optional[str]]:
        base_pdf = self.base_pdf_var.get().strip()
        barcode_pdf = self.barcode_pdf_var.get().strip()
        if not base_pdf or not barcode_pdf:
            self.draw_preview_placeholder("Select Base PDF and Barcode PDF")
            return None, None
        if not Path(base_pdf).exists():
            self.draw_preview_placeholder("Base PDF not found")
            return None, None
        if not Path(barcode_pdf).exists():
            self.draw_preview_placeholder("Barcode PDF not found")
            return None, None
        return base_pdf, barcode_pdf

    def set_preview_page_range(self, total: int) -> int:
        total = max(total, 0)
        if total <= 0:
            self.preview_page_var.set(1)
            self.preview_page_scale.configure(from_=1, to=1)
            self.preview_page_scale.set(1)
            return 1

        current = self.safe_preview_page_number()
        current = min(max(current, 1), total)
        self.preview_page_var.set(current)
        self.preview_page_scale.configure(from_=1, to=total)
        self.preview_page_scale.set(current)
        return current

    def safe_preview_page_number(self) -> int:
        try:
            return int(float(self.preview_page_var.get()))
        except Exception:
            return 1

    def preview_scale_changed(self, value: str) -> None:
        total = max(len(self.valid_barcode_indices), 1)
        page = int(round(float(value)))
        page = min(max(page, 1), total)
        if page != self.safe_preview_page_number():
            self.preview_page_var.set(page)
            self.schedule_preview()

    def preview_page_changed(self) -> None:
        total = max(len(self.valid_barcode_indices), 1)
        page = self.safe_preview_page_number()
        page = min(max(page, 1), total)
        self.preview_page_var.set(page)
        self.preview_page_scale.set(page)
        self.update_preview()

    def prev_preview_page(self) -> None:
        page = max(self.safe_preview_page_number() - 1, 1)
        self.preview_page_var.set(page)
        self.preview_page_scale.set(page)
        self.update_preview()

    def next_preview_page(self) -> None:
        total = max(len(self.valid_barcode_indices), 1)
        page = min(self.safe_preview_page_number() + 1, total)
        self.preview_page_var.set(page)
        self.preview_page_scale.set(page)
        self.update_preview()

    def get_preview_zoom(self, page_rect: fitz.Rect) -> float:
        mode = self.preview_zoom_var.get()
        canvas_w = max(self.preview_canvas.winfo_width() - 24, 100)
        canvas_h = max(self.preview_canvas.winfo_height() - 24, 100)

        if mode == "Fit Width":
            zoom = canvas_w / page_rect.width
        elif mode == "Fit Page":
            zoom = min(canvas_w / page_rect.width, canvas_h / page_rect.height)
        elif mode.endswith("%"):
            try:
                zoom = float(mode.rstrip("%")) / 100.0
            except ValueError:
                zoom = min(canvas_w / page_rect.width, canvas_h / page_rect.height)
        else:
            zoom = min(canvas_w / page_rect.width, canvas_h / page_rect.height)

        return max(min(zoom, 8), 0.05)

    def update_preview(self) -> None:
        self.preview_after_id = None
        base_pdf, barcode_pdf = self.validate_files_for_preview()
        if not base_pdf or not barcode_pdf:
            return

        temp = None
        try:
            params = self.get_params()

            # 使用缓存加载PDF文档
            base = self.preview_cache.load_or_open(base_pdf)
            barcodes = self.preview_cache.load_or_open(barcode_pdf)

            if len(base) == 0:
                self.draw_preview_placeholder("Base PDF has no pages")
                return
            if len(barcodes) == 0:
                self.draw_preview_placeholder("Barcode PDF has no pages")
                return

            self.valid_barcode_indices, skipped_pages = self.get_valid_barcode_indices(
                barcodes
            )
            if not self.valid_barcode_indices:
                self.draw_preview_placeholder("No valid barcode page found")
                return
            base_page_count_error = self.validate_base_page_count(
                base, len(barcodes), len(self.valid_barcode_indices)
            )
            if base_page_count_error:
                self.draw_preview_placeholder(base_page_count_error)
                return

            preview_page_number = self.set_preview_page_range(
                len(self.valid_barcode_indices)
            )
            barcode_index = self.valid_barcode_indices[preview_page_number - 1]
            base_page_index = self.get_base_page_index(
                base, barcode_index, preview_page_number, len(barcodes)
            )

            temp = fitz.open()
            temp.insert_pdf(base, from_page=base_page_index, to_page=base_page_index)
            page = temp[-1]
            target_rect, target_w, target_h = self.calculate_rect(
                page, barcodes[barcode_index], params
            )
            page.show_pdf_page(target_rect, barcodes, barcode_index)

            zoom = self.get_preview_zoom(page.rect)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            png_bytes = pix.tobytes("png")

            self.preview_image = tk.PhotoImage(data=png_bytes)
            self.preview_canvas.delete("all")
            canvas_w = max(self.preview_canvas.winfo_width(), 1)
            canvas_h = max(self.preview_canvas.winfo_height(), 1)
            image_w = self.preview_image.width()
            image_h = self.preview_image.height()
            x = max((canvas_w - image_w) / 2, 0)
            y = max((canvas_h - image_h) / 2, 0)
            self.preview_canvas.create_image(
                x, y, anchor="nw", image=self.preview_image
            )
            self.preview_canvas.configure(
                scrollregion=(
                    0,
                    0,
                    max(image_w + x * 2, canvas_w),
                    max(image_h + y * 2, canvas_h),
                )
            )

            self.preview_page_text_var.set(
                f"Page {preview_page_number} / {len(self.valid_barcode_indices)}"
            )
            skipped_count = len(skipped_pages)
            self.preview_detail_var.set(
                f"Source barcode page {barcode_index + 1} / {len(barcodes)} | "
                f"Base page {base_page_index + 1} / {len(base)} | "
                f"Skipped {skipped_count} page(s) | "
                f"zoom {zoom * 100:.0f}% | "
                f"width {target_w:.2f}, height {target_h:.2f} | "
                f"left {target_rect.x0:.2f}, top {target_rect.y0:.2f}, right {target_rect.x1:.2f}, bottom {target_rect.y1:.2f}"
            )

        except Exception as exc:
            self.draw_preview_placeholder(str(exc))
            self.log(f"Preview failed: {exc}")
        finally:
            if temp:
                try:
                    temp.close()
                except Exception:
                    pass

    def merge_pdf(self) -> None:
        # 检查是否已有合并任务运行
        if self.merge_thread and self.merge_thread.is_running():
            messagebox.showwarning(APP_TITLE, "Already processing PDF. Please wait...")
            return

        # 验证文件和参数
        try:
            base_pdf = self.base_pdf_var.get().strip()
            barcode_pdf = self.barcode_pdf_var.get().strip()
            output_pdf = self.output_pdf_var.get().strip()

            base_pdf, barcode_pdf, output_pdf = ParamValidator.validate_all_files(
                base_pdf, barcode_pdf, output_pdf
            )
            params = self.get_params()
        except (ValidationError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            self.log(f"Validation failed: {exc}")
            return

        # 输出开始日志
        self.log("=" * 60)
        self.log("Starting PDF merge (processing in background)")
        self.log("=" * 60)
        self.log(f"Base PDF: {base_pdf}")
        self.log(f"Barcode PDF: {barcode_pdf}")
        self.log(f"Output PDF: {output_pdf}")
        self.log(f"Skip keyword: {self.skip_keyword_var.get()}")
        self.log("-" * 60)
        self.log("Current barcode settings:")
        self.log(f"  Barcode width ratio: {params['barcode_width_ratio']}")
        self.log(f"  Bottom margin: {params['bottom_margin']}")
        self.log(f"  Max barcode height: {params['max_barcode_height']}")
        self.log(f"  X offset: {params['x_offset']}")
        self.log(f"  Y offset: {params['y_offset']}")
        self.log("-" * 60)

        # 创建并启动后台工作线程
        self.merge_thread = MergePDFWorker(
            base_pdf,
            barcode_pdf,
            output_pdf,
            params,
            on_progress=self._on_merge_progress,
            on_complete=self._on_merge_complete,
            on_error=self._on_merge_error,
            skip_keyword=self.skip_keyword_var.get(),
        )
        self.merge_thread.start()

    def _on_merge_progress(self, current: int, total: int, message: str) -> None:
        """合并进度回调"""
        if self.is_closing:
            return
        try:
            self.root.after(0, lambda: self.log(message))
        except tk.TclError:
            pass

    def _on_merge_complete(self, result: Dict[str, Any]) -> None:
        """合并完成回调"""

        def on_complete_ui():
            if self.is_closing:
                return
            self.log("=" * 60)
            self.log("Merge completed successfully")
            self.log("=" * 60)
            self.log(f"Total barcode pages: {result['total_pages']}")
            self.log(f"Pages merged: {result['merged_count']}")
            self.log(f"Pages skipped: {result['skipped_count']}")

            if result["skipped_pages"]:
                self.log(f"Skipped page numbers: {result['skipped_pages']}")
            else:
                self.log("No pages matched the skip keyword")

            self.log(f"Output file: {result['output_path']}")
            self.log("=" * 60)

            messagebox.showinfo(
                APP_TITLE,
                f"PDF merged successfully:\n{result['output_path']}\n\n"
                f"Merged: {result['merged_count']} pages\n"
                f"Skipped: {result['skipped_count']} pages",
            )
            self.update_preview()

        if not self.is_closing:
            try:
                self.root.after(0, on_complete_ui)
            except tk.TclError:
                pass

    def _on_merge_error(self, error_message: str) -> None:
        """合并错误回调"""

        def on_error_ui():
            if self.is_closing:
                return
            self.log("=" * 60)
            self.log(f"Merge failed: {error_message}")
            self.log("=" * 60)
            messagebox.showerror(APP_TITLE, f"Merge failed:\n{error_message}")

        if not self.is_closing:
            try:
                self.root.after(0, on_error_ui)
            except tk.TclError:
                pass


def main():
    enable_high_dpi_awareness()
    root = tk.Tk()
    app = BarcodeMergerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
