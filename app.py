from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk


APP_NAME = "Damn Simple ComfyUI Manager"
PROJECT_REPOSITORY_URL = "https://github.com/m4ddok87/Damn-Simple-ComfyUI-Manager"
DEFAULT_INSTANCE_PREFIX = "ComfyUI"
BACKUP_ITEMS = [
    ("workflows", "folder"),
    ("subgraphs", "folder"),
    ("custom_nodes", "folder"),
    ("extra_model_paths.yaml", "file"),
]
CUSTOM_NODE_EXCLUDE_NAMES = {
    "_psycache_",
    "__pycache__",
    "example_node.py.example",
    "websocket_image_save.py",
}
FREEZE_SUFFIX = "FREEZE-NO-UPDATE"
UPDATED_SUFFIX = "UPDATED"
COMMON_MODELS_FOLDER_NAME = "common_models_folder"
BROWSER_CACHE_FOLDER_NAME = "browser_cache"
COMMON_MODEL_SUBFOLDERS = [
    "models/checkpoints",
    "models/text_encoders",
    "models/clip",
    "models/clip_vision",
    "models/configs",
    "models/controlnet",
    "models/diffusion_models",
    "models/unet",
    "models/embeddings",
    "models/loras",
    "models/upscale_models",
    "models/vae",
    "models/audio_encoders",
    "models/model_patches",
    "models/ultralytics",
    "models/latent_upscale_models",
]
GITHUB_RELEASES_API = "https://api.github.com/repos/comfyanonymous/ComfyUI/releases?per_page=50"
PORTABLE_GIT_RELEASE_API = "https://api.github.com/repos/git-for-windows/git/releases/latest"
FALLBACK_RELEASE = "latest"
FALLBACK_ASSETS = {
    "ComfyUI_windows_portable_amd.7z": "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_amd.7z",
    "ComfyUI_windows_portable_intel.7z": "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_intel.7z",
    "ComfyUI_windows_portable_nvidia.7z": "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z",
    "ComfyUI_windows_portable_nvidia_cu126.7z": "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia_cu126.7z",
}
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
STATE_FILE = APP_ROOT / "Damn Simple ComfyUI Manager_state.json"
ICON_PATH = (Path(getattr(sys, "_MEIPASS", APP_ROOT)) / "assets" / "DSCUIM.ico")
LOCAL_TEMP_DIR = APP_ROOT / "_temp"
LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = str(LOCAL_TEMP_DIR)
os.environ["TEMP"] = str(LOCAL_TEMP_DIR)
os.environ["TMPDIR"] = str(LOCAL_TEMP_DIR)
ASSET_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT)) / "assets"
BUNDLED_SEVEN_ZIP_PATH = ASSET_ROOT / "7zr.exe"
LOCAL_SEVEN_ZIP_PATH = APP_ROOT / "_tools" / "7zr.exe"
LOCAL_GIT_ROOT = APP_ROOT / "_tools" / "git"
LOCAL_TOOL_DOWNLOADS = APP_ROOT / "_tools" / "downloads"
COMFY_WHEEL_INDEX_BASES = [
    "https://comfy-org.github.io/wheels/",
    "https://comfy-org.github.io/wheels/v2/",
]
WILDMINDER_WHEELS_JSON_URL = "https://raw.githubusercontent.com/wildminder/AI-windows-whl/main/wheels.json"
WILDMINDER_WHEELS_PAGE_URL = "https://wildminder.github.io/AI-windows-whl/"


@dataclass
class ComfyInstance:
    name: str
    path: str
    created_at: float
    notes: str = ""

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()


class WorkFolderConfig:
    def __init__(self) -> None:
        self.work_folder: Path | None = None
        self.config_path: Path | None = None
        self.instances: list[ComfyInstance] = []
        self.preferences: dict[str, object] = {}
        self.backups: list[dict[str, object]] = []

    def load(self, folder: Path) -> None:
        self.work_folder = folder
        self.config_path = self._config_path_for(folder)
        if not self.config_path.exists():
            self.instances = []
            self.preferences = {}
            self.backups = []
            self.save()
            return
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            self.instances = [
                ComfyInstance(**item) for item in payload.get("instances", [])
            ]
            self.preferences = payload.get("preferences", {})
            self.backups = payload.get("backups", [])
        except (OSError, json.JSONDecodeError, TypeError):
            self.instances = []
            self.preferences = {}
            self.backups = []

    def save(self) -> None:
        if self.work_folder is None or self.config_path is None:
            return
        self.work_folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "app": APP_NAME,
            "work_folder": str(self.work_folder),
            "updated_at": time.time(),
            "instances": [asdict(item) for item in self.instances],
            "preferences": self.preferences,
            "backups": self.backups,
        }
        self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add(self, instance: ComfyInstance) -> None:
        same_path = Path(instance.path).resolve()
        self.instances = [
            item for item in self.instances if Path(item.path).resolve() != same_path
        ]
        self.instances.append(instance)
        self.instances.sort(key=lambda item: item.name.lower())
        self.save()

    def remove(self, path: str) -> None:
        target = Path(path).resolve()
        self.instances = [
            item for item in self.instances if Path(item.path).resolve() != target
        ]
        self.save()

    @staticmethod
    def _config_path_for(folder: Path) -> Path:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", folder.name).strip("._") or "work_folder"
        return folder / f"{safe_name}_config.json"


class AppState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_work_folder = ""
        self.work_folders: list[str] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.last_work_folder = payload.get("last_work_folder", "")
            self.work_folders = [
                item for item in payload.get("work_folders", []) if Path(item).exists()
            ]
        except (OSError, json.JSONDecodeError, TypeError):
            self.last_work_folder = ""
            self.work_folders = []

    def save(self) -> None:
        payload = {
            "app": APP_NAME,
            "last_work_folder": self.last_work_folder,
            "work_folders": self.work_folders,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def remember(self, folder: Path) -> None:
        value = str(folder.resolve())
        self.last_work_folder = value
        self.work_folders = [item for item in self.work_folders if Path(item).exists()]
        if value not in self.work_folders:
            self.work_folders.append(value)
        self.save()


class InstallationCancelled(Exception):
    pass


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.title(APP_NAME)
        self.geometry("1120x720")
        self.minsize(940, 620)
        self._apply_icon()
        self._ensure_dedicated_browser_helper()
        self.after(200, self._apply_app_titlebar_theme)

        self.app_state = AppState(STATE_FILE)
        self.config = WorkFolderConfig()
        self.selected_instance: ComfyInstance | None = None
        self.selected_backup_path: Path | None = None
        self.backup_infos: list[dict[str, object]] = []
        self.selected_start_bat = ""
        self.selected_update_bat = ""
        self.start_mode_var = tk.StringVar(value="Normal")
        self.selected_comfy_version = ""
        self.selected_portable_package = ""
        self.version_values: list[str] = []
        self.package_values: list[str] = []
        self.dropdown_popup: ctk.CTkToplevel | None = None
        self.dropdown_toggle_button: ctk.CTkButton | None = None
        self.dropdown_click_protected_until = 0.0
        self.release_assets: dict[str, dict[str, str]] = {}
        self.worker_messages: queue.Queue[str] = queue.Queue()
        self.install_in_progress = False
        self.install_cancel_requested = threading.Event()
        self.current_install_destination: Path | None = None
        self.install_locked_control_states: dict[tk.Misc, str] = {}
        self.dropdown_field_buttons: dict[ctk.CTkEntry, ctk.CTkButton] = {}
        self.dedicated_window_active = False
        self.disk_usage_request_id = 0
        self.disk_usage_cache: dict[str, dict[str, int]] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        if self._try_open_last_work_folder():
            self._build_workspace_shell()
        else:
            self._build_first_run()
        self.bind("<Button-1>", self._close_dropdown_on_outside_click, add="+")
        self.bind("<Escape>", lambda _event: self._close_dropdown_popup(), add="+")
        self.protocol("WM_DELETE_WINDOW", self._on_main_window_close)
        self.after(150, self._drain_worker_messages)

    def _apply_icon(self) -> None:
        if ICON_PATH.exists():
            try:
                self.iconbitmap(str(ICON_PATH))
            except Exception:
                pass

    def _on_main_window_close(self) -> None:
        if self.install_in_progress:
            self.bell()
            return
        self.destroy()

    def _ensure_dedicated_browser_helper(self) -> None:
        if not getattr(sys, "frozen", False):
            return
        bundled_browser = Path(getattr(sys, "_MEIPASS", APP_ROOT)) / "browser"
        target_browser = APP_ROOT / "browser"
        if not bundled_browser.exists():
            return
        try:
            if target_browser.exists():
                shutil.rmtree(target_browser)
            shutil.copytree(bundled_browser, target_browser)
        except OSError:
            pass

    def _apply_app_titlebar_theme(self) -> None:
        if os.name != "nt":
            return
        try:
            self._enable_windows_dark_app_mode()
            self.update_idletasks()
            self._apply_titlebar_theme_to_hwnd(self._native_window_handle(self))
        except Exception:
            pass

    @staticmethod
    def _system_uses_dark_titlebar() -> bool:
        try:
            import darkdetect
            return bool(darkdetect.isDark())
        except Exception:
            return ctk.get_appearance_mode().lower() == "dark"

    @staticmethod
    def _apply_titlebar_theme_to_hwnd(hwnd: int) -> None:
        if os.name != "nt" or not hwnd:
            return
        App._enable_windows_dark_app_mode()
        dark = App._system_uses_dark_titlebar()
        App._allow_dark_mode_for_window(hwnd, dark)
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd),
                    ctypes.c_int(attribute),
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
            except Exception:
                continue
        caption_color = ctypes.c_int(0x00202020 if dark else 0x00F3F4F6)
        text_color = ctypes.c_int(0x00FFFFFF if dark else 0x00111111)
        for attribute, color in ((35, caption_color), (36, text_color)):
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd),
                    ctypes.c_int(attribute),
                    ctypes.byref(color),
                    ctypes.sizeof(color),
                )
            except Exception:
                pass
        try:
            ctypes.windll.uxtheme.SetWindowTheme(
                wintypes.HWND(hwnd),
                "DarkMode_Explorer" if dark else "Explorer",
                None,
            )
        except Exception:
            pass

    @staticmethod
    def _enable_windows_dark_app_mode() -> None:
        if os.name != "nt":
            return
        try:
            uxtheme = ctypes.windll.uxtheme
            set_preferred_app_mode = getattr(uxtheme, "#135")
            set_preferred_app_mode.argtypes = [ctypes.c_int]
            set_preferred_app_mode.restype = ctypes.c_int
            set_preferred_app_mode(2 if App._system_uses_dark_titlebar() else 0)
        except Exception:
            pass
        try:
            refresh_policy = getattr(ctypes.windll.uxtheme, "#104")
            refresh_policy()
        except Exception:
            pass

    @staticmethod
    def _allow_dark_mode_for_window(hwnd: int, enabled: bool) -> None:
        try:
            allow_dark_mode = getattr(ctypes.windll.uxtheme, "#133")
            allow_dark_mode.argtypes = [wintypes.HWND, wintypes.BOOL]
            allow_dark_mode.restype = wintypes.BOOL
            allow_dark_mode(wintypes.HWND(hwnd), wintypes.BOOL(enabled))
        except Exception:
            pass

    @staticmethod
    def _apply_titlebar_theme_to_process_windows() -> None:
        if os.name != "nt":
            return
        current_pid = ctypes.windll.kernel32.GetCurrentProcessId()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, _lparam):
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == current_pid:
                App._apply_titlebar_theme_to_hwnd(hwnd)
            return True

        try:
            ctypes.windll.user32.EnumWindows(enum_proc, 0)
        except Exception:
            pass

    def _try_open_last_work_folder(self) -> bool:
        if not self.app_state.last_work_folder:
            return False
        folder = Path(self.app_state.last_work_folder)
        if not folder.exists():
            return False
        self.config.load(folder)
        self._ensure_common_models_folder()
        self._ensure_browser_cache_folder()
        return True

    def _build_first_run(self) -> None:
        self._clear_root()
        self.grid_rowconfigure(0, weight=1)
        panel = ctk.CTkFrame(self, corner_radius=16)
        panel.grid(row=0, column=0, sticky="", padx=24, pady=24)
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            panel,
            text="Select a work folder to continue.",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=34, pady=(30, 10))
        ctk.CTkButton(
            panel,
            text="Select Work Folder",
            command=self._create_new_work_folder,
            height=44,
            fg_color=("#c026d3", "#d946ef"),
            hover_color=("#a21caf", "#c026d3"),
        ).grid(row=1, column=0, sticky="ew", padx=34, pady=(10, 30))

    def _build_workspace_shell(self) -> None:
        self._clear_root()
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self._build_work_folder_bar()
        self._build_tabs()
        self._refresh_instances()
        self._refresh_backups()
        self.after(50, self._restore_last_selected_instance)

    def _build_work_folder_bar(self) -> None:
        bar = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 8))
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(bar, text="Work Folder", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        self.work_folder_label = ctk.CTkLabel(
            bar,
            text=str(self.config.work_folder or ""),
            anchor="w",
            text_color=("gray35", "gray72"),
        )
        self.work_folder_label.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.open_work_folder_button = ctk.CTkButton(
            bar,
            text="Open another Work Folder",
            width=190,
            command=self._open_work_folder_picker,
        )
        self.open_work_folder_button.grid(row=0, column=2, padx=(0, 8))
        self.create_work_folder_button = ctk.CTkButton(
            bar,
            text="Create New",
            width=128,
            command=self._create_new_work_folder,
            fg_color=("#7c3aed", "#a855f7"),
            hover_color=("#6d28d9", "#9333ea"),
        )
        self.create_work_folder_button.grid(row=0, column=3)

    def _build_tabs(self) -> None:
        self.tabs = ctk.CTkTabview(self, corner_radius=14, command=self._on_tab_changed)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=24, pady=(8, 24))
        self.tabs.add("Installed instances")
        self.tabs.add("New installation")
        self.tabs.add("Backup")
        self.tabs.add("About")
        self._build_manage_tab(self.tabs.tab("Installed instances"))
        self._build_install_tab(self.tabs.tab("New installation"))
        self._build_backup_tab(self.tabs.tab("Backup"))
        self._build_about_tab(self.tabs.tab("About"))

    def _on_tab_changed(self) -> None:
        self._close_dropdown_popup()

    def _build_manage_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=0, minsize=380)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(parent, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 8), pady=12)
        left.configure(width=380)
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left,
            text="ComfyUI Instances",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        self.instance_list = ctk.CTkScrollableFrame(left, corner_radius=10)
        self.instance_list.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self.instance_list.grid_columnconfigure(0, weight=1)

        add_row = ctk.CTkFrame(left, fg_color="transparent")
        add_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 12))
        add_row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            add_row,
            text="Add",
            command=self._add_existing,
            fg_color=("#2563eb", "#3b82f6"),
            hover_color=("#1d4ed8", "#2563eb"),
        ).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ctk.CTkButton(
            add_row,
            text="Refresh",
            command=self._refresh_instances,
            fg_color=("#6d5dfc", "#7a5cff"),
            hover_color=("#5b4bd4", "#674ce0"),
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ctk.CTkButton(
            left,
            text="Delete Instance",
            command=self._delete_selected_instance,
            fg_color=("#dc2626", "#ef4444"),
            hover_color=("#b91c1c", "#dc2626"),
        ).grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 14))

        right = ctk.CTkFrame(parent, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 12), pady=12)
        right.grid_columnconfigure(0, weight=1)

        self.detail_title = ctk.CTkLabel(
            right,
            text="Select an instance",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self.detail_title.grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        self.detail_path = ctk.CTkLabel(
            right,
            text="Add an existing ComfyUI folder to get started.",
            wraplength=560,
            justify="left",
            text_color=("gray35", "gray72"),
        )
        self.detail_path.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 20))

        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=20, pady=8)
        actions.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkButton(
            actions,
            text="Open folder",
            command=self._open_selected_folder,
            fg_color=("#2563eb", "#3b82f6"),
            hover_color=("#1d4ed8", "#2563eb"),
        ).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ctk.CTkButton(
            actions,
            text="Remove from list",
            command=self._remove_selected,
            fg_color=("#6d5dfc", "#7a5cff"),
            hover_color=("#5b4bd4", "#674ce0"),
        ).grid(row=0, column=1, sticky="ew", padx=8)
        ctk.CTkButton(
            actions,
            text="Backup",
            command=self._open_create_backup_dialog,
            fg_color=("#2563eb", "#3b82f6"),
            hover_color=("#1d4ed8", "#2563eb"),
        ).grid(row=0, column=2, sticky="ew", padx=(8, 0))

        start_row = ctk.CTkFrame(right, fg_color="transparent")
        start_row.grid(row=3, column=0, sticky="ew", padx=20, pady=(10, 4))
        start_row.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            start_row,
            text="Start Instance",
            command=self._start_selected_instance,
            fg_color=("#16a34a", "#22c55e"),
            hover_color=("#15803d", "#16a34a"),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.start_bat_entry = self._build_dropdown_field(
            start_row,
            "No root .bat found",
            lambda: self._choose_start_bat(),
            column=1,
        )
        mode_frame = ctk.CTkFrame(start_row, fg_color="transparent")
        mode_frame.grid(row=0, column=3, sticky="e", padx=(12, 0))
        self.start_mode_controls: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel]] = {}
        self._build_start_mode_option(mode_frame, "Browser", 0)
        self._build_start_mode_option(mode_frame, "Dedicated", 1)
        self._refresh_start_mode_controls()

        update_row = ctk.CTkFrame(right, fg_color="transparent")
        update_row.grid(row=4, column=0, sticky="ew", padx=20, pady=4)
        update_row.grid_columnconfigure(1, weight=1)
        self.update_instance_button = ctk.CTkButton(
            update_row,
            text="Update Instance",
            command=self._update_selected_instance,
            fg_color=("#2563eb", "#3b82f6"),
            hover_color=("#1d4ed8", "#2563eb"),
        )
        self.update_instance_button.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.update_bat_entry = self._build_dropdown_field(
            update_row,
            "No update .bat found",
            lambda: self._choose_update_bat(),
            column=1,
        )
        self.freeze_instance_button = ctk.CTkButton(
            update_row,
            text="Freeze Instance",
            width=150,
            command=self._freeze_selected_instance,
            fg_color=("#6d5dfc", "#7a5cff"),
            hover_color=("#5b4bd4", "#674ce0"),
        )
        self.freeze_instance_button.grid(row=0, column=3, sticky="ew", padx=(10, 0))

        tools = ctk.CTkFrame(right, fg_color="transparent")
        tools.grid(row=5, column=0, sticky="ew", padx=20, pady=(6, 8))
        tools.grid_columnconfigure(0, weight=0, minsize=255)
        tools.grid_columnconfigure(1, weight=1)
        tools.grid_rowconfigure((1, 2, 3), weight=1)
        self.comfyui_manager_button = ctk.CTkButton(
            tools,
            text="Install ComfyUI Manager",
            command=self._install_comfyui_manager,
            fg_color=("gray62", "gray32"),
            hover_color=("gray55", "gray40"),
        )
        self.comfyui_manager_button.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=4)
        ctk.CTkButton(
            tools,
            text="Update .yaml to Common Model Folder",
            command=self._connect_yaml_to_common_models,
            fg_color=("#2563eb", "#3b82f6"),
            hover_color=("#1d4ed8", "#2563eb"),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=4)
        self.disconnect_yaml_button = ctk.CTkButton(
            tools,
            text="Disconnect .yaml from Common Model Folder",
            command=self._disconnect_yaml_from_common_models,
            fg_color=("#dc2626", "#ef4444"),
            hover_color=("#b91c1c", "#dc2626"),
        )
        self.disconnect_yaml_button.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=4)
        self.library_panel_button = ctk.CTkButton(
            tools,
            text="Library Installation Panel",
            command=self._open_library_installation_panel,
            fg_color=("#c026d3", "#d946ef"),
            hover_color=("#a21caf", "#c026d3"),
        )
        self.library_panel_button.grid(row=2, column=0, sticky="ew", padx=(0, 6), pady=4)
        self.embedded_python_cmd_button = ctk.CTkButton(
            tools,
            text="Run Embedded Python cmd",
            command=self._run_embedded_python_cmd,
            fg_color=("gray62", "gray32"),
            hover_color=("gray55", "gray40"),
        )
        self.embedded_python_cmd_button.grid(row=3, column=0, sticky="ew", padx=(0, 6), pady=4)

        self.disk_usage_canvas = ctk.CTkCanvas(
            tools,
            height=118,
            highlightthickness=0,
            bd=0,
        )
        self.disk_usage_canvas.grid(row=1, column=1, rowspan=3, sticky="nsew", padx=(6, 0), pady=4)
        self.disk_usage_canvas.bind("<Configure>", lambda _event: self._refresh_disk_usage_graph(self.selected_instance, start_worker=False))
        self._draw_empty_disk_usage_graph()

        self.detail_box = ctk.CTkTextbox(right, height=260, corner_radius=10)
        self.detail_box.grid(row=6, column=0, sticky="nsew", padx=20, pady=(12, 20))
        right.grid_rowconfigure(6, weight=1)
        self._set_detail_text("Status, notes, and quick actions for the selected instance will appear here.")

    def _build_install_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        panel = ctk.CTkFrame(parent, corner_radius=12)
        panel.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(panel, text="Instance name").grid(row=0, column=0, sticky="w", padx=18, pady=(18, 8))
        self.new_name = ctk.CTkEntry(panel, placeholder_text="ComfyUI-version-hardware")
        self.new_name.grid(row=0, column=1, sticky="ew", padx=18, pady=(18, 8))

        ctk.CTkLabel(panel, text="ComfyUI version").grid(row=1, column=0, sticky="w", padx=18, pady=8)
        version_row = ctk.CTkFrame(panel, fg_color="transparent")
        version_row.grid(row=1, column=1, sticky="ew", padx=18, pady=8)
        version_row.grid_columnconfigure(0, weight=1)
        self.comfy_version_entry = self._build_dropdown_field(
            version_row,
            "Loading releases...",
            lambda: self._open_dropdown_popup("version"),
        )

        ctk.CTkLabel(panel, text="Portable package").grid(row=2, column=0, sticky="w", padx=18, pady=8)
        package_row = ctk.CTkFrame(panel, fg_color="transparent")
        package_row.grid(row=2, column=1, sticky="ew", padx=18, pady=8)
        package_row.grid_columnconfigure(0, weight=1)
        self.portable_package_entry = self._build_dropdown_field(
            package_row,
            "Loading packages...",
            lambda: self._open_dropdown_popup("package"),
        )

        ctk.CTkLabel(panel, text="Archive URL").grid(row=3, column=0, sticky="w", padx=18, pady=8)
        self.source_url = ctk.CTkEntry(panel)
        self.source_url.grid(row=3, column=1, sticky="ew", padx=18, pady=8)
        self.source_url.configure(state="disabled")

        install_actions = ctk.CTkFrame(panel, fg_color="transparent")
        install_actions.grid(row=4, column=1, sticky="e", padx=18, pady=(12, 18))
        self.cancel_install_button = ctk.CTkButton(
            install_actions,
            text="Cancel installation",
            command=self._request_cancel_installation,
            height=42,
            fg_color=("#dc2626", "#ef4444"),
            hover_color=("#b91c1c", "#dc2626"),
        )
        self.cancel_install_button.grid(row=0, column=0, padx=(0, 10))
        self.cancel_install_button.grid_remove()
        self.install_button = ctk.CTkButton(
            install_actions,
            text="Download and prepare instance",
            command=self._start_install,
            height=42,
            fg_color=("#2563eb", "#7c3aed"),
            hover_color=("#1d4ed8", "#6d28d9"),
        )
        self.install_button.grid(row=0, column=1)

        log_panel = ctk.CTkFrame(parent, corner_radius=12)
        log_panel.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 12))
        log_panel.grid_columnconfigure(0, weight=1)
        log_panel.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            log_panel,
            text="Installation log",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
        self.install_log = ctk.CTkTextbox(log_panel, corner_radius=10)
        self.install_log.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
        progress_row = ctk.CTkFrame(log_panel, fg_color="transparent")
        progress_row.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        progress_row.grid_columnconfigure(0, weight=1)
        self.install_progress = ctk.CTkProgressBar(progress_row)
        self.install_progress.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.install_progress.set(0)
        self.install_progress_label = ctk.CTkLabel(progress_row, text="0%", width=52)
        self.install_progress_label.grid(row=0, column=1)
        self.install_progress_status = ctk.CTkLabel(
            log_panel,
            text="Idle",
            anchor="w",
            text_color=("gray35", "gray72"),
        )
        self.install_progress_status.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 14))
        self._append_log("Ready. Installation files will be written only inside the selected work folder.")
        self._load_releases_async()

    def _build_backup_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=0, minsize=520)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(parent, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 8), pady=12)
        left.configure(width=520)
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left,
            text="Backups",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        self.backup_list = ctk.CTkScrollableFrame(left, corner_radius=10)
        self.backup_list.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self.backup_list.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            left,
            text="Refresh",
            command=self._refresh_backups,
            fg_color=("#6d5dfc", "#7a5cff"),
            hover_color=("#5b4bd4", "#674ce0"),
        ).grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 12))

        right = ctk.CTkFrame(parent, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 12), pady=12)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)

        self.backup_title = ctk.CTkLabel(
            right,
            text="Select a backup",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self.backup_title.grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        action_row = ctk.CTkFrame(right, fg_color="transparent")
        action_row.grid(row=1, column=0, sticky="ew", padx=20, pady=(8, 8))
        action_row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            action_row,
            text="Restore Backup",
            command=self._open_restore_backup_dialog,
            fg_color=("#7c3aed", "#a855f7"),
            hover_color=("#6d28d9", "#9333ea"),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            action_row,
            text="Delete Backup",
            command=self._delete_selected_backup,
            fg_color=("#dc2626", "#ef4444"),
            hover_color=("#b91c1c", "#dc2626"),
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self.backup_path_label = ctk.CTkLabel(
            right,
            text="",
            anchor="w",
            wraplength=620,
            text_color=("gray35", "gray72"),
        )
        self.backup_path_label.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 8))

        self.backup_detail_box = ctk.CTkTextbox(right, height=300, corner_radius=10)
        self.backup_detail_box.grid(row=3, column=0, sticky="nsew", padx=20, pady=(8, 20))
        self._set_backup_detail_text("Backup information will appear here.")

    def _build_about_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        panel = ctk.CTkFrame(parent, fg_color="transparent")
        panel.grid(row=0, column=0, sticky="")
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            panel,
            text="maddok, 2026",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, sticky="", padx=24, pady=(0, 8))
        repo_link = ctk.CTkLabel(
            panel,
            text=PROJECT_REPOSITORY_URL,
            font=ctk.CTkFont(size=14),
            text_color=("#2563eb", "#60a5fa"),
            cursor="hand2",
        )
        repo_link.grid(row=1, column=0, sticky="", padx=24, pady=(0, 0))
        repo_link.bind("<Button-1>", lambda _event: webbrowser.open(PROJECT_REPOSITORY_URL))

    def _open_work_folder_picker(self) -> None:
        if not self.app_state.work_folders:
            self._show_alert("No Work Folders", "No existing work folders are available yet.", "info")
            return
        if not self._ask_confirm("Open Work Folder", "Open another existing work folder?"):
            return

        picker = self._make_modal("Open Work Folder", 620, 360)
        picker.grid_columnconfigure(0, weight=1)
        picker.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            picker,
            text="Choose an existing work folder",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 8))

        list_frame = ctk.CTkScrollableFrame(picker, corner_radius=10)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=18, pady=(8, 18))
        list_frame.grid_columnconfigure(0, weight=1)

        folders = [Path(item) for item in self.app_state.work_folders if Path(item).exists()]
        for index, folder in enumerate(folders):
            ctk.CTkButton(
                list_frame,
                text=str(folder),
                anchor="w",
                command=lambda value=folder: self._select_existing_work_folder(value, picker),
            ).grid(row=index, column=0, sticky="ew", padx=8, pady=5)

    def _select_existing_work_folder(self, folder: Path, window: ctk.CTkToplevel) -> None:
        window.destroy()
        self._set_work_folder(folder)

    def _create_new_work_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select Work Folder")
        if not folder:
            return
        self._set_work_folder(Path(folder))

    def _set_work_folder(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.config.load(folder)
        self._ensure_common_models_folder()
        self._ensure_browser_cache_folder()
        self.app_state.remember(folder)
        self.selected_instance = None
        self._build_workspace_shell()

    def _ensure_common_models_folder(self) -> Path | None:
        if self.config.work_folder is None:
            return None
        common_folder = self.config.work_folder / COMMON_MODELS_FOLDER_NAME
        common_folder.mkdir(parents=True, exist_ok=True)
        for relative in COMMON_MODEL_SUBFOLDERS:
            (common_folder / relative).mkdir(parents=True, exist_ok=True)
        return common_folder

    def _ensure_browser_cache_folder(self) -> Path | None:
        if self.config.work_folder is None:
            return None
        browser_cache = self.config.work_folder / BROWSER_CACHE_FOLDER_NAME
        browser_cache.mkdir(parents=True, exist_ok=True)
        return browser_cache

    def _load_releases_async(self) -> None:
        if hasattr(self, "comfy_version_entry"):
            self._set_entry_display(self.comfy_version_entry, "Loading releases...")
        if hasattr(self, "portable_package_entry"):
            self.package_values = []
            self._set_entry_display(self.portable_package_entry, "Loading packages...")
        self._set_archive_url("")
        self._append_log("Fetching ComfyUI releases from GitHub...")
        thread = threading.Thread(target=self._load_releases_worker, daemon=True)
        thread.start()

    def _load_releases_worker(self) -> None:
        try:
            request = urllib.request.Request(
                GITHUB_RELEASES_API,
                headers={"User-Agent": APP_NAME},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                releases = json.loads(response.read().decode("utf-8"))
            release_assets: dict[str, dict[str, str]] = {}
            for release in releases:
                tag = release.get("tag_name", "")
                assets = {}
                for asset in release.get("assets", []):
                    name = asset.get("name", "")
                    url = asset.get("browser_download_url", "")
                    if self._is_portable_asset(name) and url:
                        assets[name] = url
                if tag and assets:
                    release_assets[tag] = dict(sorted(assets.items()))
            if not release_assets:
                raise ValueError("No portable release assets found.")
            self.after(0, lambda: self._apply_release_assets(release_assets, from_fallback=False))
        except Exception as exc:
            self.after(0, lambda: self._apply_release_assets({FALLBACK_RELEASE: FALLBACK_ASSETS}, from_fallback=True, error=str(exc)))

    def _apply_release_assets(
        self,
        release_assets: dict[str, dict[str, str]],
        from_fallback: bool = False,
        error: str = "",
    ) -> None:
        self.release_assets = release_assets
        versions = list(release_assets.keys())
        self.version_values = versions
        self._comfy_version_changed(versions[0])
        if from_fallback:
            self._append_log(f"GitHub release fetch failed. Using fallback package list. {error}")
        else:
            package_count = sum(len(assets) for assets in release_assets.values())
            self._append_log(f"Loaded {len(release_assets)} ComfyUI releases and {package_count} portable packages from GitHub.")

    def _comfy_version_changed(self, value: str) -> None:
        self.selected_comfy_version = value
        self._set_entry_display(self.comfy_version_entry, value)
        assets = self.release_assets.get(value, {})
        names = list(assets.keys()) or ["No portable packages found"]
        self.package_values = names
        self._portable_package_changed(names[0])

    def _portable_package_changed(self, value: str) -> None:
        self.selected_portable_package = value
        self._set_entry_display(self.portable_package_entry, value)
        version = self.selected_comfy_version
        url = self.release_assets.get(version, {}).get(value, "")
        self._set_archive_url(url)

    def _build_dropdown_field(self, parent: ctk.CTkFrame, text: str, command, column: int = 0) -> ctk.CTkEntry:
        entry = ctk.CTkEntry(parent)
        entry.insert(0, text)
        entry.configure(state="disabled")
        entry.grid(row=0, column=column, sticky="ew", padx=(0, 8))
        button = ctk.CTkButton(parent, text="▼", width=42, text_color="#ffffff", font=ctk.CTkFont(size=13, weight="bold"))
        button.configure(command=lambda: self._toggle_dropdown_from_button(button, command))
        button.grid(row=0, column=column + 1)
        self.dropdown_field_buttons[entry] = button
        return entry

    @staticmethod
    def _set_entry_display(entry: ctk.CTkEntry, value: str) -> None:
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, value)
        entry.configure(state="disabled")

    def _build_start_mode_option(self, parent: ctk.CTkFrame, label: str, column: int) -> None:
        option = ctk.CTkFrame(parent, fg_color="transparent", cursor="hand2")
        option.grid(row=0, column=column, padx=(0, 10) if column == 0 else (0, 0))
        indicator = ctk.CTkLabel(option, text="○", width=22, font=ctk.CTkFont(family="Segoe UI Symbol", size=24, weight="bold"), cursor="hand2")
        indicator.grid(row=0, column=0, padx=(0, 5))
        text_label = ctk.CTkLabel(option, text=label, cursor="hand2")
        text_label.grid(row=0, column=1)
        self.start_mode_controls[label] = (indicator, text_label)
        mode_value = "Normal" if label == "Browser" else label
        for widget in (option, indicator, text_label):
            widget.bind("<Button-1>", lambda _event, value=mode_value: self._set_start_mode(value))

    def _refresh_start_mode_controls(self) -> None:
        if not hasattr(self, "start_mode_controls"):
            return
        selected = self.start_mode_var.get()
        for label, (indicator, _text_label) in self.start_mode_controls.items():
            is_selected = label == selected or (label == "Browser" and selected == "Normal")
            is_dark = ctk.get_appearance_mode().lower() == "dark"
            fill = "#3b82f6" if is_dark else "#2563eb"
            outline = fill if is_selected else ("#ffffff" if is_dark else "#374151")
            if is_selected:
                indicator.configure(text="●", text_color=fill)
            else:
                indicator.configure(text="○", text_color=outline)

    @staticmethod
    def _canvas_bg_color() -> str:
        return "#242424" if ctk.get_appearance_mode().lower() == "dark" else "#ebebeb"

    def _open_dropdown_popup(self, kind: str) -> None:
        self._close_dropdown_popup()
        values = self.version_values if kind == "version" else self.package_values
        entry = self.comfy_version_entry if kind == "version" else self.portable_package_entry
        if not values:
            return

        self._protect_dropdown_opening_click()
        self.dropdown_popup = ctk.CTkToplevel(self)
        self.dropdown_popup.overrideredirect(True)
        self.dropdown_popup.transient(self)
        x = entry.winfo_rootx()
        y = entry.winfo_rooty() + entry.winfo_height() + 4
        width = entry.winfo_width() + 50
        self.dropdown_popup.geometry(f"{width}x260+{x}+{y}")
        self.dropdown_popup.grid_columnconfigure(0, weight=1)
        self.dropdown_popup.grid_rowconfigure(0, weight=1)

        list_frame = ctk.CTkScrollableFrame(self.dropdown_popup, corner_radius=8)
        list_frame.grid(row=0, column=0, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)
        for index, value in enumerate(values):
            ctk.CTkButton(
                list_frame,
                text=value,
                anchor="w",
                fg_color=("gray87", "gray22"),
                text_color=("gray10", "gray92"),
                hover_color=("gray78", "gray30"),
                command=lambda selected=value, popup_kind=kind: self._select_dropdown_value(popup_kind, selected),
            ).grid(row=index, column=0, sticky="ew", padx=6, pady=4)

    def _select_dropdown_value(self, kind: str, value: str) -> None:
        self._close_dropdown_popup()
        if kind == "version":
            self._comfy_version_changed(value)
        else:
            self._portable_package_changed(value)

    def _close_dropdown_popup(self) -> None:
        if self.dropdown_popup is not None and self.dropdown_popup.winfo_exists():
            self.dropdown_popup.destroy()
        self.dropdown_popup = None
        if self.dropdown_toggle_button is not None:
            try:
                self.dropdown_toggle_button.configure(text="▼")
            except tk.TclError:
                pass
        self.dropdown_toggle_button = None

    def _toggle_dropdown_from_button(self, button: ctk.CTkButton, open_command) -> None:
        if self.dropdown_popup is not None and self.dropdown_popup.winfo_exists() and self.dropdown_toggle_button == button:
            self._close_dropdown_popup()
            return
        self._close_dropdown_popup()
        self.dropdown_toggle_button = button
        open_command()
        if self.dropdown_popup is not None and self.dropdown_popup.winfo_exists():
            self.dropdown_toggle_button = button
            button.configure(text="▲")
        else:
            self.dropdown_toggle_button = None
            button.configure(text="▼")

    def _close_dropdown_on_outside_click(self, event: tk.Event) -> None:
        if self.dropdown_popup is None or not self.dropdown_popup.winfo_exists():
            return
        if time.monotonic() < self.dropdown_click_protected_until:
            return
        try:
            if event.widget.winfo_toplevel() == self.dropdown_popup:
                return
        except tk.TclError:
            return
        self._close_dropdown_popup()

    def _protect_dropdown_opening_click(self) -> None:
        self.dropdown_click_protected_until = time.monotonic() + 0.25

    def _set_archive_url(self, url: str) -> None:
        self.source_url.configure(state="normal")
        self.source_url.delete(0, "end")
        self.source_url.insert(0, url)
        self.source_url.configure(state="disabled")
        self._update_instance_placeholder()

    @staticmethod
    def _is_portable_asset(name: str) -> bool:
        lowered = name.lower()
        return (
            lowered.startswith("comfyui_windows_portable_")
            and lowered.endswith(".7z")
            and "source" not in lowered
            and "archive" not in lowered
            and "attestation" not in lowered
        )

    def _update_instance_placeholder(self) -> None:
        if not hasattr(self, "new_name"):
            return
        self.new_name.configure(placeholder_text=self._default_instance_name())

    def _default_instance_name(self) -> str:
        version = self._version_slug(self.selected_comfy_version)
        hardware = self._hardware_slug(self.selected_portable_package)
        return f"{DEFAULT_INSTANCE_PREFIX}-{version}-{hardware}"

    @staticmethod
    def _version_slug(version: str) -> str:
        match = re.search(r"\d+(?:\.\d+)+", version)
        if match:
            return match.group(0).replace(".", "-")
        cleaned = re.sub(r"[^A-Za-z0-9]+", "-", version).strip("-")
        return cleaned or "latest"

    @staticmethod
    def _hardware_slug(package_name: str) -> str:
        lowered = package_name.lower()
        if "nvidia_cu126" in lowered:
            return "nvidia-cu126"
        if "nvidia" in lowered:
            return "nvidia"
        if "intel" in lowered:
            return "intel"
        if "amd" in lowered:
            return "amd"
        return "portable"

    @staticmethod
    def _safe_folder_name(name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip(".- ")
        return cleaned

    def _refresh_instances(self) -> None:
        for child in self.instance_list.winfo_children():
            child.destroy()
        if not self.config.instances:
            ctk.CTkLabel(
                self.instance_list,
                text="No registered instances.",
                text_color=("gray35", "gray72"),
            ).grid(row=0, column=0, sticky="ew", padx=10, pady=12)
            return
        for index, instance in enumerate(self.config.instances):
            status = "OK" if instance.exists else "Missing"
            button = ctk.CTkButton(
                self.instance_list,
                text=f"{instance.name}   [{status}]",
                anchor="w",
                command=lambda item=instance: self._select_instance(item),
                fg_color=("gray87", "gray22"),
                text_color=("gray10", "gray92"),
                hover_color=("gray78", "gray30"),
            )
            button.grid(row=index, column=0, sticky="ew", padx=6, pady=5)

    def _restore_last_selected_instance(self) -> None:
        if self.selected_instance is not None:
            return
        last_path = str(self.config.preferences.get("last_selected_instance_path", "")).strip()
        last_name = str(self.config.preferences.get("last_selected_instance_name", "")).strip()
        match = None
        if last_path:
            try:
                target = Path(last_path).resolve()
                match = next((item for item in self.config.instances if Path(item.path).resolve() == target), None)
            except OSError:
                match = None
        if match is None and last_name:
            match = next((item for item in self.config.instances if item.name == last_name), None)
        if match is not None:
            self._select_instance(match)

    def _select_instance(self, instance: ComfyInstance) -> None:
        self.selected_instance = instance
        self.config.preferences["last_selected_instance_path"] = instance.path
        self.config.preferences["last_selected_instance_name"] = instance.name
        self.config.save()
        self.detail_title.configure(text=instance.name)
        self.detail_path.configure(text=instance.path)
        self._refresh_instance_action_fields(instance)
        created = time.strftime("%Y-%m-%d %H:%M", time.localtime(instance.created_at))
        status = "folder found" if instance.exists else "folder not found"
        backup_summary = self._instance_backup_summary(instance)
        backup_text = "No backup saved."
        if backup_summary["count"]:
            backup_text = (
                f"{backup_summary['count']} backup(s) saved.\n"
                f"Latest backup: {self._format_timestamp(backup_summary['latest'])}"
            )
        common_status = self._common_model_status(instance)
        common_label = "connected" if common_status["connected"] else "not connected"
        common_paths = common_status["common_paths"]
        internal_paths = common_status["internal_paths"]
        common_text = "\n".join(f"- {path}" for path in common_paths) if common_paths else "- None found"
        internal_text = "\n".join(f"- {path}" for path in internal_paths) if internal_paths else "- None found"
        comfy_root = self._resolve_comfy_root(Path(instance.path))
        custom_nodes = self._list_custom_nodes(comfy_root / "custom_nodes")
        custom_nodes_text = "\n".join(f"- {node}" for node in custom_nodes) if custom_nodes else "- None found"
        triton_status = "installed" if self._is_triton_installed(instance) else "not installed"
        ultralytics_status = "installed" if self._is_ultralytics_installed(instance) else "not installed"
        sage_attention_status = "installed" if self._is_sage_attention_installed(instance) else "not installed"
        flash_attention_status = "installed" if self._is_flash_attention_installed(instance) else "not installed"
        self._set_detail_text(
            f"Status: {status}\n"
            f"Created/registered: {created}\n"
            f"Disk Usage: calculating...\n"
            f"Backup: {backup_text}\n"
            f"Triton: {triton_status}\n"
            f"Ultralytics: {ultralytics_status}\n"
            f"Sage Attention: {sage_attention_status}\n"
            f"Flash Attention: {flash_attention_status}\n"
            f"Common model folder: {common_label}\n\n"
            f"Custom nodes:\n{custom_nodes_text}\n\n"
            f"Common model paths:\n{common_text}\n\n"
            f"Internal model paths:\n{internal_text}\n\n"
            f"Notes:\n{instance.notes or 'No notes.'}"
        )
        cached_usage = self.disk_usage_cache.get(self._disk_usage_cache_key(instance))
        if cached_usage:
            self._set_detail_disk_usage(self._format_disk_usage_detail(cached_usage["instance_bytes"]))
        self._refresh_disk_usage_graph(instance)

    def _refresh_disk_usage_graph(self, instance: ComfyInstance | None, start_worker: bool = True) -> None:
        if not hasattr(self, "disk_usage_canvas"):
            return
        if instance is None:
            self._draw_empty_disk_usage_graph()
            return
        cache_key = self._disk_usage_cache_key(instance)
        cached_usage = self.disk_usage_cache.get(cache_key)
        if cached_usage:
            self._draw_disk_usage_from_snapshot(cached_usage)
        else:
            self._draw_empty_disk_usage_graph("Calculating disk usage...")
        if not start_worker:
            return
        self.disk_usage_request_id += 1
        request_id = self.disk_usage_request_id
        threading.Thread(
            target=self._calculate_disk_usage_worker,
            args=(request_id, instance, cache_key),
            daemon=True,
        ).start()

    def _calculate_disk_usage_worker(self, request_id: int, instance: ComfyInstance, cache_key: str) -> None:
        snapshot = self._calculate_disk_usage_snapshot(instance)
        self.after(0, lambda: self._apply_disk_usage_snapshot(request_id, instance.path, cache_key, snapshot))

    def _calculate_disk_usage_snapshot(self, instance: ComfyInstance) -> dict[str, int] | None:
        folder = Path(instance.path)
        instance_bytes = self._folder_size_bytes(folder)
        if instance_bytes is None:
            return None
        try:
            usage = shutil.disk_usage(folder)
        except OSError:
            return None
        common_bytes = 0
        common_status = self._common_model_status(instance)
        if common_status["connected"]:
            common_folder = self._ensure_common_models_folder()
            if common_folder is not None:
                common_size = self._folder_size_bytes(common_folder)
                if common_size is not None:
                    common_bytes = common_size
        other_instances_bytes = self._other_instances_size_bytes(instance)
        work_folder_total_bytes = 0
        work_folder_residual_bytes = 0
        if self.config.work_folder is not None:
            work_size = self._folder_size_bytes(self.config.work_folder)
            if work_size is not None:
                work_folder_total_bytes = work_size
                work_folder_residual_bytes = max(work_size - instance_bytes - other_instances_bytes - common_bytes, 0)
        other_used = max(usage.used - work_folder_total_bytes, 0)
        return {
            "instance_bytes": instance_bytes,
            "other_instances_bytes": other_instances_bytes,
            "common_bytes": common_bytes,
            "work_folder_residual_bytes": work_folder_residual_bytes,
            "work_folder_total_bytes": work_folder_total_bytes,
            "other_used": other_used,
            "free_bytes": usage.free,
            "total_bytes": usage.total,
        }

    def _apply_disk_usage_snapshot(
        self,
        request_id: int,
        instance_path: str,
        cache_key: str,
        snapshot: dict[str, int] | None,
    ) -> None:
        if request_id != self.disk_usage_request_id:
            return
        if self.selected_instance is None or self.selected_instance.path != instance_path:
            return
        if snapshot is None:
            self._draw_empty_disk_usage_graph("Disk usage not available")
            self._set_detail_disk_usage("not available")
            return
        self.disk_usage_cache[cache_key] = snapshot
        self._set_detail_disk_usage(self._format_disk_usage_detail(snapshot["instance_bytes"]))
        self._draw_disk_usage_from_snapshot(snapshot)

    def _draw_disk_usage_from_snapshot(self, snapshot: dict[str, int]) -> None:
        self._draw_disk_usage_graph(
            snapshot["instance_bytes"],
            snapshot["other_instances_bytes"],
            snapshot["common_bytes"],
            snapshot["work_folder_residual_bytes"],
            snapshot["work_folder_total_bytes"],
            snapshot["other_used"],
            snapshot["free_bytes"],
            snapshot["total_bytes"],
        )

    def _set_detail_disk_usage(self, value: str) -> None:
        if not hasattr(self, "detail_box"):
            return
        self.detail_box.configure(state="normal")
        text = self.detail_box.get("1.0", "end-1c")
        text = re.sub(r"^Disk Usage: .*$", f"Disk Usage: {value}", text, count=1, flags=re.MULTILINE)
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", text)
        self.detail_box.configure(state="disabled")

    def _disk_usage_cache_key(self, instance: ComfyInstance) -> str:
        try:
            return str(Path(instance.path).resolve()).casefold()
        except OSError:
            return str(Path(instance.path)).casefold()

    @staticmethod
    def _format_disk_usage_detail(size_bytes: int) -> str:
        return f"{size_bytes / (1024 * 1024):,.1f} MB"

    def _other_instances_size_bytes(self, selected_instance: ComfyInstance) -> int:
        selected_path = Path(selected_instance.path)
        try:
            selected_resolved = selected_path.resolve()
        except OSError:
            selected_resolved = selected_path
        selected_key = str(selected_resolved).casefold()
        total = 0
        seen_paths: set[str] = set()
        for instance in self.config.instances:
            folder = Path(instance.path)
            try:
                resolved = folder.resolve()
            except OSError:
                resolved = folder
            resolved_key = str(resolved).casefold()
            if resolved_key == selected_key or resolved_key in seen_paths:
                continue
            seen_paths.add(resolved_key)
            size = self._folder_size_bytes(folder)
            if size is not None:
                total += size
        return total

    def _draw_empty_disk_usage_graph(self, message: str = "Select an instance") -> None:
        if not hasattr(self, "disk_usage_canvas"):
            return
        canvas = self.disk_usage_canvas
        canvas.delete("all")
        canvas.configure(bg=self._canvas_bg_color())
        width = max(canvas.winfo_width(), 260)
        height = max(canvas.winfo_height(), 78)
        text_color = "#ffffff" if ctk.get_appearance_mode().lower() == "dark" else "#374151"
        canvas.create_text(width / 2, height / 2, text=message, fill=text_color, font=("Segoe UI", 9))

    def _draw_disk_usage_graph(
        self,
        instance_bytes: int,
        other_instances_bytes: int,
        common_bytes: int,
        work_folder_residual_bytes: int,
        work_folder_total_bytes: int,
        other_bytes: int,
        free_bytes: int,
        total_bytes: int,
    ) -> None:
        canvas = self.disk_usage_canvas
        canvas.delete("all")
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        bg = self._canvas_bg_color()
        canvas.configure(bg=bg)
        width = max(canvas.winfo_width(), 260)
        height = max(canvas.winfo_height(), 118)
        pad_x = 14
        bar_height = 14
        radius = bar_height // 2
        bar_y = max(52, (height - bar_height) // 2 + 4)
        bar_width = max(width - pad_x * 2, 1)
        total = max(total_bytes, 1)

        free_color = "#ffffff" if is_dark else "#f8fafc"
        other_color = "#a3a3a3" if is_dark else "#c7cbd1"
        instance_color = "#3b82f6"
        other_instances_color = "#38bdf8"
        common_color = "#facc15"
        work_folder_color = "#a855f7"
        outline = "#4b5563" if is_dark else "#9ca3af"
        label_color = "#ffffff" if is_dark else "#111827"
        muted_label = "#e5e7eb" if is_dark else "#4b5563"
        guide_color = "#ffffff" if is_dark else "#6b7280"
        canvas.create_text(
            width - pad_x,
            3,
            text="Disk Usage",
            anchor="ne",
            fill=label_color,
            font=("Segoe UI", 8, "bold"),
        )

        used_segments = [
            {"name": "Instance", "label": "Instance", "bytes": instance_bytes, "color": instance_color, "minimum": radius * 2},
            {"name": "Other Instances", "label": "Other Instances", "bytes": other_instances_bytes, "color": other_instances_color, "minimum": radius * 2},
            {"name": "Common Model Folder", "label": "Common Model Folder", "bytes": common_bytes, "color": common_color, "minimum": radius * 2},
            {
                "name": "Work Folder",
                "label": "Work Folder",
                "bytes": work_folder_residual_bytes,
                "display_bytes": work_folder_total_bytes,
                "color": work_folder_color,
                "minimum": radius * 2,
            },
            {"name": "Other", "label": "Other", "bytes": other_bytes, "color": muted_label, "minimum": 0},
        ]
        visible_segments = [segment for segment in used_segments if int(segment["bytes"]) > 0]
        for segment in visible_segments:
            segment["width"] = self._segment_width(int(segment["bytes"]), total, bar_width)
            if int(segment["minimum"]) > 0:
                segment["width"] = max(int(segment["width"]), int(segment["minimum"]))
        used_width = sum(int(segment["width"]) for segment in visible_segments)
        if used_width > bar_width:
            overflow = used_width - bar_width
            for segment in reversed(visible_segments):
                minimum = int(segment["minimum"])
                current = int(segment["width"])
                reduction = min(overflow, max(current - minimum, 0))
                if reduction:
                    segment["width"] = current - reduction
                    overflow -= reduction
                if overflow <= 0:
                    break
        free_width = max(bar_width - sum(int(segment["width"]) for segment in visible_segments), 0)
        if free_width == 0 and free_bytes > 0:
            free_width = 1
            for segment in reversed(visible_segments):
                minimum = int(segment["minimum"])
                current = int(segment["width"])
                if current > minimum:
                    segment["width"] = current - 1
                    break

        x0 = pad_x
        x_end = pad_x + bar_width
        self._draw_rounded_bar(canvas, x0, bar_y, x_end, bar_y + bar_height, radius, free_color, outline)
        cursor = x0
        for index, segment in enumerate(visible_segments):
            segment_width = int(segment["width"])
            next_cursor = cursor + segment_width
            segment["start"] = cursor
            segment["end"] = next_cursor
            draw_start = cursor if index == 0 else cursor - 1
            if index == 0:
                self._draw_left_rounded_segment(canvas, cursor, bar_y, next_cursor, bar_y + bar_height, radius, str(segment["color"]))
            else:
                canvas.create_rectangle(draw_start, bar_y, next_cursor, bar_y + bar_height, fill=str(segment["color"]), outline="")
            cursor = next_cursor
        self._draw_rounded_outline(canvas, x0, bar_y, x_end, bar_y + bar_height, radius, outline)

        label_sides = {
            "Instance": "top",
            "Common Model Folder": "top",
            "Other": "top",
            "Other Instances": "bottom",
            "Work Folder": "bottom",
        }
        label_items = []
        for segment in visible_segments:
            side = label_sides.get(str(segment["name"]))
            if side is None:
                continue
            segment_x = (float(segment["start"]) + float(segment["end"])) / 2
            label_items.append({"segment": segment, "side": side, "target_x": segment_x})

        for side, label_y, min_gap in (("top", 19, 88), ("bottom", height - 23, 96)):
            side_items = [item for item in label_items if item["side"] == side]
            for item, label_x in self._spread_disk_label_positions(side_items, x0, x_end, min_gap):
                segment = item["segment"]
                segment_x = float(item["target_x"])
                if side == "top":
                    bar_anchor_y = bar_y - 3
                    elbow_y = bar_y - 12
                    label_anchor_y = label_y + 18
                else:
                    bar_anchor_y = bar_y + bar_height + 3
                    elbow_y = bar_y + bar_height + 10
                    label_anchor_y = label_y - 11
                canvas.create_line(
                    segment_x,
                    bar_anchor_y,
                    segment_x,
                    elbow_y,
                    label_x,
                    elbow_y,
                    label_x,
                    label_anchor_y,
                    fill=guide_color,
                    width=1,
                )
                available_width = 112 if segment["name"] == "Common Model Folder" else 86
                label_name = self._wrap_disk_label(str(segment["label"]), available_width)
                label_text = f"{label_name}\n{self._format_storage_size(int(segment.get('display_bytes', segment['bytes'])))}"
                canvas.create_text(
                    label_x,
                    label_y,
                    text=label_text,
                    anchor="center",
                    fill=str(segment["color"]),
                    font=("Segoe UI", 7),
                )

        free_pct = free_bytes / total * 100
        percent_y = bar_y + bar_height + 8
        canvas.create_text(x_end, percent_y, text=f"{free_pct:.1f}% free", anchor="e", fill=label_color, font=("Segoe UI", 7, "bold"))

    @staticmethod
    def _wrap_disk_label(label: str, max_width_px: int) -> str:
        if len(label) * 4 <= max_width_px:
            return label
        max_chars = max(8, max_width_px // 4)
        lines: list[str] = []
        current = ""
        for word in label.split():
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > max_chars:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return "\n".join(lines)

    @staticmethod
    def _spread_disk_label_positions(items: list[dict[str, object]], x0: float, x1: float, min_gap: int) -> list[tuple[dict[str, object], float]]:
        if not items:
            return []
        margin = 36
        ordered = sorted(items, key=lambda item: float(item["target_x"]))
        positions = [min(max(float(item["target_x"]), x0 + margin), x1 - margin) for item in ordered]
        for index in range(1, len(positions)):
            positions[index] = max(positions[index], positions[index - 1] + min_gap)
        overflow = positions[-1] - (x1 - margin)
        if overflow > 0:
            positions = [position - overflow for position in positions]
        for index in range(len(positions) - 2, -1, -1):
            positions[index] = min(positions[index], positions[index + 1] - min_gap)
        underflow = (x0 + margin) - positions[0]
        if underflow > 0:
            positions = [position + underflow for position in positions]
        return list(zip(ordered, positions))

    @staticmethod
    def _segment_width(size_bytes: int, total_bytes: int, bar_width: int) -> int:
        if size_bytes <= 0:
            return 0
        width = int(round(size_bytes / max(total_bytes, 1) * bar_width))
        return max(width, 2)

    @staticmethod
    def _format_storage_size(size_bytes: int) -> str:
        gib = size_bytes / (1024 ** 3)
        if gib >= 1:
            return f"{gib:,.1f} GB"
        return f"{size_bytes / (1024 ** 2):,.1f} MB"

    @staticmethod
    def _draw_rounded_bar(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, radius: int, fill: str, outline: str) -> None:
        canvas.create_rectangle(x0 + radius, y0, x1 - radius, y1, fill=fill, outline="")
        canvas.create_oval(x0, y0, x0 + radius * 2, y1, fill=fill, outline="")
        canvas.create_oval(x1 - radius * 2, y0, x1, y1, fill=fill, outline="")
        App._draw_rounded_outline(canvas, x0, y0, x1, y1, radius, outline)

    @staticmethod
    def _draw_rounded_outline(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, radius: int, outline: str) -> None:
        canvas.create_line(x0 + radius, y0, x1 - radius, y0, fill=outline)
        canvas.create_line(x0 + radius, y1, x1 - radius, y1, fill=outline)
        canvas.create_arc(x0, y0, x0 + radius * 2, y1, start=90, extent=180, outline=outline, style="arc")
        canvas.create_arc(x1 - radius * 2, y0, x1, y1, start=-90, extent=180, outline=outline, style="arc")

    @staticmethod
    def _draw_left_rounded_segment(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, radius: int, fill: str) -> None:
        if x1 <= x0:
            return
        canvas.create_rectangle(x0 + radius, y0, x1, y1, fill=fill, outline="")
        canvas.create_oval(x0, y0, x0 + radius * 2, y1, fill=fill, outline="")
        canvas.create_rectangle(x0 + radius, y0, x1, y1, fill=fill, outline="")

    @staticmethod
    def _folder_size_bytes(folder: Path) -> int | None:
        if not folder.exists() or not folder.is_dir():
            return None
        total = 0
        stack = [folder]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue
        return total

    def _refresh_instance_action_fields(self, instance: ComfyInstance) -> None:
        settings = self._get_instance_settings(instance)
        start_values = self._list_instance_root_bats(instance)
        update_values = self._list_instance_update_bats(instance)
        self.selected_start_bat = self._preferred_bat(str(settings.get("start_bat", "")), start_values)
        self.selected_update_bat = self._preferred_bat(str(settings.get("update_bat", "")), update_values)
        start_mode = str(settings.get("start_mode", "Normal"))
        if start_mode not in {"Normal", "Dedicated"}:
            start_mode = "Normal"
        self.start_mode_var.set(start_mode)
        self._refresh_start_mode_controls()
        if hasattr(self, "start_bat_entry"):
            self._set_entry_display(self.start_bat_entry, self.selected_start_bat or "No root .bat found")
        if hasattr(self, "update_bat_entry"):
            self._set_entry_display(self.update_bat_entry, self.selected_update_bat or "No update .bat found")
        frozen = self._is_instance_frozen(instance)
        if hasattr(self, "update_instance_button"):
            self.update_instance_button.configure(state="disabled" if frozen else "normal")
        if hasattr(self, "freeze_instance_button"):
            self.freeze_instance_button.configure(state="disabled" if frozen else "normal")
        if hasattr(self, "comfyui_manager_button"):
            manager_text = "Re-install ComfyUI Manager" if self._comfyui_manager_path(instance).exists() else "Install ComfyUI Manager"
            self.comfyui_manager_button.configure(text=manager_text, state="normal")
        if hasattr(self, "disconnect_yaml_button"):
            active_yaml = self._resolve_comfy_root(Path(instance.path)) / "extra_model_paths.yaml"
            self.disconnect_yaml_button.configure(state="normal" if active_yaml.exists() else "disabled")
        if hasattr(self, "library_panel_button"):
            self.library_panel_button.configure(state="normal")
        if hasattr(self, "embedded_python_cmd_button"):
            python_path = self._embedded_python_path(instance)
            self.embedded_python_cmd_button.configure(state="normal" if python_path.exists() else "disabled")

    def _instance_backup_summary(self, instance: ComfyInstance) -> dict[str, object]:
        if not self.backup_infos:
            self.backup_infos = self._scan_backups()
        source_path = str(self._resolve_comfy_root(Path(instance.path)))
        matches = [
            info for info in self.backup_infos
            if info.get("source_instance") == instance.name or info.get("source_path") == source_path
        ]
        latest = max((float(info.get("created_at", 0) or 0) for info in matches), default=0)
        return {"count": len(matches), "latest": latest}

    def _instance_settings_key(self, instance: ComfyInstance) -> str:
        try:
            return str(Path(instance.path).resolve())
        except OSError:
            return instance.path

    def _get_instance_settings(self, instance: ComfyInstance) -> dict[str, object]:
        instances = self.config.preferences.setdefault("instances", {})
        if not isinstance(instances, dict):
            instances = {}
            self.config.preferences["instances"] = instances
        key = self._instance_settings_key(instance)
        settings = instances.setdefault(key, {})
        if not isinstance(settings, dict):
            settings = {}
            instances[key] = settings
        return settings

    def _set_instance_setting(self, instance: ComfyInstance, key: str, value: object) -> None:
        settings = self._get_instance_settings(instance)
        settings[key] = value
        self.config.save()

    def _move_instance_settings(self, old_key: str, instance: ComfyInstance) -> None:
        instances = self.config.preferences.setdefault("instances", {})
        if not isinstance(instances, dict):
            return
        new_key = self._instance_settings_key(instance)
        if old_key in instances and new_key != old_key:
            instances[new_key] = instances.pop(old_key)

    def _is_instance_frozen(self, instance: ComfyInstance) -> bool:
        return FREEZE_SUFFIX in instance.name or FREEZE_SUFFIX in Path(instance.path).name

    def _comfyui_manager_path(self, instance: ComfyInstance) -> Path:
        comfy_root = self._resolve_comfy_root(Path(instance.path))
        return comfy_root / "custom_nodes" / "comfyui-manager"

    def _embedded_python_path(self, instance: ComfyInstance) -> Path:
        return Path(instance.path) / "python_embeded" / "python.exe"

    def _is_triton_installed(self, instance: ComfyInstance) -> bool:
        site_packages = Path(instance.path) / "python_embeded" / "Lib" / "site-packages"
        if not site_packages.exists():
            return False
        markers = [
            site_packages / "triton",
            *site_packages.glob("triton*.dist-info"),
            *site_packages.glob("triton_windows*.dist-info"),
        ]
        return any(path.exists() for path in markers)

    def _is_ultralytics_installed(self, instance: ComfyInstance) -> bool:
        site_packages = Path(instance.path) / "python_embeded" / "Lib" / "site-packages"
        if not site_packages.exists():
            return False
        markers = [
            site_packages / "ultralytics",
            *site_packages.glob("ultralytics*.dist-info"),
        ]
        return any(path.exists() for path in markers)

    def _is_sage_attention_installed(self, instance: ComfyInstance) -> bool:
        site_packages = Path(instance.path) / "python_embeded" / "Lib" / "site-packages"
        if not site_packages.exists():
            return False
        markers = [
            site_packages / "sageattention",
            *site_packages.glob("sageattention*.dist-info"),
        ]
        return any(path.exists() for path in markers)

    def _is_flash_attention_installed(self, instance: ComfyInstance) -> bool:
        site_packages = Path(instance.path) / "python_embeded" / "Lib" / "site-packages"
        if not site_packages.exists():
            return False
        markers = [
            site_packages / "flash_attn",
            *site_packages.glob("flash_attn*.dist-info"),
            *site_packages.glob("flash_attn*.egg-info"),
        ]
        return any(path.exists() for path in markers)

    @staticmethod
    def _preferred_bat(saved_value: str, values: list[str]) -> str:
        if saved_value in values:
            return saved_value
        return values[0] if values else ""

    @staticmethod
    def _list_bat_files(folder: Path) -> list[str]:
        if not folder.exists() or not folder.is_dir():
            return []
        return sorted(item.name for item in folder.glob("*.bat") if item.is_file())

    def _list_instance_root_bats(self, instance: ComfyInstance) -> list[str]:
        return self._list_bat_files(Path(instance.path))

    def _list_instance_update_bats(self, instance: ComfyInstance) -> list[str]:
        return self._list_bat_files(Path(instance.path) / "update")

    def _choose_start_bat(self) -> None:
        if self.selected_instance is None:
            return
        values = self._list_instance_root_bats(self.selected_instance)
        self._open_simple_dropdown(self.start_bat_entry, values, self._set_start_bat)

    def _choose_update_bat(self) -> None:
        if self.selected_instance is None:
            return
        values = self._list_instance_update_bats(self.selected_instance)
        self._open_simple_dropdown(self.update_bat_entry, values, self._set_update_bat)

    def _set_start_bat(self, value: str) -> None:
        if self.selected_instance is None:
            return
        self.selected_start_bat = value
        self._set_entry_display(self.start_bat_entry, value)
        self._set_instance_setting(self.selected_instance, "start_bat", value)

    def _set_update_bat(self, value: str) -> None:
        if self.selected_instance is None:
            return
        self.selected_update_bat = value
        self._set_entry_display(self.update_bat_entry, value)
        self._set_instance_setting(self.selected_instance, "update_bat", value)

    def _set_start_mode(self, value: str) -> None:
        if value == "Browser":
            value = "Normal"
        if value not in {"Normal", "Dedicated"}:
            value = "Normal"
        self.start_mode_var.set(value)
        self._refresh_start_mode_controls()
        if self.selected_instance is not None:
            self._set_instance_setting(self.selected_instance, "start_mode", value)

    def _start_selected_instance(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        bat_name = self.selected_start_bat
        bat_path = Path(self.selected_instance.path) / bat_name
        if not bat_name or not bat_path.exists():
            self._show_alert("Missing Launcher", "Choose an existing .bat file from the instance root.", "warning")
            return
        dedicated_mode = self.start_mode_var.get() == "Dedicated"
        if dedicated_mode:
            url = self._dedicated_url_for_instance(self.selected_instance)
            if self._is_local_url_available(url):
                self._set_instance_setting(self.selected_instance, "dedicated_url", url)
                self._open_dedicated_instance_window(self.selected_instance, already_running=True)
                return
            if self._is_local_port_listening(url):
                self._terminate_local_port_owner(url)
                self._wait_for_local_port_to_close(url, timeout=8)
            try:
                launch_bat = self._prepare_dedicated_launch_bat(self.selected_instance, bat_path)
            except Exception as exc:
                self._show_alert("Dedicated Launch Failed", f"Could not prepare the dedicated launcher: {exc}", "error")
                return
            try:
                instance_process = self._run_batch_file(launch_bat, Path(self.selected_instance.path), allow_app_temp=True)
            except Exception as exc:
                self._show_alert("Dedicated Launch Failed", f"Could not start the instance: {exc}", "error")
                return
            self.dedicated_window_active = True
            storage_path = self._dedicated_storage_path(self.selected_instance)
            self._set_instance_setting(self.selected_instance, "dedicated_url", url)
            self._set_instance_setting(self.selected_instance, "dedicated_storage_path", str(storage_path))
            self._set_instance_setting(self.selected_instance, "start_mode", "Dedicated")
            threading.Thread(
                target=self._wait_then_open_dedicated_browser,
                args=(self.selected_instance.name, url, storage_path, instance_process),
                daemon=True,
            ).start()
            return
        launch_bat = bat_path
        allow_app_temp = False
        try:
            self._run_batch_file(launch_bat, Path(self.selected_instance.path), allow_app_temp=allow_app_temp)
        except Exception as exc:
            self._show_alert("Start Failed", f"Could not start the instance: {exc}", "error")
            return

    def _update_selected_instance(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        if self._is_instance_frozen(self.selected_instance):
            self._show_alert("Frozen Instance", "Frozen instances cannot be updated.", "info")
            return
        bat_name = self.selected_update_bat
        update_folder = Path(self.selected_instance.path) / "update"
        bat_path = update_folder / bat_name
        if not bat_name or not bat_path.exists():
            self._show_alert("Missing Updater", "Choose an existing .bat file from the instance update folder.", "warning")
            return
        try:
            process = self._run_batch_file(bat_path, update_folder)
        except Exception as exc:
            self._show_alert("Update Failed", f"Could not start the updater: {exc}", "error")
            return
        instance = self.selected_instance
        before_version = self._detect_comfy_version(instance) or self._extract_version_from_name(instance.name)
        threading.Thread(
            target=self._wait_for_update_completion,
            args=(process, instance, before_version),
            daemon=True,
        ).start()

    def _run_batch_file(self, bat_path: Path, cwd: Path, allow_app_temp: bool = False) -> subprocess.Popen:
        if allow_app_temp:
            self._assert_inside_directory(bat_path, LOCAL_TEMP_DIR)
        else:
            self._assert_inside_work_folder(bat_path)
        self._assert_inside_work_folder(cwd)
        if os.name == "nt":
            launcher = str(bat_path) if allow_app_temp else bat_path.name
            command = ["cmd.exe", "/c", launcher]
        else:
            command = [str(bat_path)]
        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        return subprocess.Popen(command, cwd=str(cwd), creationflags=flags, env=self._subprocess_env_with_local_git())

    def _prepare_dedicated_launch_bat(self, instance: ComfyInstance, source_bat: Path) -> Path:
        self._assert_inside_work_folder(source_bat)
        LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        text = self._read_batch_text(source_bat)
        patched = self._patch_batch_disable_auto_launch(text)
        safe_instance = self._safe_folder_name(instance.name) or "instance"
        safe_bat = self._safe_folder_name(source_bat.stem) or "launcher"
        dedicated_bat = LOCAL_TEMP_DIR / f"{safe_instance}_{safe_bat}_dedicated.bat"
        dedicated_bat.write_text(patched, encoding="utf-8")
        return dedicated_bat

    @staticmethod
    def _read_batch_text(path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "mbcs"):
            try:
                return path.read_text(encoding=encoding)
            except (OSError, UnicodeError, LookupError):
                continue
        return path.read_text(errors="ignore")

    @staticmethod
    def _patch_batch_disable_auto_launch(text: str) -> str:
        lines = []
        patched_launch_line = False
        for line in text.splitlines():
            cleaned = re.sub(r"\s+--auto-launch\b", "", line)
            lower = cleaned.lower()
            is_comfy_launch = "main.py" in lower and ("python" in lower or "python.exe" in lower)
            if is_comfy_launch and "--disable-auto-launch" not in lower:
                cleaned = f"{cleaned} --disable-auto-launch"
                patched_launch_line = True
            elif is_comfy_launch:
                patched_launch_line = True
            lines.append(cleaned)
        if not patched_launch_line:
            lines.append("rem Dedicated mode: original launcher did not expose a main.py launch line.")
            lines.append("rem If a browser still opens, add --disable-auto-launch to the selected launcher manually.")
        return "\n".join(lines).rstrip() + "\n"

    def _open_dedicated_instance_window(self, instance: ComfyInstance, already_running: bool = False) -> None:
        if self.dedicated_window_active:
            self._show_alert(
                "Dedicated Instance Already Running",
                "Close the current dedicated instance window before starting another one.",
                "warning",
            )
            return
        if not self._dedicated_browser_available():
            self._show_alert(
                "Dedicated Mode Unavailable",
                "Dedicated mode requires browser\\DS-ComfyUI-Browser.exe in the application folder.",
                "error",
            )
            return
        url = self._dedicated_url_for_instance(instance)
        self._set_instance_setting(instance, "dedicated_url", url)
        storage_path = self._dedicated_storage_path(instance)
        self._set_instance_setting(instance, "dedicated_storage_path", str(storage_path))
        self._set_instance_setting(instance, "start_mode", "Dedicated")
        self.dedicated_window_active = True
        self._run_dedicated_browser_window(instance.name, url, storage_path, None)

    def _wait_then_open_dedicated_browser(
        self,
        title: str,
        url: str,
        storage_path: Path,
        instance_process: subprocess.Popen | None = None,
    ) -> None:
        if not self._wait_for_local_url(url, timeout=90):
            if instance_process is not None:
                self._terminate_process_tree(instance_process)
            self.after(0, lambda: self._dedicated_window_failed("The ComfyUI local address did not respond in time."))
            return
        self.after(0, lambda: self._run_dedicated_browser_window(title, url, storage_path, instance_process))

    def _run_dedicated_browser_window(
        self,
        title: str,
        url: str,
        storage_path: Path,
        instance_process: subprocess.Popen | None,
    ) -> None:
        try:
            process = self._launch_webview2_dedicated_browser(title, url, storage_path)
        except Exception as exc:
            self.dedicated_window_active = False
            self._restore_main_window_after_dedicated()
            self.after(0, lambda message=str(exc): self._show_alert("Dedicated Mode Failed", f"Could not open the dedicated window: {message}", "error"))
            return
        self._hide_main_window_for_dedicated()
        threading.Thread(target=self._wait_for_dedicated_process, args=(process, instance_process, url), daemon=True).start()

    def _launch_webview2_dedicated_browser(self, title: str, url: str, storage_path: Path) -> subprocess.Popen:
        storage_path.mkdir(parents=True, exist_ok=True)
        browser_exe = self._dedicated_browser_exe()
        if not browser_exe.exists():
            raise RuntimeError(f"Dedicated browser helper not found: {browser_exe}")
        command = [
            str(browser_exe),
            "--url",
            url,
            "--title",
            title,
            "--user-data-folder",
            str(storage_path),
            "--config-path",
            str(self.config.config_path or ""),
            "--instance-key",
            str(Path(self.selected_instance.path).resolve()) if self.selected_instance is not None else "",
            "--theme",
            "dark" if self._system_uses_dark_titlebar() else "light",
        ]
        return subprocess.Popen(
            command,
            cwd=str(APP_ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def _wait_for_dedicated_process(
        self,
        process: subprocess.Popen,
        instance_process: subprocess.Popen | None = None,
        url: str | None = None,
    ) -> None:
        process.wait()
        if instance_process is not None:
            self._terminate_process_tree(instance_process)
        if url:
            self._terminate_local_port_owner(url)
            self._wait_for_local_port_to_close(url, timeout=8)
        self.dedicated_window_active = False
        self.after(0, self._restore_main_window_after_dedicated)

    def _terminate_process_tree(self, process: subprocess.Popen) -> None:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=False,
                )
            else:
                process.terminate()
        except Exception:
            pass

    def _terminate_local_port_owner(self, url: str) -> None:
        if os.name != "nt":
            return
        port = self._port_from_url(url)
        if port is None:
            return
        for pid in self._pids_listening_on_port(port):
            if pid == os.getpid():
                continue
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=False,
                )
            except Exception:
                pass

    def _is_local_port_listening(self, url: str) -> bool:
        port = self._port_from_url(url)
        return bool(port and self._pids_listening_on_port(port))

    def _wait_for_local_port_to_close(self, url: str, timeout: int = 8) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._is_local_port_listening(url):
                return
            time.sleep(0.25)

    @staticmethod
    def _port_from_url(url: str) -> int | None:
        try:
            parsed = urllib.parse.urlparse(url)
            return parsed.port
        except ValueError:
            return None

    @staticmethod
    def _pids_listening_on_port(port: int) -> list[int]:
        if os.name != "nt":
            return []
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
        except Exception:
            return []
        pids: set[int] = set()
        port_token = f":{port}"
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() not in {"TCP", "UDP"}:
                continue
            local_address = parts[1]
            state = parts[3].upper() if parts[0].upper() == "TCP" and len(parts) >= 5 else ""
            pid_text = parts[-1]
            if not local_address.endswith(port_token):
                continue
            if parts[0].upper() == "TCP" and state != "LISTENING":
                continue
            try:
                pids.add(int(pid_text))
            except ValueError:
                continue
        return sorted(pids)

    def _hide_main_window_for_dedicated(self) -> None:
        try:
            self.withdraw()
        except Exception:
            pass

    def _restore_main_window_after_dedicated(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self._apply_app_titlebar_theme()
        except Exception:
            pass

    def _start_titlebar_theme_keeper(self) -> None:
        if os.name != "nt":
            return

        def worker() -> None:
            while self.dedicated_window_active:
                self._apply_titlebar_theme_to_process_windows()
                time.sleep(0.5)
            self._apply_titlebar_theme_to_process_windows()

        threading.Thread(target=worker, daemon=True).start()

    def _dedicated_storage_path(self, instance: ComfyInstance) -> Path:
        cache_root = self._ensure_browser_cache_folder()
        if cache_root is None:
            cache_root = APP_ROOT / BROWSER_CACHE_FOLDER_NAME
        profile_name = self._safe_folder_name(instance.name) or "instance"
        settings = self._get_instance_settings(instance)
        existing = str(settings.get("dedicated_storage_path", "")).strip()
        if existing:
            existing_path = Path(existing)
            try:
                existing_path.resolve().relative_to(cache_root.resolve())
                existing_path.mkdir(parents=True, exist_ok=True)
                return existing_path
            except (OSError, ValueError):
                pass
        path = cache_root / profile_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _dedicated_window_failed(self, message: str) -> None:
        self.dedicated_window_active = False
        self._show_alert("Dedicated Mode Failed", message, "error")

    @staticmethod
    def _dedicated_window_background() -> str:
        try:
            import darkdetect
            is_dark = bool(darkdetect.isDark())
        except Exception:
            mode = ctk.get_appearance_mode().lower()
            is_dark = mode == "dark"
        return "#1f1f1f" if is_dark else "#f3f4f6"

    def _dedicated_url_for_instance(self, instance: ComfyInstance) -> str:
        settings = self._get_instance_settings(instance)
        saved_url = str(settings.get("dedicated_url", "")).strip()
        if saved_url:
            return saved_url
        bat_path = Path(instance.path) / self.selected_start_bat
        port = "8188"
        host = "127.0.0.1"
        try:
            text = bat_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        port_match = re.search(r"--port\s+(\d+)", text)
        if port_match:
            port = port_match.group(1)
        listen_match = re.search(r"--listen(?:\s+([^\s]+))?", text)
        if listen_match and listen_match.group(1):
            candidate = listen_match.group(1).strip()
            if candidate not in {"0.0.0.0", "::"}:
                host = candidate
        return f"http://{host}:{port}"

    @staticmethod
    def _wait_for_local_url(url: str, timeout: int = 90) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if App._is_local_url_available(url, timeout=2):
                return True
            else:
                time.sleep(1)
        return False

    @staticmethod
    def _is_local_url_available(url: str, timeout: int = 2) -> bool:
        for endpoint in ("/system_stats", "/queue"):
            try:
                api_url = urllib.parse.urljoin(url.rstrip("/") + "/", endpoint.lstrip("/"))
                with urllib.request.urlopen(api_url, timeout=timeout) as response:
                    payload = response.read(1024 * 256)
                data = json.loads(payload.decode("utf-8", errors="ignore") or "{}")
                if isinstance(data, dict):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _dedicated_browser_available() -> bool:
        return App._dedicated_browser_exe().exists()

    @staticmethod
    def _dedicated_browser_exe() -> Path:
        return APP_ROOT / "browser" / "DS-ComfyUI-Browser.exe"

    def _wait_for_update_completion(self, process: subprocess.Popen, instance: ComfyInstance, before_version: str) -> None:
        process.wait()
        after_version = self._detect_comfy_version(instance) or self._extract_version_from_name(instance.name)
        if after_version and before_version and after_version != before_version:
            self.after(0, lambda: self._mark_instance_updated(instance, after_version))
        else:
            self.after(0, lambda: self._refresh_after_update(instance))

    def _refresh_after_update(self, instance: ComfyInstance) -> None:
        if self.selected_instance is instance:
            self._select_instance(instance)
        self._refresh_instances()

    def _mark_instance_updated(self, instance: ComfyInstance, version: str) -> None:
        try:
            root = Path(instance.path)
            if not root.exists():
                return
            old_key = self._instance_settings_key(instance)
            new_folder_name = self._updated_instance_name(root.name, version)
            new_root = root.with_name(new_folder_name)
            if new_root != root:
                self._assert_inside_work_folder(new_root)
                if new_root.exists():
                    raise RuntimeError(f"Target folder already exists: {new_root}")
                root.rename(new_root)
                instance.path = str(new_root)
            instance.name = self._updated_instance_name(instance.name, version)
            self._move_instance_settings(old_key, instance)
            self.config.save()
        except Exception as exc:
            self._show_alert("Update Rename Failed", f"The update finished, but the instance could not be renamed: {exc}", "warning")
            return
        self._refresh_instances()
        self._select_instance(instance)

    def _updated_instance_name(self, name: str, version: str) -> str:
        version_slug = self._version_slug(version)
        base = re.sub(rf"-?{UPDATED_SUFFIX}$", "", name)
        updated = re.sub(r"(?i)(ComfyUI-)\d+(?:-\d+)+", rf"\g<1>{version_slug}", base, count=1)
        if updated == base and version_slug not in updated:
            updated = f"{updated}-{version_slug}"
        return f"{updated}-{UPDATED_SUFFIX}"

    def _frozen_instance_name(self, name: str) -> str:
        base = re.sub(rf"-?{UPDATED_SUFFIX}$", "", name)
        base = re.sub(rf"-?{FREEZE_SUFFIX}$", "", base)
        return f"{base}-{FREEZE_SUFFIX}"

    def _detect_comfy_version(self, instance: ComfyInstance) -> str:
        comfy_root = self._resolve_comfy_root(Path(instance.path))
        if not (comfy_root / ".git").exists():
            return ""
        git_executable = self._git_executable()
        if git_executable is None:
            return ""
        try:
            result = subprocess.run(
                [str(git_executable), "-C", str(comfy_root), "describe", "--tags", "--abbrev=0"],
                capture_output=True,
                text=True,
                timeout=8,
                env=self._subprocess_env_with_local_git(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _git_executable(self) -> Path | None:
        local_git = self._local_git_executable()
        if local_git is not None:
            return local_git
        system_git = shutil.which("git")
        return Path(system_git) if system_git else None

    def _local_git_executable(self) -> Path | None:
        candidates = [
            LOCAL_GIT_ROOT / "cmd" / "git.exe",
            LOCAL_GIT_ROOT / "bin" / "git.exe",
            LOCAL_GIT_ROOT / "mingw64" / "bin" / "git.exe",
        ]
        for candidate in candidates:
            if self._is_git_executable(candidate):
                return candidate
        if LOCAL_GIT_ROOT.exists():
            for candidate in LOCAL_GIT_ROOT.rglob("git.exe"):
                if self._is_git_executable(candidate):
                    return candidate
        return None

    def _ensure_local_git(self, progress_callback=None) -> Path:
        local_git = self._local_git_executable()
        if local_git is not None:
            return local_git
        if progress_callback:
            progress_callback(0.22, "Preparing local Git...")
        download_url, asset_name = self._latest_portable_git_asset()
        LOCAL_TOOL_DOWNLOADS.mkdir(parents=True, exist_ok=True)
        archive = LOCAL_TOOL_DOWNLOADS / asset_name
        if progress_callback:
            progress_callback(0.28, "Downloading portable Git...")
        self._download_tool(download_url, archive, 0.28, 0.58, progress_callback, "Downloading portable Git")
        if progress_callback:
            progress_callback(0.6, "Extracting portable Git...")
        temp_extract = LOCAL_TOOL_DOWNLOADS / "git_extract"
        self._safe_remove_tree(temp_extract)
        temp_extract.mkdir(parents=True, exist_ok=True)
        seven_zip = self._prepare_local_7zr()
        if not seven_zip.exists():
            raise RuntimeError("Portable 7-Zip extractor is missing. Rebuild the EXE so assets\\7zr.exe is included.")
        self._run_7zr(seven_zip, ["x", str(archive), f"-o{temp_extract}", "-y"], "Portable Git extraction failed", 0.6, 0.82, progress_callback)
        self._safe_remove_tree(LOCAL_GIT_ROOT)
        LOCAL_GIT_ROOT.parent.mkdir(parents=True, exist_ok=True)
        extracted_git = self._find_extracted_git_root(temp_extract)
        if extracted_git is None:
            raise RuntimeError("Portable Git extraction completed, but git.exe was not found.")
        shutil.move(str(extracted_git), str(LOCAL_GIT_ROOT))
        self._safe_remove_tree(temp_extract)
        try:
            archive.unlink()
        except OSError:
            pass
        local_git = self._local_git_executable()
        if local_git is None:
            raise RuntimeError("Local Git setup failed: git.exe was not found after extraction.")
        if progress_callback:
            progress_callback(0.84, "Local Git ready.")
        return local_git

    def _latest_portable_git_asset(self) -> tuple[str, str]:
        request = urllib.request.Request(PORTABLE_GIT_RELEASE_API, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        for asset in payload.get("assets", []):
            name = str(asset.get("name", ""))
            lowered = name.lower()
            if lowered.startswith("portablegit") and "64-bit" in lowered and lowered.endswith(".7z.exe"):
                url = str(asset.get("browser_download_url", ""))
                if url:
                    return url, name
        raise RuntimeError("Could not find a 64-bit PortableGit asset in the latest Git for Windows release.")

    def _download_tool(self, url: str, destination: Path, start: float, end: float, progress_callback=None, label: str = "Downloading tool") -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise RuntimeError(f"{label} failed with HTTP status {status}.")
            total_size = int(response.headers.get("Content-Length") or 0)
            last_emit = 0.0
            downloaded = 0
            with destination.open("wb") as file:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if not progress_callback or now - last_emit < 0.4:
                        continue
                    last_emit = now
                    if total_size:
                        ratio = min(downloaded / total_size, 1.0)
                        progress_callback(start + ((end - start) * ratio), f"{label} ({int(ratio * 100)}%)")
                    else:
                        progress_callback(start, f"{label} ({downloaded / (1024 * 1024):.1f} MB)")
        if total_size and downloaded != total_size:
            raise RuntimeError(f"{label} incomplete: received {downloaded} of {total_size} bytes.")

    @staticmethod
    def _find_extracted_git_root(folder: Path) -> Path | None:
        if App._is_git_executable(folder / "cmd" / "git.exe"):
            return folder
        for candidate in folder.rglob("git.exe"):
            if App._is_git_executable(candidate):
                parent_name = candidate.parent.name.lower()
                if parent_name == "cmd":
                    return candidate.parent.parent
                if parent_name == "bin" and candidate.parent.parent.name.lower() == "mingw64":
                    return candidate.parent.parent.parent
                if parent_name == "bin":
                    return candidate.parent.parent
                return candidate.parent
        return None

    @staticmethod
    def _is_git_executable(path: Path) -> bool:
        try:
            if not path.exists() or path.stat().st_size < 1024:
                return False
            with path.open("rb") as file:
                return file.read(2) == b"MZ"
        except OSError:
            return False

    def _subprocess_env_with_local_git(self) -> dict[str, str]:
        env = os.environ.copy()
        local_git = self._local_git_executable()
        if local_git is None:
            return env
        git_paths = [
            local_git.parent,
            LOCAL_GIT_ROOT / "cmd",
            LOCAL_GIT_ROOT / "bin",
            LOCAL_GIT_ROOT / "usr" / "bin",
            LOCAL_GIT_ROOT / "mingw64" / "bin",
        ]
        path_prefix = os.pathsep.join(str(path) for path in git_paths if path.exists())
        if path_prefix:
            env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
        return env

    @staticmethod
    def _extract_version_from_name(name: str) -> str:
        match = re.search(r"\d+(?:-\d+)+", name)
        return match.group(0) if match else ""

    def _add_existing(self) -> None:
        folder = filedialog.askdirectory(
            title="Select ComfyUI folder",
            initialdir=str(self.config.work_folder) if self.config.work_folder else None,
        )
        if not folder:
            return
        path = Path(folder)
        if not self._is_inside_work_folder(path):
            self._show_alert("Invalid Folder", "Choose a folder inside the current work folder.", "error")
            return
        name = path.name or "ComfyUI"
        if not self._looks_like_comfy(path):
            proceed = self._ask_confirm("Add Folder", "This folder does not appear to contain ComfyUI. Add it anyway?")
            if not proceed:
                return
        self.config.add(ComfyInstance(name=name, path=str(path), created_at=time.time()))
        self._refresh_instances()

    def _remove_selected(self) -> None:
        if self.selected_instance is None:
            return
        self.config.remove(self.selected_instance.path)
        self.selected_instance = None
        self.detail_title.configure(text="Select an instance")
        self.detail_path.configure(text="Instance removed from the list. Files on disk were not touched.")
        if hasattr(self, "start_bat_entry"):
            self._set_entry_display(self.start_bat_entry, "No root .bat found")
        if hasattr(self, "update_bat_entry"):
            self._set_entry_display(self.update_bat_entry, "No update .bat found")
        self._set_detail_text("No instance selected.")
        self._refresh_instances()

    def _delete_selected_instance(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance before deleting it.", "info")
            return
        instance = self.selected_instance
        instance_path = Path(instance.path)
        if not instance_path.exists():
            if self._ask_confirm("Delete Missing Instance", "The instance folder is already missing. Remove it from the list?"):
                self.config.remove(instance.path)
                self.selected_instance = None
                self.detail_title.configure(text="Select an instance")
                self.detail_path.configure(text="Instance removed from the list.")
                self._set_detail_text("No instance selected.")
                self._refresh_instances()
            return
        message = (
            f"Delete this instance from disk?\n\n"
            f"{instance.name}\n{instance_path}\n\n"
            "This action is irreversible. Existing backups will be kept."
        )
        if not self._ask_confirm("Delete Instance", message):
            return
        self._show_delete_instance_progress(instance)

    def _show_delete_instance_progress(self, instance: ComfyInstance) -> None:
        dialog = self._make_modal("Deleting Instance", 500, 210)
        dialog.protocol("WM_DELETE_WINDOW", lambda: self.bell())
        dialog.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            dialog,
            text="Deleting Instance",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(22, 8))
        status_label = ctk.CTkLabel(
            dialog,
            text="Preparing removal...",
            anchor="w",
            text_color=("gray35", "gray72"),
        )
        status_label.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 16))
        progress = ctk.CTkProgressBar(dialog)
        progress.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 22))
        progress.set(0)

        messages: queue.Queue[tuple[str, object]] = queue.Queue()
        threading.Thread(
            target=self._delete_instance_worker,
            args=(instance, self._dedicated_storage_paths_for_delete(instance), messages),
            daemon=True,
        ).start()
        self._poll_delete_instance_progress(dialog, status_label, progress, instance, messages)

    def _poll_delete_instance_progress(
        self,
        dialog: ctk.CTkToplevel,
        status_label: ctk.CTkLabel,
        progress: ctk.CTkProgressBar,
        instance: ComfyInstance,
        messages: queue.Queue[tuple[str, object]],
    ) -> None:
        done = False
        error = ""
        while True:
            try:
                kind, payload = messages.get_nowait()
            except queue.Empty:
                break
            if kind == "STATUS":
                status_label.configure(text=str(payload))
            elif kind == "PROGRESS":
                progress.set(max(0.0, min(1.0, float(payload))))
            elif kind == "ERROR":
                error = str(payload)
                done = True
            elif kind == "DONE":
                done = True

        if not done:
            dialog.after(100, lambda: self._poll_delete_instance_progress(dialog, status_label, progress, instance, messages))
            return

        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        dialog.destroy()
        if error:
            self._show_alert("Delete Failed", f"Could not delete the instance completely:\n\n{error}", "error")
            return
        self._finalize_deleted_instance(instance)

    def _delete_instance_worker(
        self,
        instance: ComfyInstance,
        cache_paths: list[Path],
        messages: queue.Queue[tuple[str, object]],
    ) -> None:
        try:
            instance_path = Path(instance.path)
            messages.put(("STATUS", "Deleting instance folder..."))
            messages.put(("PROGRESS", 0.1))
            self._assert_inside_work_folder(instance_path)
            self._remove_tree_completely(instance_path)

            if cache_paths:
                step = 0.45 / max(len(cache_paths), 1)
                for index, cache_path in enumerate(cache_paths, start=1):
                    messages.put(("STATUS", f"Deleting dedicated browser cache: {cache_path.name}"))
                    messages.put(("PROGRESS", 0.45 + (step * (index - 1))))
                    self._remove_tree_completely(cache_path)
            messages.put(("STATUS", "Verifying cleanup..."))
            messages.put(("PROGRESS", 0.9))
            leftovers = [instance_path, *cache_paths]
            remaining = [str(path) for path in leftovers if path.exists()]
            if remaining:
                raise RuntimeError("Residual files or folders remain:\n" + "\n".join(remaining))
            messages.put(("PROGRESS", 1.0))
            messages.put(("STATUS", "Instance deleted."))
            messages.put(("DONE", ""))
        except Exception as exc:
            messages.put(("ERROR", str(exc)))

    def _dedicated_storage_paths_for_delete(self, instance: ComfyInstance) -> list[Path]:
        if self.config.work_folder is None:
            return []
        cache_root = self.config.work_folder / BROWSER_CACHE_FOLDER_NAME
        if not cache_root.exists():
            return []
        candidates: list[Path] = []
        settings = self._get_instance_settings(instance)
        saved_path = str(settings.get("dedicated_storage_path", "")).strip()
        if saved_path:
            candidates.append(Path(saved_path))
        candidates.append(cache_root / (self._safe_folder_name(instance.name) or "instance"))

        safe_paths: list[Path] = []
        for path in candidates:
            try:
                resolved = path.resolve()
                resolved.relative_to(cache_root.resolve())
            except (OSError, ValueError):
                continue
            if resolved not in safe_paths:
                safe_paths.append(resolved)
        return safe_paths

    def _finalize_deleted_instance(self, instance: ComfyInstance) -> None:
        settings_key = self._instance_settings_key(instance)
        self.config.remove(instance.path)
        instances = self.config.preferences.get("instances", {})
        if isinstance(instances, dict):
            instances.pop(settings_key, None)
        if self.config.preferences.get("last_selected_instance_path") == instance.path:
            self.config.preferences.pop("last_selected_instance_path", None)
            self.config.preferences.pop("last_selected_instance_name", None)
        self.config.save()
        self.selected_instance = None
        self.detail_title.configure(text="Select an instance")
        self.detail_path.configure(text="Instance deleted from disk. Backups were kept.")
        if hasattr(self, "start_bat_entry"):
            self._set_entry_display(self.start_bat_entry, "No root .bat found")
        if hasattr(self, "update_bat_entry"):
            self._set_entry_display(self.update_bat_entry, "No update .bat found")
        self._set_detail_text("Instance deleted. Dedicated browser cache was removed. Backups were kept for future restores.")
        self._refresh_instances()

    def _open_selected_folder(self) -> None:
        if self.selected_instance is None:
            return
        path = Path(self.selected_instance.path)
        if not path.exists():
            self._show_alert("Missing Folder", "The selected folder does not exist.", "warning")
            return
        os.startfile(path)

    def _freeze_selected_instance(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        instance = self.selected_instance
        root = Path(instance.path)
        if self._is_instance_frozen(instance):
            self._show_alert("Already Frozen", "This instance is already marked as FREEZE-NO-UPDATE.", "info")
            return
        if not root.exists():
            self._show_alert("Missing Folder", "The selected instance folder does not exist.", "warning")
            return
        if not self._ask_confirm(
            "Freeze Instance",
            "This will permanently remove the update folder and .git folder from the selected instance. Continue?",
        ):
            return
        try:
            self._assert_inside_work_folder(root)
            comfy_root = self._resolve_comfy_root(root)
            freeze_targets = [root / "update", root / ".git", comfy_root / ".git"]
            for child in freeze_targets:
                self._assert_inside_work_folder(child)
                self._safe_remove_tree(child)
            old_key = self._instance_settings_key(instance)
            frozen_folder_name = self._frozen_instance_name(root.name)
            if root.name != frozen_folder_name:
                new_root = root.with_name(frozen_folder_name)
                self._assert_inside_work_folder(new_root)
                if new_root.exists():
                    raise RuntimeError(f"Target folder already exists: {new_root}")
                root.rename(new_root)
                instance.path = str(new_root)
                root = new_root
            instance.name = self._frozen_instance_name(instance.name)
            self._move_instance_settings(old_key, instance)
            self.config.save()
        except Exception as exc:
            self._show_alert("Freeze Failed", f"Could not freeze the instance: {exc}", "error")
            return
        self._refresh_instances()
        self._select_instance(instance)
        self._show_alert("Instance Frozen", "The instance has been marked as FREEZE-NO-UPDATE.", "info")

    def _install_comfyui_manager(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        instance = self.selected_instance
        comfy_root = self._resolve_comfy_root(Path(instance.path))
        custom_nodes = comfy_root / "custom_nodes"
        manager_folder = self._comfyui_manager_path(instance)
        if manager_folder.exists():
            if not self._ask_confirm("Reinstall ComfyUI Manager", "ComfyUI Manager is already installed. Delete it and reinstall?"):
                return
        if not self._ask_confirm(
            "Install ComfyUI Manager",
            "This will download ComfyUI Manager from GitHub and install it into the selected instance. Continue?",
        ):
            return

        progress = self._open_manager_progress_dialog("Preparing ComfyUI Manager installation...")
        if hasattr(self, "comfyui_manager_button"):
            self.comfyui_manager_button.configure(state="disabled")

        def worker() -> None:
            try:
                def progress_update(value: float, label: str) -> None:
                    self.after(0, lambda current=value, text=label: self._update_manager_progress(progress, current, text))

                progress_update(0.12, "Preparing local Git...")
                git_executable = self._ensure_local_git(progress_update)
                progress_update(0.2, "Preparing custom_nodes folder...")
                self._assert_inside_work_folder(custom_nodes)
                custom_nodes.mkdir(parents=True, exist_ok=True)
                if manager_folder.exists():
                    progress_update(0.35, "Removing existing ComfyUI Manager...")
                    self._assert_inside_work_folder(manager_folder)
                    self._safe_remove_tree(manager_folder)
                progress_update(0.86, "Downloading and installing from GitHub...")
                command = [str(git_executable), "clone", "https://github.com/ltdrdata/ComfyUI-Manager", "comfyui-manager"]
                result = subprocess.run(
                    command,
                    cwd=str(custom_nodes),
                    capture_output=True,
                    text=True,
                    env=self._subprocess_env_with_local_git(),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "").strip()
                    raise RuntimeError(detail or "git clone failed.")
                progress_update(1.0, "Installation completed.")
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda message=error: self._finish_manager_install(progress, False, message))
                return
            self.after(0, lambda: self._finish_manager_install(progress, True, ""))

        threading.Thread(target=worker, daemon=True).start()

    def _open_manager_progress_dialog(
        self,
        status: str,
        title: str = "ComfyUI Manager",
        heading: str = "Installing ComfyUI Manager",
    ) -> dict[str, object]:
        dialog = self._make_modal(title, 480, 220)
        dialog.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            dialog,
            text=heading,
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(22, 8))
        status_label = ctk.CTkLabel(dialog, text=status, anchor="w", text_color=("gray35", "gray72"))
        status_label.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 16))
        progress_bar = ctk.CTkProgressBar(dialog)
        progress_bar.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 24))
        progress_bar.set(0.05)
        return {"dialog": dialog, "status": status_label, "bar": progress_bar}

    def _update_manager_progress(self, progress: dict[str, object], value: float, status: str) -> None:
        dialog = progress.get("dialog")
        if not isinstance(dialog, ctk.CTkToplevel) or not dialog.winfo_exists():
            return
        status_label = progress.get("status")
        progress_bar = progress.get("bar")
        if isinstance(status_label, ctk.CTkLabel):
            status_label.configure(text=status)
        if isinstance(progress_bar, ctk.CTkProgressBar):
            progress_bar.set(max(0.0, min(1.0, value)))

    def _finish_manager_install(self, progress: dict[str, object], success: bool, error: str) -> None:
        dialog = progress.get("dialog")
        if isinstance(dialog, ctk.CTkToplevel) and dialog.winfo_exists():
            dialog.destroy()
        if self.selected_instance is not None:
            self._refresh_instance_action_fields(self.selected_instance)
            self._select_instance(self.selected_instance)
        if success:
            self._show_alert("ComfyUI Manager Installed", "ComfyUI Manager is now installed in the instance", "info")
        else:
            if hasattr(self, "comfyui_manager_button"):
                self.comfyui_manager_button.configure(state="normal")
            self._show_alert("Install Failed", f"Could not install ComfyUI Manager: {error}", "error")

    def _install_triton(self, instance: ComfyInstance | None = None) -> None:
        target = instance or self.selected_instance
        if target is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        self._install_instance_library(
            instance=target,
            library_name="Triton",
            package_name="triton-windows",
            is_installed=self._is_triton_installed,
            progress_title="Install Triton",
            progress_heading="Installing Triton",
            success_message="Triton is now installed in the instance.",
        )

    def _install_ultralytics(self, instance: ComfyInstance | None = None) -> None:
        target = instance or self.selected_instance
        if target is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        self._install_instance_library(
            instance=target,
            library_name="Ultralytics",
            package_name="ultralytics",
            is_installed=self._is_ultralytics_installed,
            progress_title="Install Ultralytics",
            progress_heading="Installing Ultralytics",
            success_message="Ultralytics is now installed in the instance.",
        )

    def _install_instance_library(
        self,
        instance: ComfyInstance,
        library_name: str,
        package_name: str,
        is_installed,
        progress_title: str,
        progress_heading: str,
        success_message: str,
    ) -> None:
        already_installed = bool(is_installed(instance))
        action = "Re-install" if already_installed else "Install"
        python_path = self._embedded_python_path(instance)
        if not python_path.exists():
            self._show_alert("Embedded Python Missing", "This instance does not contain python_embeded\\python.exe.", "error")
            return
        if not self._ask_confirm(
            f"{action} {library_name}",
            f"This will {action.lower()} {library_name} using the selected instance embedded Python. Continue?",
        ):
            return
        progress = self._open_manager_progress_dialog(
            f"Preparing {library_name} installation...",
            title=progress_title,
            heading=progress_heading,
        )

        def worker() -> None:
            try:
                self._assert_inside_work_folder(python_path)
                self.after(0, lambda: self._update_manager_progress(progress, 0.25, "Running pip inside the instance..."))
                command = [str(python_path), "-m", "pip", "install", package_name]
                if already_installed:
                    command.extend(["--upgrade", "--force-reinstall"])
                result = subprocess.run(
                    command,
                    cwd=str(Path(instance.path)),
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                self.after(0, lambda: self._update_manager_progress(progress, 0.85, "Checking installation..."))
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "").strip()
                    raise RuntimeError(detail or "pip install failed.")
                if not is_installed(instance):
                    raise RuntimeError(f"pip completed, but {library_name} was not found in site-packages.")
                self.after(0, lambda: self._update_manager_progress(progress, 1.0, f"{library_name} installation completed."))
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda message=error: self._finish_instance_library_install(progress, False, message, library_name, success_message))
                return
            self.after(0, lambda: self._finish_instance_library_install(progress, True, "", library_name, success_message))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_instance_library_install(
        self,
        progress: dict[str, object],
        success: bool,
        error: str,
        library_name: str,
        success_message: str,
    ) -> None:
        dialog = progress.get("dialog")
        if isinstance(dialog, ctk.CTkToplevel) and dialog.winfo_exists():
            dialog.destroy()
        if self.selected_instance is not None:
            self._refresh_instance_action_fields(self.selected_instance)
            self._select_instance(self.selected_instance)
            self._refresh_library_panel_buttons()
        if success:
            self._show_alert(f"{library_name} Installed", success_message, "info")
        else:
            subtitle = "No Compatible Version Found" if self._is_no_compatible_wheel_error(error) else ""
            self._show_alert(
                f"{library_name} Install Failed",
                f"Could not install {library_name}: {error}",
                "error",
                subtitle=subtitle,
            )

    @staticmethod
    def _is_no_compatible_wheel_error(error: str) -> bool:
        lowered = error.lower()
        return "no exact compatible wheel found" in lowered or "no compatible wheel found" in lowered

    def _install_sage_attention(self, instance: ComfyInstance | None = None) -> None:
        target = instance or self.selected_instance
        if target is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        self._install_matched_wheel_library(
            instance=target,
            library_name="Sage Attention",
            import_name="sageattention",
            project_names=["sageattention"],
            is_installed=self._is_sage_attention_installed,
        )

    def _install_flash_attention(self, instance: ComfyInstance | None = None) -> None:
        target = instance or self.selected_instance
        if target is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        self._install_matched_wheel_library(
            instance=target,
            library_name="Flash Attention",
            import_name="flash_attn",
            project_names=["flash-attn", "flash_attn"],
            is_installed=self._is_flash_attention_installed,
        )

    def _install_matched_wheel_library(
        self,
        instance: ComfyInstance,
        library_name: str,
        import_name: str,
        project_names: list[str],
        is_installed,
    ) -> None:
        already_installed = bool(is_installed(instance))
        action = "Re-install" if already_installed else "Install"
        python_path = self._embedded_python_path(instance)
        if not python_path.exists():
            self._show_alert("Embedded Python Missing", "This instance does not contain python_embeded\\python.exe.", "error")
            return
        if not self._ask_confirm(
            f"{action} {library_name}",
            (
                f"This will detect the selected instance Python, Torch, CUDA and Windows tags, "
                f"then install {library_name} only if an exact compatible wheel is found. Continue?"
            ),
        ):
            return
        progress = self._open_manager_progress_dialog(
            f"Preparing {library_name} wheel matching...",
            title=f"{action} {library_name}",
            heading=f"{action} {library_name}",
        )

        def progress_update(value: float, label: str) -> None:
            self.after(0, lambda current=value, text=label: self._update_manager_progress(progress, current, text))

        def worker() -> None:
            wheel_path: Path | None = None
            try:
                self._assert_inside_work_folder(python_path)
                progress_update(0.08, "Detecting instance environment...")
                environment = self._detect_instance_wheel_environment(instance)
                progress_update(
                    0.2,
                    (
                        f"Detected {environment['python_tag']} / torch {environment['torch_version']} / "
                        f"{environment['cuda_tag']} / {environment['platform_tag']}"
                    ),
                )
                progress_update(0.28, "Searching for an exact compatible wheel...")
                wheel_url, wheel_name = self._find_exact_attention_wheel(project_names, environment)
                wheel_dir = LOCAL_TEMP_DIR / "library_wheels" / (self._safe_folder_name(instance.name) or "instance")
                wheel_dir.mkdir(parents=True, exist_ok=True)
                wheel_path = wheel_dir / wheel_name
                progress_update(0.42, f"Downloading exact wheel: {wheel_name}")
                self._download_tool(wheel_url, wheel_path, 0.42, 0.72, progress_update, f"Downloading {library_name} wheel")
                progress_update(0.76, "Installing local wheel without dependency changes...")
                result = subprocess.run(
                    [
                        str(python_path),
                        "-m",
                        "pip",
                        "install",
                        "--force-reinstall",
                        "--no-deps",
                        "--no-index",
                        str(wheel_path),
                    ],
                    cwd=str(Path(instance.path)),
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "").strip()
                    raise RuntimeError(detail or "pip wheel install failed.")
                progress_update(0.92, "Checking installation...")
                checked_environment = self._detect_instance_wheel_environment(instance)
                for key in ("torch_version", "cuda_tag", "python_tag", "platform_tag"):
                    if checked_environment.get(key) != environment.get(key):
                        raise RuntimeError(
                            f"The instance environment changed during installation "
                            f"({key}: {environment.get(key)} -> {checked_environment.get(key)})."
                        )
                if not is_installed(instance):
                    raise RuntimeError(f"pip completed, but {library_name} was not found in site-packages.")
                progress_update(1.0, f"{library_name} installation completed.")
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda message=error: self._finish_instance_library_install(
                    progress,
                    False,
                    message,
                    library_name,
                    f"{library_name} is now installed in the instance.",
                ))
                return
            finally:
                if wheel_path is not None:
                    try:
                        wheel_path.unlink()
                    except OSError:
                        pass
            self.after(0, lambda: self._finish_instance_library_install(
                progress,
                True,
                "",
                library_name,
                f"{library_name} is now installed in the instance.",
            ))

        threading.Thread(target=worker, daemon=True).start()

    def _detect_instance_wheel_environment(self, instance: ComfyInstance) -> dict[str, str]:
        python_path = self._embedded_python_path(instance)
        code = (
            "import json, platform, re, sys, sysconfig\n"
            "from importlib import metadata\n"
            "from pathlib import Path\n"
            "\n"
            "def cuda_tag_from_text(value):\n"
            "    match = re.search(r'cu(\\d{3})', str(value or '').lower())\n"
            "    return f'cu{match.group(1)}' if match else ''\n"
            "\n"
            "def cuda_tag_from_compiled_version(value):\n"
            "    try:\n"
            "        number = int(value)\n"
            "    except Exception:\n"
            "        return ''\n"
            "    if number <= 0:\n"
            "        return ''\n"
            "    major = number // 1000\n"
            "    minor = (number % 1000) // 10\n"
            "    return f'cu{major}{minor}' if major and minor >= 0 else ''\n"
            "\n"
            "info = {\n"
            "    'python_tag': f'cp{sys.version_info.major}{sys.version_info.minor}',\n"
            "    'platform_tag': 'win_amd64' if platform.machine().lower() in {'amd64', 'x86_64'} else platform.machine().lower(),\n"
            "}\n"
            "try:\n"
            "    import torch\n"
            "    torch_full_version = str(torch.__version__)\n"
            "    info['torch_version'] = torch_full_version.split('+', 1)[0]\n"
            "    cuda = str(torch.version.cuda or '')\n"
            "    cuda_candidates = []\n"
            "    if cuda:\n"
            "        cuda_candidates.append('cu' + cuda.replace('.', ''))\n"
            "    cuda_candidates.append(cuda_tag_from_text(torch_full_version))\n"
            "    for dist_name in ('torch',):\n"
            "        try:\n"
            "            cuda_candidates.append(cuda_tag_from_text(metadata.version(dist_name)))\n"
            "        except metadata.PackageNotFoundError:\n"
            "            pass\n"
            "    site_paths = [sysconfig.get_paths().get('purelib'), sysconfig.get_paths().get('platlib')]\n"
            "    for site_path in {path for path in site_paths if path}:\n"
            "        root = Path(site_path)\n"
            "        if not root.exists():\n"
            "            continue\n"
            "        for item in root.iterdir():\n"
            "            item_name = item.name.lower()\n"
            "            if not item_name.startswith('torch'):\n"
            "                continue\n"
            "            cuda_candidates.append(cuda_tag_from_text(item.name))\n"
            "            if item.is_dir() and item_name.endswith(('.dist-info', '.egg-info')):\n"
            "                for metadata_name in ('METADATA', 'direct_url.json', 'WHEEL'):\n"
            "                    metadata_path = item / metadata_name\n"
            "                    if metadata_path.exists():\n"
            "                        try:\n"
            "                            cuda_candidates.append(cuda_tag_from_text(metadata_path.read_text(errors='ignore')[:12000]))\n"
            "                        except Exception:\n"
            "                            pass\n"
            "    for method_name in ('_cuda_getCompiledVersion', '_cuda_getRuntimeVersion'):\n"
            "        method = getattr(torch._C, method_name, None)\n"
            "        if callable(method):\n"
            "            try:\n"
            "                cuda_candidates.append(cuda_tag_from_compiled_version(method()))\n"
            "            except Exception:\n"
            "                pass\n"
            "    info['cuda_tag'] = next((tag for tag in cuda_candidates if tag), '')\n"
            "    abi = getattr(torch._C, '_GLIBCXX_USE_CXX11_ABI', None)\n"
            "    info['cxx11abi'] = '' if abi is None else ('TRUE' if bool(abi) else 'FALSE')\n"
            "except Exception as exc:\n"
            "    info['error'] = str(exc)\n"
            "print(json.dumps(info))\n"
        )
        result = subprocess.run(
            [str(python_path), "-c", code],
            cwd=str(Path(instance.path)),
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"Could not detect the instance Python/Torch environment: {detail}")
        try:
            info = json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            raise RuntimeError("Could not parse the instance environment detection output.") from exc
        if info.get("error"):
            raise RuntimeError(f"Could not import torch from the instance embedded Python: {info['error']}")
        required = ("python_tag", "torch_version", "cuda_tag", "platform_tag")
        missing = [key for key in required if not str(info.get(key, "")).strip()]
        if missing:
            detected = (
                f"python={info.get('python_tag', 'unknown')}, "
                f"torch={info.get('torch_version', 'unknown')}, "
                f"cuda={info.get('cuda_tag', 'missing')}, "
                f"platform={info.get('platform_tag', 'unknown')}"
            )
            extra = ""
            if "cuda_tag" in missing:
                extra = (
                    " The selected instance PyTorch installation does not expose a CUDA tag, "
                    "so an exact CUDA wheel cannot be selected safely."
                )
            raise RuntimeError(f"Missing required compatibility tags: {', '.join(missing)}. Detected: {detected}.{extra}")
        return {key: str(value) for key, value in info.items()}

    def _find_exact_attention_wheel(self, project_names: list[str], environment: dict[str, str]) -> tuple[str, str]:
        candidates: list[tuple[str, str]] = []
        errors: list[str] = []
        try:
            candidates.extend(self._wheel_links_from_wildminder_catalog())
        except Exception as exc:
            errors.append(f"{WILDMINDER_WHEELS_JSON_URL}: {exc}")
        for base_url in COMFY_WHEEL_INDEX_BASES:
            for project_name in project_names:
                index_url = urllib.parse.urljoin(base_url, f"{project_name}/")
                try:
                    candidates.extend(self._wheel_links_from_index(index_url))
                except Exception as exc:
                    errors.append(f"{index_url}: {exc}")
        candidates = self._dedupe_wheel_candidates(candidates)
        matches = [
            (url, name)
            for url, name in candidates
            if self._wheel_matches_environment(name, project_names, environment)
        ]
        if not matches:
            detected = (
                f"{environment.get('python_tag')} / torch {environment.get('torch_version')} / "
                f"{environment.get('cuda_tag')} / {environment.get('platform_tag')}"
            )
            details = "\n".join(errors[:4])
            if details:
                details = f"\n\nIndex errors:\n{details}"
            raise RuntimeError(
                f"No exact compatible wheel found for {detected}. "
                f"Searched Wildminder AI-windows-whl and Comfy-Org wheel indexes. Nothing was installed.{details}"
            )
        matches.sort(key=lambda item: item[1].lower(), reverse=True)
        return matches[0]

    def _wheel_links_from_wildminder_catalog(self) -> list[tuple[str, str]]:
        request = urllib.request.Request(WILDMINDER_WHEELS_JSON_URL, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
            catalog = json.loads(response.read().decode("utf-8", errors="ignore"))
        links: list[tuple[str, str]] = []

        def collect(value) -> None:
            if isinstance(value, dict):
                for item in value.values():
                    collect(item)
                return
            if isinstance(value, list):
                for item in value:
                    collect(item)
                return
            if not isinstance(value, str):
                return
            text = value.strip()
            if ".whl" not in text.lower():
                return
            if not re.match(r"^https?://", text, flags=re.IGNORECASE):
                return
            wheel_url = self._normalize_wheel_download_url(text)
            wheel_name = self._wheel_name_from_url(wheel_url)
            if wheel_name.lower().endswith(".whl"):
                links.append((wheel_url, wheel_name))

        collect(catalog)
        return links

    def _wheel_links_from_index(self, index_url: str) -> list[tuple[str, str]]:
        request = urllib.request.Request(index_url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
            html = response.read().decode("utf-8", errors="ignore")
        links: list[tuple[str, str]] = []
        for href in re.findall(r'href=[\"\']([^\"\']+\.whl(?:#[^\"\']*)?)[\"\']', html, flags=re.IGNORECASE):
            clean_href = href.split("#", 1)[0]
            url = self._normalize_wheel_download_url(urllib.parse.urljoin(index_url, clean_href))
            name = self._wheel_name_from_url(url)
            if name.lower().endswith(".whl"):
                links.append((url, name))
        return links

    @staticmethod
    def _dedupe_wheel_candidates(candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        unique: list[tuple[str, str]] = []
        for url, name in candidates:
            key = (url.lower(), name.lower())
            if key in seen:
                continue
            seen.add(key)
            unique.append((url, name))
        return unique

    @staticmethod
    def _normalize_wheel_download_url(url: str) -> str:
        clean_url = urllib.parse.unquote(url.strip()).split("#", 1)[0]
        parsed = urllib.parse.urlparse(clean_url)
        if parsed.netloc.lower() == "huggingface.co" and "/blob/" in parsed.path:
            path = parsed.path.replace("/blob/", "/resolve/", 1)
            return urllib.parse.urlunparse(parsed._replace(path=path))
        if parsed.netloc.lower() == "github.com" and "/blob/" in parsed.path:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 5:
                owner, repo, _, branch = parts[:4]
                file_path = "/".join(parts[4:])
                return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
        return clean_url

    @staticmethod
    def _wheel_name_from_url(url: str) -> str:
        return urllib.parse.unquote(Path(urllib.parse.urlparse(url.split("#", 1)[0]).path).name)

    @staticmethod
    def _wheel_matches_environment(name: str, project_names: list[str], environment: dict[str, str]) -> bool:
        lowered = urllib.parse.unquote(name).lower()
        normalized_name = lowered.replace("-", "_")
        normalized_projects = [project.lower().replace("-", "_") for project in project_names]
        if not any(normalized_name.startswith(project) for project in normalized_projects):
            return False
        if not lowered.endswith(".whl"):
            return False
        for token in ("python_tag", "cuda_tag", "platform_tag"):
            value = str(environment.get(token, "")).lower()
            if value and value not in lowered:
                return False
        torch_version = str(environment.get("torch_version", "")).lower()
        if not torch_version:
            return False
        torch_versions = [torch_version]
        torch_parts = torch_version.split(".")
        if len(torch_parts) >= 2:
            torch_versions.append(".".join(torch_parts[:2]))
        if not any(re.search(rf"torch{re.escape(version)}(?![0-9.])", lowered) for version in torch_versions):
            return False
        cxx11abi = str(environment.get("cxx11abi", "")).lower()
        if "cxx11abi" in lowered and cxx11abi and f"cxx11abi{cxx11abi}" not in lowered:
            return False
        return True

    def _open_library_installation_panel(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        instance = self.selected_instance
        dialog = self._make_modal(f"Library Installation Panel - {instance.name}", 520, 290)
        dialog.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            dialog,
            text="Install or re-install libraries only inside this instance.",
            text_color=("gray35", "gray72"),
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(24, 16))
        self.library_panel_window = dialog
        self.library_panel_instance_path = instance.path
        self.library_triton_button = ctk.CTkButton(
            dialog,
            text="Install Triton",
            command=lambda item=instance: self._install_triton(item),
            height=40,
        )
        self.library_triton_button.grid(row=1, column=0, sticky="ew", padx=24, pady=5)
        self.library_ultralytics_button = ctk.CTkButton(
            dialog,
            text="Install Ultralytics",
            command=lambda item=instance: self._install_ultralytics(item),
            height=40,
        )
        self.library_ultralytics_button.grid(row=2, column=0, sticky="ew", padx=24, pady=5)
        self.library_sage_attention_button = ctk.CTkButton(
            dialog,
            text="Install Sage Attention",
            command=lambda item=instance: self._install_sage_attention(item),
            height=40,
        )
        self.library_sage_attention_button.grid(row=3, column=0, sticky="ew", padx=24, pady=5)
        self.library_flash_attention_button = ctk.CTkButton(
            dialog,
            text="Install Flash Attention",
            command=lambda item=instance: self._install_flash_attention(item),
            height=40,
        )
        self.library_flash_attention_button.grid(row=4, column=0, sticky="ew", padx=24, pady=(5, 24))
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self._refresh_library_panel_buttons()

    def _refresh_library_panel_buttons(self) -> None:
        if self.selected_instance is None:
            return
        if not hasattr(self, "library_panel_window"):
            return
        dialog = self.library_panel_window
        if not isinstance(dialog, ctk.CTkToplevel) or not dialog.winfo_exists():
            return
        instance = next(
            (item for item in self.config.instances if item.path == getattr(self, "library_panel_instance_path", "")),
            self.selected_instance,
        )
        if getattr(self, "library_panel_instance_path", "") != instance.path:
            return
        if hasattr(self, "library_triton_button"):
            self._configure_library_button(self.library_triton_button, "Triton", self._is_triton_installed(instance))
        if hasattr(self, "library_ultralytics_button"):
            self._configure_library_button(self.library_ultralytics_button, "Ultralytics", self._is_ultralytics_installed(instance))
        if hasattr(self, "library_sage_attention_button"):
            self._configure_library_button(self.library_sage_attention_button, "Sage Attention", self._is_sage_attention_installed(instance))
        if hasattr(self, "library_flash_attention_button"):
            self._configure_library_button(self.library_flash_attention_button, "Flash Attention", self._is_flash_attention_installed(instance))

    @staticmethod
    def _configure_library_button(button: ctk.CTkButton, library_name: str, installed: bool) -> None:
        if installed:
            button.configure(
                text=f"Re-install {library_name}",
                state="normal",
                fg_color=("gray62", "gray32"),
                hover_color=("gray55", "gray40"),
            )
        else:
            button.configure(
                text=f"Install {library_name}",
                state="normal",
                fg_color=("#2563eb", "#3b82f6"),
                hover_color=("#1d4ed8", "#2563eb"),
            )

    def _run_embedded_python_cmd(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        instance = self.selected_instance
        python_path = self._embedded_python_path(instance)
        if not python_path.exists():
            self._show_alert("Embedded Python Missing", "This instance does not contain python_embeded\\python.exe.", "error")
            return
        try:
            self._assert_inside_work_folder(python_path)
            python_exe = str(python_path)
            instance_folder = str(Path(instance.path))
            launcher_path = LOCAL_TEMP_DIR / f"embedded_python_cmd_{self._safe_folder_name(instance.name) or 'instance'}.bat"
            launcher_path.write_text(
                "\n".join(
                    [
                        "@echo off",
                        f'title Embedded Python - {instance.name}',
                        f'cd /d "{instance_folder}"',
                        f'doskey pyemb="{python_exe}" $*',
                        f"echo Instance: {instance.name}",
                        f"echo Embedded Python: {python_exe}",
                        "echo.",
                        "echo To use the Instance Embedded Python use the alias 'pyemb' like this: pyemb ^<arguments^>",
                        "echo Example: pyemb -m pip list",
                        "echo.",
                    ]
                ),
                encoding="utf-8",
            )
            subprocess.Popen(
                ["cmd.exe", "/k", str(launcher_path)],
                cwd=str(Path(instance.path)),
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
            )
        except Exception as exc:
            self._show_alert("Embedded Python Cmd Failed", f"Could not open the embedded Python command prompt: {exc}", "error")

    def _connect_yaml_to_common_models(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        try:
            common_folder = self._ensure_common_models_folder()
            if common_folder is None:
                raise RuntimeError("No work folder is active.")
            comfy_root = self._resolve_comfy_root(Path(self.selected_instance.path))
            self._assert_inside_work_folder(comfy_root)
            active_yaml = comfy_root / "extra_model_paths.yaml"
            example_yaml = comfy_root / "extra_model_paths.yaml.example"
            self._assert_inside_work_folder(active_yaml)
            self._assert_inside_work_folder(example_yaml)
            template_text = ""
            if example_yaml.exists():
                template_text = example_yaml.read_text(encoding="utf-8", errors="ignore")
            elif active_yaml.exists():
                template_text = active_yaml.read_text(encoding="utf-8", errors="ignore")
            new_text = self._build_common_models_yaml(common_folder, template_text)
            active_yaml.write_text(new_text, encoding="utf-8")
            if example_yaml.exists():
                try:
                    example_yaml.unlink()
                except OSError:
                    pass
            self._set_instance_setting(self.selected_instance, "common_models_connected", True)
        except Exception as exc:
            self._show_alert("YAML Update Failed", f"Could not update extra_model_paths.yaml: {exc}", "error")
            return
        self._select_instance(self.selected_instance)
        self._show_alert("YAML Updated", "The instance is now connected to the common model folder.", "info")

    def _disconnect_yaml_from_common_models(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance first.", "info")
            return
        try:
            comfy_root = self._resolve_comfy_root(Path(self.selected_instance.path))
            active_yaml = comfy_root / "extra_model_paths.yaml"
            example_yaml = comfy_root / "extra_model_paths.yaml.example"
            self._assert_inside_work_folder(active_yaml)
            self._assert_inside_work_folder(example_yaml)
            if not active_yaml.exists():
                self._show_alert("No Active YAML", "This instance has no active extra_model_paths.yaml file.", "info")
                return
            if example_yaml.exists() and not self._ask_confirm("Replace YAML Example", "An extra_model_paths.yaml.example file already exists. Replace it?"):
                return
            if example_yaml.exists():
                example_yaml.unlink()
            active_yaml.rename(example_yaml)
            self._set_instance_setting(self.selected_instance, "common_models_connected", False)
        except Exception as exc:
            self._show_alert("Disconnect Failed", f"Could not disconnect the YAML file: {exc}", "error")
            return
        self._select_instance(self.selected_instance)
        self._show_alert("YAML Disconnected", "The instance will use its internal model folders again.", "info")

    def _open_create_backup_dialog(self) -> None:
        if self.selected_instance is None:
            self._show_alert("No Instance Selected", "Select an instance before creating a backup.", "info")
            return
        instance_path = Path(self.selected_instance.path)
        comfy_root = self._resolve_comfy_root(instance_path)
        if not comfy_root.exists():
            self._show_alert("Missing Instance", "The selected instance folder does not exist.", "warning")
            return

        available = [
            item_name for item_name, _kind in BACKUP_ITEMS
            if self._backup_item_source(self.selected_instance, item_name) is not None
        ]
        if not available:
            self._show_alert("No Backup Items", "This instance has no supported backup items.", "info")
            return

        dialog = self._make_modal("Create Backup", 420, 430)
        dialog.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            dialog,
            text=f"Backup {self.selected_instance.name}",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 10))

        variables: dict[str, tk.BooleanVar] = {}
        for row, (item_name, _kind) in enumerate(BACKUP_ITEMS, start=1):
            variable = tk.BooleanVar(value=item_name in available)
            variables[item_name] = variable
            checkbox = ctk.CTkCheckBox(dialog, text=item_name, variable=variable)
            checkbox.grid(row=row, column=0, sticky="w", padx=20, pady=6)
            if item_name not in available:
                checkbox.configure(state="disabled")

        progress_label = ctk.CTkLabel(dialog, text="Ready", anchor="w", text_color=("gray35", "gray72"))
        progress_label.grid(row=5, column=0, sticky="ew", padx=20, pady=(12, 4))
        progress_bar = ctk.CTkProgressBar(dialog)
        progress_bar.grid(row=6, column=0, sticky="ew", padx=20, pady=(0, 8))
        progress_bar.set(0)

        create_button = ctk.CTkButton(
            dialog,
            text="Create Backup",
            command=lambda: self._create_backup_from_dialog(dialog, variables, create_button, progress_bar, progress_label),
            fg_color=("#2563eb", "#7c3aed"),
            hover_color=("#1d4ed8", "#6d28d9"),
        )
        create_button.grid(row=7, column=0, sticky="ew", padx=20, pady=(12, 8))

    def _create_backup_from_dialog(
        self,
        dialog: ctk.CTkToplevel,
        variables: dict[str, tk.BooleanVar],
        create_button: ctk.CTkButton,
        progress_bar: ctk.CTkProgressBar,
        progress_label: ctk.CTkLabel,
    ) -> None:
        selected_items = [name for name, variable in variables.items() if variable.get()]
        if not selected_items:
            self._show_alert("No Items Selected", "Select at least one backup item.", "error")
            return
        if self.selected_instance is None:
            return
        instance = self.selected_instance
        create_button.configure(state="disabled", text="Creating backup...")
        self._set_backup_progress(progress_bar, progress_label, 0.02, "Preparing backup...")

        def progress_callback(value: float, label: str) -> None:
            self.after(0, lambda: self._set_backup_progress(progress_bar, progress_label, value, label))

        def worker() -> None:
            try:
                backup_path = self._create_backup(instance, selected_items, progress_callback)
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda message=error: self._finish_backup_dialog(dialog, create_button, progress_bar, progress_label, None, message))
                return
            self.after(0, lambda path=backup_path: self._finish_backup_dialog(dialog, create_button, progress_bar, progress_label, path, ""))

        threading.Thread(target=worker, daemon=True).start()

    def _set_backup_progress(self, progress_bar: ctk.CTkProgressBar, progress_label: ctk.CTkLabel, value: float, label: str) -> None:
        if not progress_bar.winfo_exists() or not progress_label.winfo_exists():
            return
        progress_bar.set(max(0.0, min(1.0, value)))
        progress_label.configure(text=label)

    def _finish_backup_dialog(
        self,
        dialog: ctk.CTkToplevel,
        create_button: ctk.CTkButton,
        progress_bar: ctk.CTkProgressBar,
        progress_label: ctk.CTkLabel,
        backup_path: Path | None,
        error: str,
    ) -> None:
        if error:
            if create_button.winfo_exists():
                create_button.configure(state="normal", text="Create Backup")
            self._set_backup_progress(progress_bar, progress_label, 0, "Backup failed")
            self._show_alert("Backup Failed", f"Backup failed: {error}", "error")
            return
        self._set_backup_progress(progress_bar, progress_label, 1.0, "Backup completed")
        if dialog.winfo_exists():
            dialog.destroy()
        self._refresh_backups()
        self._show_alert("Backup Created", f"Backup created:\n{backup_path}", "info")

    def _create_backup(self, instance: ComfyInstance, selected_items: list[str], progress_callback=None) -> Path:
        if self.config.work_folder is None:
            raise RuntimeError("No work folder is active.")
        instance_root = Path(instance.path)
        instance_path = self._resolve_comfy_root(instance_root)
        self._assert_inside_work_folder(instance_root)
        self._assert_inside_work_folder(instance_path)
        backup_dir = self.config.work_folder / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        safe_instance = self._safe_folder_name(instance.name)
        backup_path = backup_dir / f"{safe_instance}_{timestamp}.zip"

        source_map = {
            item: source for item in selected_items
            if (source := self._backup_item_source(instance, item)) is not None
        }
        included_items = list(source_map.keys())
        if not included_items:
            raise RuntimeError("No selected backup items exist on disk.")
        archive_roots = {
            item: self._backup_archive_name(source_map[item], instance_path, instance_root)
            for item in included_items
        }
        if progress_callback:
            progress_callback(0.08, "Scanning selected backup items...")

        manifest = {
            "app": APP_NAME,
            "source_instance": instance.name,
            "source_path": str(instance_path),
            "created_at": time.time(),
            "items": included_items,
            "item_archive_roots": archive_roots,
            "extra_model_paths": self._read_extra_model_paths(instance_path / "extra_model_paths.yaml"),
            "custom_nodes": self._list_custom_nodes(instance_path / "custom_nodes"),
        }

        archive_entries: list[tuple[Path, str, str]] = []
        for item_name in included_items:
            source = source_map[item_name]
            archive_root = archive_roots[item_name]
            if source.is_dir():
                for file_path in source.rglob("*"):
                    relative_path = Path(archive_root) / file_path.relative_to(source)
                    if item_name == "custom_nodes" and self._is_excluded_custom_node_path(relative_path):
                        continue
                    if file_path.is_file():
                        archive_entries.append((file_path, relative_path.as_posix(), item_name))
            elif source.is_file():
                archive_entries.append((source, archive_root, item_name))
        if progress_callback:
            progress_callback(0.15, f"Writing {len(archive_entries)} backup file(s)...")

        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("_ds_meta/backup_manifest.json", json.dumps(manifest, indent=2))
            total_files = max(len(archive_entries), 1)
            last_emit = 0.0
            for index, (file_path, archive_name, item_name) in enumerate(archive_entries, start=1):
                archive.write(file_path, archive_name)
                now = time.monotonic()
                if progress_callback and (index == total_files or index % 20 == 0 or now - last_emit >= 0.25):
                    progress = 0.15 + (0.78 * (index / total_files))
                    progress_callback(progress, f"Backing up {item_name} ({index}/{total_files})")
                    last_emit = now

        if progress_callback:
            progress_callback(0.96, "Registering backup...")
        self._register_backup(backup_path)
        if progress_callback:
            progress_callback(1.0, "Backup completed")
        return backup_path

    def _register_backup(self, backup_path: Path) -> None:
        info = self._inspect_backup(backup_path)
        stored = [item for item in self.config.backups if item.get("path") != str(backup_path)]
        stored.append({
            "path": str(backup_path),
            "source_instance": info.get("source_instance", ""),
            "created_at": info.get("created_at", 0),
            "items": info.get("items", []),
        })
        self.config.backups = stored
        self.config.save()

    def _backup_item_source(self, instance: ComfyInstance, item_name: str) -> Path | None:
        instance_root = Path(instance.path)
        comfy_root = self._resolve_comfy_root(instance_root)
        candidates: list[Path]
        if item_name in {"workflows", "subgraphs"}:
            candidates = [
                comfy_root / item_name,
                comfy_root / "user" / "default" / item_name,
                instance_root / item_name,
            ]
        elif item_name == "custom_nodes":
            candidates = [comfy_root / item_name, instance_root / item_name]
        else:
            candidates = [comfy_root / item_name, instance_root / item_name]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _backup_archive_name(source: Path, comfy_root: Path, instance_root: Path) -> str:
        for base in (comfy_root, instance_root):
            try:
                return source.relative_to(base).as_posix()
            except ValueError:
                continue
        return source.name

    def _refresh_backups(self) -> None:
        if not hasattr(self, "backup_list"):
            return
        for child in self.backup_list.winfo_children():
            child.destroy()
        self.backup_infos = self._scan_backups()
        if not self.backup_infos:
            ctk.CTkLabel(
                self.backup_list,
                text="No backups found.",
                text_color=("gray35", "gray72"),
            ).grid(row=0, column=0, sticky="ew", padx=10, pady=12)
            self.selected_backup_path = None
            return
        for index, info in enumerate(self.backup_infos):
            label = f"{info.get('source_instance', 'Unknown')}  {self._format_timestamp(info.get('created_at', 0))}"
            ctk.CTkButton(
                self.backup_list,
                text=label,
                anchor="w",
                command=lambda item=info: self._select_backup(item),
                fg_color=("gray87", "gray22"),
                text_color=("gray10", "gray92"),
                hover_color=("gray78", "gray30"),
            ).grid(row=index, column=0, sticky="ew", padx=6, pady=5)
        self.config.backups = [
            {
                "path": str(info["path"]),
                "source_instance": info.get("source_instance", ""),
                "created_at": info.get("created_at", 0),
                "items": info.get("items", []),
            }
            for info in self.backup_infos
        ]
        self.config.save()

    def _scan_backups(self) -> list[dict[str, object]]:
        if self.config.work_folder is None:
            return []
        backup_dir = self.config.work_folder / "backup"
        if not backup_dir.exists():
            return []
        infos = []
        for backup_path in sorted(backup_dir.glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True):
            try:
                infos.append(self._inspect_backup(backup_path))
            except Exception:
                continue
        return infos

    def _select_backup(self, info: dict[str, object]) -> None:
        path = Path(str(info["path"]))
        self.selected_backup_path = path
        self.backup_title.configure(text=path.name)
        self.backup_path_label.configure(text=str(path))
        self._set_backup_detail_text(self._format_backup_info(info))

    def _delete_selected_backup(self) -> None:
        if self.selected_backup_path is None:
            self._show_alert("No Backup Selected", "Select a backup first.", "info")
            return
        if not self._ask_confirm("Delete Backup", "Delete this backup from disk?"):
            return
        try:
            if self.selected_backup_path.exists():
                self.selected_backup_path.unlink()
        except OSError as exc:
            self._show_alert("Delete Failed", f"Could not delete backup: {exc}", "error")
            return
        self.selected_backup_path = None
        self.backup_title.configure(text="Select a backup")
        self.backup_path_label.configure(text="")
        self._set_backup_detail_text("Backup deleted.")
        self._refresh_backups()

    def _open_restore_backup_dialog(self) -> None:
        if self.selected_backup_path is None:
            self._show_alert("No Backup Selected", "Select a backup first.", "info")
            return
        if not self.config.instances:
            self._show_alert("No Instances", "No installed instances are available for restore.", "info")
            return
        info = self._inspect_backup(self.selected_backup_path)
        items = list(info.get("items", []))
        if not items:
            self._show_alert("Invalid Backup", "This backup has no restorable items.", "error")
            return

        dialog = self._make_modal("Restore Backup", 560, 520)
        dialog.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            dialog,
            text="Restore Backup",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 10))

        target_names = [instance.name for instance in self.config.instances if Path(instance.path).exists()]
        if not target_names:
            self._show_alert("No Instances", "No existing instance folders are available for restore.", "info")
            dialog.destroy()
            return
        target_selection = {"value": target_names[0]}
        ctk.CTkLabel(dialog, text="Target instance").grid(row=1, column=0, sticky="w", padx=20, pady=(8, 4))
        target_row = ctk.CTkFrame(dialog, fg_color="transparent")
        target_row.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 12))
        target_row.grid_columnconfigure(0, weight=1)
        target_entry = self._build_dropdown_field(
            target_row,
            target_selection["value"],
            lambda: self._open_simple_dropdown(
                target_entry,
                target_names,
                lambda value: self._set_restore_target(target_entry, target_selection, value),
            ),
        )

        ctk.CTkLabel(dialog, text="Restore items").grid(row=3, column=0, sticky="w", padx=20, pady=(8, 4))
        variables: dict[str, tk.BooleanVar] = {}
        for row, item_name in enumerate(items, start=4):
            variable = tk.BooleanVar(value=True)
            variables[item_name] = variable
            ctk.CTkCheckBox(dialog, text=item_name, variable=variable).grid(
                row=row, column=0, sticky="w", padx=20, pady=5
            )

        ctk.CTkButton(
            dialog,
            text="Restore Backup",
            command=lambda: self._restore_backup_from_dialog(dialog, target_selection["value"], variables),
            fg_color=("#7c3aed", "#a855f7"),
            hover_color=("#6d28d9", "#9333ea"),
        ).grid(row=4 + len(items), column=0, sticky="ew", padx=20, pady=(18, 10))

    def _set_restore_target(self, entry: ctk.CTkEntry, selection: dict[str, str], value: str) -> None:
        selection["value"] = value
        self._set_entry_display(entry, value)

    def _open_simple_dropdown(self, entry: ctk.CTkEntry, values: list[str], callback) -> None:
        self._close_dropdown_popup()
        if not values:
            return
        self._protect_dropdown_opening_click()
        self.dropdown_popup = ctk.CTkToplevel(self)
        self.dropdown_popup.overrideredirect(True)
        self.dropdown_popup.transient(self)
        x = entry.winfo_rootx()
        y = entry.winfo_rooty() + entry.winfo_height() + 4
        width = entry.winfo_width() + 50
        self.dropdown_popup.geometry(f"{width}x220+{x}+{y}")
        self.dropdown_popup.grid_columnconfigure(0, weight=1)
        self.dropdown_popup.grid_rowconfigure(0, weight=1)
        list_frame = ctk.CTkScrollableFrame(self.dropdown_popup, corner_radius=8)
        list_frame.grid(row=0, column=0, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)
        for index, value in enumerate(values):
            ctk.CTkButton(
                list_frame,
                text=value,
                anchor="w",
                fg_color=("gray87", "gray22"),
                text_color=("gray10", "gray92"),
                hover_color=("gray78", "gray30"),
                command=lambda selected=value: self._select_simple_dropdown_value(callback, selected),
            ).grid(row=index, column=0, sticky="ew", padx=6, pady=4)

    def _select_simple_dropdown_value(self, callback, value: str) -> None:
        self._close_dropdown_popup()
        callback(value)

    def _restore_backup_from_dialog(self, dialog: ctk.CTkToplevel, target_name: str, variables: dict[str, tk.BooleanVar]) -> None:
        selected_items = [name for name, variable in variables.items() if variable.get()]
        if not selected_items:
            self._show_alert("No Items Selected", "Select at least one item to restore.", "error")
            return
        target = next((item for item in self.config.instances if item.name == target_name), None)
        if target is None:
            self._show_alert("Invalid Target", "Select a valid target instance.", "error")
            return
        if not self._ask_confirm("Restore Backup", f"Restore selected backup items into {target.name}? Existing files with the same names will be overwritten."):
            return
        try:
            self._restore_backup(self.selected_backup_path, Path(target.path), selected_items)
        except Exception as exc:
            self._show_alert("Restore Failed", f"Restore failed: {exc}", "error")
            return
        dialog.destroy()
        self._show_alert("Backup Restored", "Backup restored.", "info")

    def _restore_backup(self, backup_path: Path | None, target_path: Path, selected_items: list[str]) -> None:
        if backup_path is None:
            raise RuntimeError("No backup selected.")
        self._assert_inside_work_folder(backup_path)
        self._assert_inside_work_folder(target_path)
        if not target_path.exists():
            raise RuntimeError("Target instance folder does not exist.")
        target_path = self._resolve_comfy_root(target_path)
        self._assert_inside_work_folder(target_path)
        selected_roots = set(selected_items)
        with zipfile.ZipFile(backup_path) as archive:
            names = [name.replace("\\", "/") for name in archive.namelist()]
            archive_roots = self._backup_item_archive_roots(archive, names)
            for member in archive.infolist():
                name = member.filename.replace("\\", "/")
                if name.endswith("/") or name.startswith("_ds_meta/"):
                    continue
                logical_item = self._logical_backup_item_for_archive_name(name, archive_roots)
                if logical_item not in selected_roots:
                    continue
                output_path = target_path / name
                self._assert_inside_directory(output_path, target_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, output_path.open("wb") as target:
                    shutil.copyfileobj(source, target)

    def _inspect_backup(self, backup_path: Path) -> dict[str, object]:
        with zipfile.ZipFile(backup_path) as archive:
            names = [name.replace("\\", "/") for name in archive.namelist()]
            manifest = {}
            if "_ds_meta/backup_manifest.json" in names:
                with archive.open("_ds_meta/backup_manifest.json") as manifest_file:
                    manifest = json.loads(manifest_file.read().decode("utf-8"))
            manifest_items = manifest.get("items", [])
            if isinstance(manifest_items, list) and manifest_items:
                items = [item for item in manifest_items if isinstance(item, str)]
            else:
                archive_roots = self._backup_item_archive_roots(archive, names)
                items = []
                for item_name, _kind in BACKUP_ITEMS:
                    roots = [item_name, archive_roots.get(item_name, "")]
                    if any(root and any(name == root or name.startswith(f"{root}/") for name in names) for root in roots):
                        items.append(item_name)
            custom_nodes = manifest.get("custom_nodes") or self._list_custom_nodes_from_archive(names)
            extra_model_paths = manifest.get("extra_model_paths") or self._read_extra_model_paths_from_archive(archive, names)
        return {
            "path": backup_path,
            "source_instance": manifest.get("source_instance", backup_path.stem),
            "source_path": manifest.get("source_path", ""),
            "created_at": manifest.get("created_at", backup_path.stat().st_mtime),
            "items": items,
            "custom_nodes": custom_nodes,
            "extra_model_paths": extra_model_paths,
        }

    @staticmethod
    def _backup_item_archive_roots(archive: zipfile.ZipFile, names: list[str]) -> dict[str, str]:
        if "_ds_meta/backup_manifest.json" not in names:
            return {}
        try:
            with archive.open("_ds_meta/backup_manifest.json") as manifest_file:
                manifest = json.loads(manifest_file.read().decode("utf-8"))
        except (OSError, KeyError, json.JSONDecodeError):
            return {}
        roots = manifest.get("item_archive_roots", {})
        if not isinstance(roots, dict):
            return {}
        return {
            str(item): str(root).replace("\\", "/")
            for item, root in roots.items()
            if isinstance(item, str) and isinstance(root, str)
        }

    @staticmethod
    def _logical_backup_item_for_archive_name(name: str, archive_roots: dict[str, str]) -> str:
        for item_name, _kind in BACKUP_ITEMS:
            archive_root = archive_roots.get(item_name, item_name)
            if name == archive_root or name.startswith(f"{archive_root}/"):
                return item_name
            if name == item_name or name.startswith(f"{item_name}/"):
                return item_name
        return name.split("/", 1)[0]

    def _format_backup_info(self, info: dict[str, object]) -> str:
        lines = [
            f"Backup file: {Path(str(info.get('path', ''))).name}",
            f"Source instance: {info.get('source_instance', 'Unknown')}",
            f"Source path: {info.get('source_path', '') or 'Not recorded'}",
            f"Created at: {self._format_timestamp(info.get('created_at', 0))}",
            "",
            "Included items:",
        ]
        for item in info.get("items", []):
            lines.append(f"- {item}")

        lines.extend(["", "extra_model_paths.yaml external folders:"])
        extra_paths = info.get("extra_model_paths", [])
        if extra_paths:
            for path in extra_paths:
                lines.append(f"- {path}")
        else:
            lines.append("- None found")

        lines.extend(["", "Custom nodes:"])
        custom_nodes = info.get("custom_nodes", [])
        if custom_nodes:
            for node in custom_nodes:
                lines.append(f"- {node}")
        else:
            lines.append("- None found")
        return "\n".join(lines)

    def _set_backup_detail_text(self, text: str) -> None:
        if not hasattr(self, "backup_detail_box"):
            return
        self.backup_detail_box.configure(state="normal")
        self.backup_detail_box.delete("1.0", "end")
        self.backup_detail_box.insert("1.0", text)
        self.backup_detail_box.configure(state="disabled")

    def _make_modal(self, title: str, width: int, height: int) -> ctk.CTkToplevel:
        self._close_dropdown_popup()
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        self._center_window(dialog, width, height)
        dialog.transient(self)
        dialog.grab_set()
        self._style_toplevel(dialog)
        return dialog

    def _style_toplevel(self, window: ctk.CTkToplevel) -> None:
        try:
            window.configure(fg_color=ctk.ThemeManager.theme["CTk"]["fg_color"])
        except tk.TclError:
            pass
        self._apply_toplevel_icon(window)
        if os.name == "nt":
            for delay in (0, 80, 220, 500):
                window.after(delay, lambda target=window: self._apply_toplevel_window_chrome(target))

    def _apply_toplevel_icon(self, window: ctk.CTkToplevel) -> None:
        if not ICON_PATH.exists():
            return
        try:
            window.iconbitmap(default=str(ICON_PATH))
        except Exception:
            try:
                window.iconbitmap(str(ICON_PATH))
            except Exception:
                pass

    def _apply_toplevel_window_chrome(self, window: ctk.CTkToplevel) -> None:
        try:
            if window.winfo_exists():
                self._apply_toplevel_icon(window)
                hwnd = self._native_window_handle(window)
                self._apply_windows_icon_to_hwnd(hwnd)
                self._apply_titlebar_theme_to_hwnd(hwnd)
        except Exception:
            pass

    @staticmethod
    def _apply_windows_icon_to_hwnd(hwnd: int) -> None:
        if os.name != "nt" or not hwnd or not ICON_PATH.exists():
            return
        try:
            icon_path = str(ICON_PATH)
            user32 = ctypes.windll.user32
            load_image = user32.LoadImageW
            load_image.argtypes = [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                ctypes.c_uint,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            load_image.restype = wintypes.HANDLE

            small_icon = load_image(None, icon_path, 1, 16, 16, 0x00000010)
            big_icon = load_image(None, icon_path, 1, 32, 32, 0x00000010)
            if small_icon:
                user32.SendMessageW(wintypes.HWND(hwnd), 0x0080, 0, small_icon)
                App._set_window_class_icon(hwnd, -34, small_icon)
            if big_icon:
                user32.SendMessageW(wintypes.HWND(hwnd), 0x0080, 1, big_icon)
                App._set_window_class_icon(hwnd, -14, big_icon)
        except Exception:
            pass

    @staticmethod
    def _set_window_class_icon(hwnd: int, index: int, icon_handle: int) -> None:
        try:
            user32 = ctypes.windll.user32
            if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_longlong):
                set_class_long = user32.SetClassLongPtrW
                set_class_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                set_class_long.restype = ctypes.c_void_p
                set_class_long(wintypes.HWND(hwnd), index, ctypes.c_void_p(icon_handle))
            else:
                set_class_long = user32.SetClassLongW
                set_class_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
                set_class_long.restype = ctypes.c_long
                set_class_long(wintypes.HWND(hwnd), index, ctypes.c_long(icon_handle))
        except Exception:
            pass

    @staticmethod
    def _native_window_handle(window: tk.Misc) -> int:
        hwnd = int(window.winfo_id())
        if os.name != "nt" or not hwnd:
            return hwnd
        try:
            get_ancestor = ctypes.windll.user32.GetAncestor
            get_ancestor.argtypes = [wintypes.HWND, ctypes.c_uint]
            get_ancestor.restype = wintypes.HWND
            root_hwnd = get_ancestor(wintypes.HWND(hwnd), ctypes.c_uint(2))
            if root_hwnd:
                return int(root_hwnd)
        except Exception:
            pass
        return hwnd

    def _lock_app_for_installation(self) -> None:
        self._append_log("The app is locked until the current instance installation is completed.")
        self._close_dropdown_popup()
        self.install_locked_control_states = {}
        if hasattr(self, "cancel_install_button"):
            self.cancel_install_button.configure(state="normal", text="Cancel installation")
            self.cancel_install_button.grid()
        controls: list[tk.Misc] = [
            getattr(self, "open_work_folder_button", None),
            getattr(self, "create_work_folder_button", None),
            getattr(self, "new_name", None),
            getattr(self, "comfy_version_entry", None),
            getattr(self, "portable_package_entry", None),
            getattr(self, "source_url", None),
            getattr(self, "install_button", None),
        ]
        if hasattr(self, "tabs") and hasattr(self.tabs, "_segmented_button"):
            controls.append(self.tabs._segmented_button)
        for entry_name in ("comfy_version_entry", "portable_package_entry"):
            entry = getattr(self, entry_name, None)
            button = self.dropdown_field_buttons.get(entry)
            if button is not None:
                controls.append(button)
        for control in controls:
            self._set_install_locked_control_state(control, "disabled")

    def _unlock_app_after_installation(self) -> None:
        self._restore_install_locked_controls()
        if hasattr(self, "cancel_install_button"):
            self.cancel_install_button.grid_remove()
        self._append_log("The app is unlocked.")

    def _set_install_locked_control_state(self, widget: tk.Misc | None, state: str) -> None:
        if widget is None:
            return
        try:
            if not widget.winfo_exists():
                return
            current_state = self._widget_state(widget)
            if widget not in self.install_locked_control_states:
                self.install_locked_control_states[widget] = current_state
            widget.configure(state=state)
        except Exception:
            pass

    def _restore_install_locked_controls(self) -> None:
        for widget, state in list(self.install_locked_control_states.items()):
            try:
                if widget.winfo_exists():
                    widget.configure(state=state)
            except Exception:
                pass
        self.install_locked_control_states = {}

    @staticmethod
    def _widget_state(widget: tk.Misc) -> str:
        try:
            return str(widget.cget("state"))
        except Exception:
            return str(getattr(widget, "_state", "normal"))

    def _center_window(self, window: ctk.CTkToplevel, width: int, height: int) -> None:
        self.update_idletasks()
        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_width = max(self.winfo_width(), 1)
        parent_height = max(self.winfo_height(), 1)
        x = parent_x + max((parent_width - width) // 2, 0)
        y = parent_y + max((parent_height - height) // 2, 0)
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _show_alert(self, title: str, message: str, level: str = "info", subtitle: str = "") -> None:
        dialog = self._make_modal(title, 460, 250 if subtitle else 220)
        dialog.grid_columnconfigure(0, weight=1)
        colors = {
            "info": ("#2563eb", "#3b82f6"),
            "warning": ("#ca8a04", "#eab308"),
            "error": ("#dc2626", "#ef4444"),
        }
        accent = colors.get(level, colors["info"])
        ctk.CTkLabel(dialog, text=title, font=ctk.CTkFont(size=20, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(22, 2 if subtitle else 8)
        )
        message_row = 1
        if subtitle:
            ctk.CTkLabel(dialog, text=subtitle, font=ctk.CTkFont(size=20, weight="bold")).grid(
                row=1, column=0, sticky="w", padx=24, pady=(0, 10)
            )
            message_row = 2
        ctk.CTkLabel(dialog, text=message, wraplength=400, justify="left", text_color=("gray35", "gray72")).grid(
            row=message_row, column=0, sticky="ew", padx=24, pady=(0, 20)
        )
        ctk.CTkButton(
            dialog,
            text="OK",
            command=dialog.destroy,
            fg_color=accent,
            hover_color=accent,
        ).grid(row=message_row + 1, column=0, sticky="e", padx=24, pady=(0, 20))
        dialog.wait_window()

    def _ask_confirm(self, title: str, message: str) -> bool:
        result = {"value": False}
        dialog = self._make_modal(title, 500, 240)
        dialog.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(dialog, text=title, font=ctk.CTkFont(size=20, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=24, pady=(22, 8)
        )
        ctk.CTkLabel(dialog, text=message, wraplength=440, justify="left", text_color=("gray35", "gray72")).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=24, pady=(0, 22)
        )

        def choose(value: bool) -> None:
            result["value"] = value
            dialog.destroy()

        ctk.CTkButton(dialog, text="Cancel", command=lambda: choose(False), fg_color=("gray65", "gray28")).grid(
            row=2, column=0, sticky="ew", padx=(24, 8), pady=(0, 22)
        )
        ctk.CTkButton(
            dialog,
            text="Confirm",
            command=lambda: choose(True),
            fg_color=("#7c3aed", "#a855f7"),
            hover_color=("#6d28d9", "#9333ea"),
        ).grid(row=2, column=1, sticky="ew", padx=(8, 24), pady=(0, 22))
        dialog.wait_window()
        return result["value"]

    @staticmethod
    def _format_timestamp(value: object) -> str:
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            timestamp = 0
        if timestamp <= 0:
            return "Unknown"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

    @staticmethod
    def _read_extra_model_paths(path: Path) -> list[str]:
        if not path.exists() or not path.is_file():
            return []
        try:
            return App._extract_yaml_paths(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            return []

    @staticmethod
    def _read_extra_model_paths_from_archive(archive: zipfile.ZipFile, names: list[str]) -> list[str]:
        if "extra_model_paths.yaml" not in names:
            return []
        try:
            with archive.open("extra_model_paths.yaml") as file:
                text = file.read().decode("utf-8", errors="ignore")
        except (OSError, KeyError):
            return []
        return App._extract_yaml_paths(text)

    @staticmethod
    def _extract_yaml_paths(text: str) -> list[str]:
        paths: list[str] = []
        base_path = ""
        for line in text.splitlines():
            stripped = line.strip().strip("'\"")
            if not stripped or stripped.startswith("#"):
                continue
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                stripped = value.strip().strip("'\"")
                if key.strip() == "base_path":
                    base_path = stripped
            if not stripped or stripped == "|":
                continue
            if re.search(r"(^[A-Za-z]:[\\/]|^[\\/]{2})", stripped):
                paths.append(stripped)
            elif "/" in stripped and base_path:
                paths.append(str(Path(base_path) / stripped.replace("/", os.sep)))
            elif "/" in stripped:
                paths.append(stripped)
        return list(dict.fromkeys(paths))

    def _common_model_status(self, instance: ComfyInstance) -> dict[str, object]:
        common_folder = self._ensure_common_models_folder()
        common_token = ""
        if common_folder is not None:
            common_token = str(common_folder.resolve()).replace("\\", "/").lower()
        comfy_root = self._resolve_comfy_root(Path(instance.path))
        paths = self._read_extra_model_paths(comfy_root / "extra_model_paths.yaml")
        common_paths = []
        internal_paths = []
        for path in paths:
            normalized = path.replace("\\", "/").lower()
            if common_token and common_token in normalized:
                common_paths.append(path)
            else:
                internal_paths.append(path)
        connected = bool(common_paths)
        if not connected:
            settings = self._get_instance_settings(instance)
            connected = bool(settings.get("common_models_connected", False)) and (comfy_root / "extra_model_paths.yaml").exists()
        return {
            "connected": connected,
            "common_paths": common_paths,
            "internal_paths": internal_paths,
        }

    def _build_common_models_yaml(self, common_folder: Path, template_text: str) -> str:
        suffix = self._yaml_suffix_after_a1111_marker(template_text)
        base_path = self._yaml_path(common_folder)
        lines = [
            "#Rename this to extra_model_paths.yaml and ComfyUI will load it",
            "",
            "#config for comfyui",
            "#your base path should be either an existing comfy install or a central folder where you store all of your models, loras, etc.",
            "",
            "comfyui:",
            f"    base_path: {base_path}",
            "    checkpoints: models/checkpoints/",
            "    text_encoders: |",
            "        models/text_encoders/",
            "        models/clip/",
            "    clip_vision: models/clip_vision/",
            "    configs: models/configs/",
            "    controlnet: models/controlnet/",
            "    diffusion_models: |",
            "        models/diffusion_models/",
            "        models/unet/",
            "    embeddings: models/embeddings/",
            "    loras: models/loras/",
            "    upscale_models: models/upscale_models/",
            "    vae: models/vae/",
            "    audio_encoders: models/audio_encoders/",
            "    model_patches: models/model_patches/",
            "    ultralytics: models/ultralytics/",
            "    latent_upscale_models: models/latent_upscale_models/",
            "",
        ]
        if suffix:
            lines.append(suffix.lstrip("\n"))
        else:
            lines.append("#config for a1111 ui")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _yaml_suffix_after_a1111_marker(text: str) -> str:
        if not text:
            return ""
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if "#config for a1111 ui" in line.lower():
                return "\n".join(lines[index:])
        return ""

    @staticmethod
    def _yaml_path(path: Path) -> str:
        value = path.resolve().as_posix()
        return value if value.endswith("/") else f"{value}/"

    @staticmethod
    def _list_custom_nodes(path: Path) -> list[str]:
        if not path.exists() or not path.is_dir():
            return []
        return sorted(
            item.name
            for item in path.iterdir()
            if item.is_dir() and item.name not in CUSTOM_NODE_EXCLUDE_NAMES
        )

    @staticmethod
    def _list_custom_nodes_from_archive(names: list[str]) -> list[str]:
        nodes = set()
        for name in names:
            if not name.startswith("custom_nodes/"):
                continue
            parts = name.split("/")
            if len(parts) >= 2 and parts[1] and parts[1] not in CUSTOM_NODE_EXCLUDE_NAMES:
                nodes.add(parts[1])
        return sorted(nodes)

    @staticmethod
    def _is_excluded_custom_node_path(relative_path: Path) -> bool:
        parts = relative_path.parts
        if len(parts) < 2 or parts[0] != "custom_nodes":
            return False
        return any(part in CUSTOM_NODE_EXCLUDE_NAMES for part in parts[1:])

    def _start_install(self) -> None:
        if self.install_in_progress:
            return
        if self.config.work_folder is None:
            self._show_alert("No Work Folder", "Select a work folder before starting the installation.", "error")
            return
        raw_name = self.new_name.get().strip() or self._default_instance_name()
        name = self._safe_folder_name(raw_name)
        if not name:
            self._show_alert("Invalid Instance Name", "Choose a valid instance name.", "error")
            return
        destination = self.config.work_folder / name
        if destination.resolve() == self.config.work_folder.resolve():
            self._show_alert("Invalid Destination", "ComfyUI cannot be installed directly in the work folder.", "error")
            return
        self.source_url.configure(state="normal")
        source_url = self.source_url.get().strip()
        self.source_url.configure(state="disabled")
        if not source_url:
            self._show_alert("Missing Package", "Choose a ComfyUI version and portable package before starting the installation.", "error")
            return
        if destination.exists():
            self._show_alert("Duplicate Instance", "The instance name already matches an existing work folder subfolder.", "error")
            return
        self.install_cancel_requested.clear()
        self.current_install_destination = destination
        self.install_in_progress = True
        self._set_install_progress(0, "Starting installation")
        thread = threading.Thread(
            target=self._install_worker,
            args=(name, destination, source_url, self.selected_comfy_version, self.selected_portable_package),
            daemon=True,
        )
        thread.start()
        try:
            self._lock_app_for_installation()
        except Exception as exc:
            self._append_log(f"Interface lock warning: {exc}")
        self.install_button.configure(state="disabled", text="Installing...")

    def _request_cancel_installation(self) -> None:
        if not self.install_in_progress:
            return
        if not self._ask_confirm(
            "Cancel Installation",
            "Cancel the current installation and remove all partial files?",
        ):
            return
        self.install_cancel_requested.set()
        if hasattr(self, "cancel_install_button"):
            self.cancel_install_button.configure(state="disabled", text="Cancelling...")
        self._set_install_progress(0.0, "Cancelling installation")
        self._append_log("Cancellation requested. Waiting for the current operation to stop.")

    def _raise_if_install_cancelled(self) -> None:
        if self.install_cancel_requested.is_set():
            raise InstallationCancelled()

    def _cleanup_cancelled_installation(self, destination: Path) -> None:
        self._assert_inside_work_folder(destination)
        self._safe_remove_tree(destination)

    def _install_worker(self, name: str, destination: Path, source_url: str, version: str, package_name: str) -> None:
        download_dir = destination / "_download"
        extract_dir = destination / "_extract"
        try:
            self._raise_if_install_cancelled()
            self._assert_inside_work_folder(destination)
            self._assert_inside_directory(download_dir, destination)
            self._assert_inside_directory(extract_dir, destination)
            self.worker_messages.put(("PROGRESS", 0.02, "Preparing folders"))
            self.worker_messages.put(f"Creating folder: {destination}")
            destination.mkdir(parents=True, exist_ok=True)
            download_dir.mkdir(parents=True, exist_ok=True)
            archive = download_dir / self._archive_name_from_url(source_url, package_name)
            self._assert_inside_directory(archive, destination)

            self.worker_messages.put(f"Downloading ComfyUI {version} / {package_name}: {source_url}")
            self._download_file(source_url, archive, 0.05, 0.72)
            self._raise_if_install_cancelled()
            archive_size = archive.stat().st_size
            if archive_size < 1024 * 1024:
                raise RuntimeError(f"Downloaded archive is unexpectedly small ({archive_size} bytes).")
            self.worker_messages.put(f"Downloaded archive size: {archive_size / (1024 * 1024):.1f} MB")

            self.worker_messages.put(("PROGRESS", 0.74, "Preparing extraction"))
            self._safe_remove_tree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)
            self.worker_messages.put("Extracting archive...")
            if archive.suffix.lower() == ".7z":
                self.worker_messages.put("Testing and extracting with local portable 7-Zip.")
            self.worker_messages.put(("PROGRESS", 0.78, "Extracting archive"))
            self._extract_archive(archive, extract_dir, progress_callback=lambda value, label: self.worker_messages.put(("PROGRESS", value, label)))
            self._raise_if_install_cancelled()

            self.worker_messages.put(("PROGRESS", 0.9, "Moving files"))
            roots = [item for item in extract_dir.iterdir() if item.is_dir()]
            source_root = roots[0] if len(roots) == 1 else extract_dir
            for item in source_root.iterdir():
                self._raise_if_install_cancelled()
                shutil.move(str(item), str(destination / item.name))
            self.worker_messages.put(("PROGRESS", 0.96, "Cleaning temporary files"))
            self._safe_remove_tree(extract_dir)
            self._safe_remove_tree(download_dir)

            self.config.add(ComfyInstance(name=name, path=str(destination), created_at=time.time()))
            self.worker_messages.put(("PROGRESS", 1.0, "Installation completed"))
            self.worker_messages.put("Installation completed and instance added to the list.")
            self.worker_messages.put("__REFRESH__")
            self.worker_messages.put("__INSTALL_DONE__")
        except InstallationCancelled:
            try:
                self._cleanup_cancelled_installation(destination)
                self.worker_messages.put("Installation cancelled. Partial files were removed.")
            except Exception as cleanup_exc:
                self.worker_messages.put(f"Installation cancelled, but cleanup failed: {cleanup_exc}")
            self.worker_messages.put(("PROGRESS", 0.0, "Installation cancelled"))
            self.worker_messages.put("__INSTALL_DONE__")
        except Exception as exc:
            self._safe_remove_tree(extract_dir)
            try:
                if destination.exists() and not any(destination.iterdir()):
                    destination.rmdir()
            except OSError:
                pass
            self.worker_messages.put(("PROGRESS", 0.0, "Installation failed"))
            self.worker_messages.put(f"Installation error: {exc}")
            if download_dir.exists():
                self.worker_messages.put(f"Downloaded files kept for inspection: {download_dir}")
            self.worker_messages.put("__INSTALL_DONE__")

    def _download_file(self, url: str, destination: Path, start: float, end: float) -> None:
        if destination.parent:
            destination.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise RuntimeError(f"Download failed with HTTP status {status}.")
            total_size = int(response.headers.get("Content-Length") or 0)
            self.worker_messages.put(f"Download target: {destination}")
            if total_size:
                self.worker_messages.put(f"Expected download size: {total_size / (1024 * 1024):.1f} MB")
            self._stream_response_to_file(response, destination, total_size, start, end)

    def _stream_response_to_file(self, response, destination: Path, total_size: int, start: float, end: float) -> None:
        last_percent = -1
        last_emit = 0.0
        downloaded = 0
        with destination.open("wb") as file:
            while True:
                self._raise_if_install_cancelled()
                chunk = response.read(1024 * 1024)
                self._raise_if_install_cancelled()
                if not chunk:
                    break
                file.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if total_size <= 0:
                    if now - last_emit >= 0.5:
                        self.worker_messages.put(("PROGRESS", start, f"Downloading package ({downloaded / (1024 * 1024):.1f} MB)"))
                        last_emit = now
                    continue
                ratio = min(downloaded / total_size, 1.0)
                progress = start + ((end - start) * ratio)
                percent = int(ratio * 100)
                if percent == last_percent and now - last_emit < 0.5:
                    continue
                last_percent = percent
                last_emit = now
                self.worker_messages.put(("PROGRESS", progress, f"Downloading package ({percent}%)"))
        if total_size and downloaded != total_size:
            raise RuntimeError(f"Download incomplete: received {downloaded} of {total_size} bytes.")


    @staticmethod
    def _safe_remove_tree(path: Path) -> None:
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
        except OSError:
            shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _remove_tree_completely(path: Path) -> None:
        if not path.exists():
            return

        def on_error(function, target, _exc_info) -> None:
            try:
                os.chmod(target, 0o700)
                function(target)
            except OSError:
                raise

        last_error: Exception | None = None
        for _attempt in range(5):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
                else:
                    shutil.rmtree(path, onerror=on_error)
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
            if not path.exists():
                return
        if path.exists():
            detail = f": {last_error}" if last_error else ""
            raise RuntimeError(f"Could not fully remove {path}{detail}")

    def _assert_inside_work_folder(self, path: Path) -> None:
        if self.config.work_folder is None:
            raise RuntimeError("No work folder is active.")
        self._assert_inside_directory(path, self.config.work_folder)

    @staticmethod
    def _assert_inside_directory(path: Path, parent: Path) -> None:
        try:
            path.resolve().relative_to(parent.resolve())
        except ValueError as exc:
            raise RuntimeError(f"Refusing to write outside the expected folder: {path}") from exc

    @staticmethod
    def _archive_name_from_url(url: str, package_name: str = "") -> str:
        if package_name.lower().endswith(".7z"):
            return package_name
        lowered = url.lower().split("?", 1)[0]
        if lowered.endswith(".7z"):
            return "comfyui_portable.7z"
        if lowered.endswith(".zip"):
            return "comfyui_archive.zip"
        return "comfyui_archive.download"

    def _extract_archive(self, archive: Path, destination: Path, progress_callback=None) -> None:
        suffix = archive.suffix.lower()
        if suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                names = zf.infolist()
                total = max(len(names), 1)
                for index, item in enumerate(names, start=1):
                    self._raise_if_install_cancelled()
                    zf.extract(item, destination)
                    if progress_callback and index % 25 == 0:
                        ratio = min(index / total, 1.0)
                        progress_callback(0.78 + (0.12 * ratio), "Extracting archive")
            return
        if suffix == ".7z":
            seven_zip = App._prepare_local_7zr()
            if not seven_zip.exists():
                raise RuntimeError("Portable 7-Zip extractor is missing. Rebuild the EXE so assets\\7zr.exe is included.")
            self._run_7zr(seven_zip, ["t", str(archive)], "7-Zip integrity test failed", 0.78, 0.82, progress_callback)
            self._run_7zr(seven_zip, ["x", str(archive), f"-o{destination}", "-y"], "7-Zip extraction failed", 0.82, 0.9, progress_callback)
            return
        raise ValueError("Unsupported archive format. Use a .zip or .7z archive.")

    @staticmethod
    def _prepare_local_7zr() -> Path:
        if App._is_valid_windows_exe(LOCAL_SEVEN_ZIP_PATH):
            return LOCAL_SEVEN_ZIP_PATH
        if LOCAL_SEVEN_ZIP_PATH.exists():
            try:
                LOCAL_SEVEN_ZIP_PATH.unlink()
            except OSError:
                pass
        if not App._is_valid_windows_exe(BUNDLED_SEVEN_ZIP_PATH):
            return LOCAL_SEVEN_ZIP_PATH
        LOCAL_SEVEN_ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BUNDLED_SEVEN_ZIP_PATH, LOCAL_SEVEN_ZIP_PATH)
        return LOCAL_SEVEN_ZIP_PATH

    @staticmethod
    def _is_valid_windows_exe(path: Path) -> bool:
        try:
            if not path.exists() or path.stat().st_size < 102400:
                return False
            with path.open("rb") as file:
                return file.read(2) == b"MZ"
        except OSError:
            return False

    def _run_7zr(
        self,
        executable: Path,
        args: list[str],
        error_message: str,
        progress_start: float,
        progress_end: float,
        progress_callback=None,
    ) -> None:
        if not App._is_valid_windows_exe(executable):
            raise RuntimeError(f"{error_message}. Local 7-Zip executable is invalid or corrupted: {executable}")
        command = [str(executable), *args]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(APP_ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            last_emit = 0.0
            started_at = time.monotonic()
            phase = "Testing archive" if args and args[0] == "t" else "Extracting archive"
            while process.poll() is None:
                if self.install_cancel_requested.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise InstallationCancelled()
                now = time.monotonic()
                if progress_callback and now - last_emit >= 0.7:
                    elapsed_ratio = min((now - started_at) / 30.0, 0.92)
                    current = progress_start + ((progress_end - progress_start) * elapsed_ratio)
                    progress_callback(current, phase)
                    last_emit = now
                time.sleep(0.1)
            stdout, stderr = process.communicate()
        except OSError as exc:
            raise RuntimeError(f"{error_message}. Could not run local 7-Zip from {executable}: {exc}") from exc
        if process.returncode != 0:
            detail = (stderr or stdout or "").strip()
            raise RuntimeError(f"{error_message}. {detail}")
        if progress_callback:
            progress_callback(progress_end, phase)

    def _drain_worker_messages(self) -> None:
        processed = 0
        while processed < 40:
            try:
                message = self.worker_messages.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if isinstance(message, tuple) and len(message) == 3 and message[0] == "PROGRESS":
                self._set_install_progress(float(message[1]), str(message[2]))
            elif message == "__REFRESH__":
                self._refresh_instances()
            elif message == "__INSTALL_DONE__":
                self.install_in_progress = False
                self._unlock_app_after_installation()
                self.install_cancel_requested.clear()
                self.current_install_destination = None
                if hasattr(self, "install_button"):
                    self.install_button.configure(state="normal", text="Download and prepare instance")
            else:
                self._append_log(message)
        self.after(150, self._drain_worker_messages)

    def _set_detail_text(self, text: str) -> None:
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", text)
        self.detail_box.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        if not hasattr(self, "install_log"):
            return
        self.install_log.configure(state="normal")
        self.install_log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.install_log.see("end")
        self.install_log.configure(state="disabled")

    def _set_install_progress(self, value: float, label: str) -> None:
        value = max(0.0, min(1.0, value))
        if hasattr(self, "install_progress"):
            self.install_progress.set(value)
        if hasattr(self, "install_progress_label"):
            self.install_progress_label.configure(text=f"{int(value * 100)}%")
        if hasattr(self, "install_progress_status"):
            self.install_progress_status.configure(text=label or "Working...")

    def _is_inside_work_folder(self, path: Path) -> bool:
        if self.config.work_folder is None:
            return False
        try:
            path.resolve().relative_to(self.config.work_folder.resolve())
            return True
        except ValueError:
            return False

    def _clear_root(self) -> None:
        self._close_dropdown_popup()
        for child in self.winfo_children():
            child.destroy()

    @staticmethod
    def _looks_like_comfy(path: Path) -> bool:
        markers = ["main.py", "nodes.py", "comfy", "web"]
        return any((path / marker).exists() for marker in markers)

    def _resolve_comfy_root(self, instance_path: Path) -> Path:
        if self._looks_like_comfy(instance_path):
            return instance_path
        direct_comfy = instance_path / "ComfyUI"
        if self._looks_like_comfy(direct_comfy):
            return direct_comfy
        try:
            children = [item for item in instance_path.iterdir() if item.is_dir()]
        except OSError:
            return instance_path
        for child in children:
            if self._looks_like_comfy(child):
                return child
        return instance_path


if __name__ == "__main__":
    App().mainloop()
