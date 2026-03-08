from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlparse, urlunparse


CREATE_NO_WINDOW = 0x08000000
OPENCLAW_CONTROL_UI_TABS = {
    "agents",
    "channels",
    "chat",
    "config",
    "cron",
    "debug",
    "instances",
    "logs",
    "nodes",
    "overview",
    "sessions",
    "skills",
    "usage",
}


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = get_app_dir()
CONFIG_PATH = APP_DIR / "desktop_cat_panel_config.json"
RUNTIME_PATH = APP_DIR / "desktop_cat_runtime.json"
DEVICE_IDENTITY_PATH = APP_DIR / "openclaw_device_identity.json"
CAT_EXE_PATH = APP_DIR / "Pawly.exe"
CAT_SCRIPT_PATH = APP_DIR / "desktop_cat.py"


def normalize_openclaw_url(openclaw_url: str) -> str:
    url = openclaw_url.strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"http://{url}"
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[-1].lower() in OPENCLAW_CONTROL_UI_TABS:
        path_parts = path_parts[:-1]
    normalized_path = "/" + "/".join(path_parts) if path_parts else ""
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", parsed.query, parsed.fragment))


def load_config() -> dict:
    default_payload = {
        "openclaw_url": os.environ.get("OPENCLAW_URL", ""),
        "openclaw_token": os.environ.get("OPENCLAW_TOKEN", ""),
    }
    if not CONFIG_PATH.exists():
        return default_payload
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return default_payload
    return {
        "openclaw_url": str(payload.get("openclaw_url", default_payload["openclaw_url"])),
        "openclaw_token": str(payload.get("openclaw_token", default_payload["openclaw_token"])),
    }


def save_config(payload: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_pid_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False

    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    output = completed.stdout.strip()
    return completed.returncode == 0 and f'"{pid}"' in output


def load_runtime_pid() -> int | None:
    if not RUNTIME_PATH.exists():
        return None
    try:
        payload = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
        pid = int(payload["pid"])
        if is_pid_running(pid):
            return pid
    except Exception:
        pass
    clear_runtime_file()
    return None


def clear_runtime_file() -> None:
    if RUNTIME_PATH.exists():
        RUNTIME_PATH.unlink(missing_ok=True)


def load_device_id() -> str:
    if not DEVICE_IDENTITY_PATH.exists():
        return ""
    try:
        payload = json.loads(DEVICE_IDENTITY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    device_id = str(payload.get("deviceId", "")).strip()
    return device_id


def resolve_python_command() -> list[str] | None:
    executable_candidates: list[Path] = []
    if Path(sys.executable).suffix.lower() == ".exe":
        executable_candidates.append(Path(sys.executable).with_name("pythonw.exe"))
        executable_candidates.append(Path(sys.executable).with_name("python.exe"))

    for candidate in executable_candidates:
        if candidate.exists():
            return [str(candidate)]

    for command in ("pythonw.exe", "python.exe", "python"):
        resolved = shutil.which(command)
        if resolved:
            return [resolved]

    return None


def resolve_cat_command(openclaw_url: str, openclaw_token: str) -> list[str]:
    normalized_url = normalize_openclaw_url(openclaw_url)
    if CAT_EXE_PATH.exists():
        command = [str(CAT_EXE_PATH)]
    elif CAT_SCRIPT_PATH.exists():
        python_command = resolve_python_command()
        if not python_command:
            raise RuntimeError("未找到 Python 运行环境，无法启动小猫。")
        command = python_command + [str(CAT_SCRIPT_PATH)]
    else:
        raise RuntimeError("未找到 OpenClaw 小猫程序。")

    if normalized_url:
        command += ["--openclaw-url", normalized_url]
    if openclaw_token.strip():
        command += ["--openclaw-token", openclaw_token.strip()]
    return command


def stop_cat_process() -> bool:
    pid = load_runtime_pid()
    if pid is None:
        clear_runtime_file()
        return False

    completed = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode == 0 or not is_pid_running(pid):
        clear_runtime_file()
        return True
    return False


class DesktopCatPanel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Pawly")
        self.root.geometry("560x430")
        self.root.resizable(False, False)
        self.colors = {
            "bg": "#f3f6fb",
            "card": "#ffffff",
            "border": "#d8e1f0",
            "text": "#162033",
            "muted": "#6b7280",
            "accent": "#4f7cff",
            "accent_hover": "#3e6cf0",
            "accent_pressed": "#3159cf",
            "danger": "#d9485f",
            "danger_bg": "#fff1f2",
            "success": "#1f8f5f",
            "input_bg": "#f8faff",
        }
        self.root.configure(bg=self.colors["bg"])

        config = load_config()
        self.openclaw_url_var = tk.StringVar(value=config.get("openclaw_url", ""))
        self.openclaw_token_var = tk.StringVar(value=config.get("openclaw_token", ""))
        self.device_id_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="准备就绪")
        self.status_hold_until = 0.0

        self.configure_fonts()
        self.configure_styles()
        self.build_ui()
        self.fit_window_to_content()
        self.refresh_device_id()
        self.set_status("准备就绪")
        self.refresh_status()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def configure_fonts(self) -> None:
        family = "Microsoft YaHei UI"
        self.title_font = tkfont.Font(family=family, size=16, weight="bold")
        self.subtitle_font = tkfont.Font(family=family, size=9)
        self.label_font = tkfont.Font(family=family, size=10, weight="bold")
        self.body_font = tkfont.Font(family=family, size=10)
        self.status_font = tkfont.Font(family=family, size=11, weight="bold")

        try:
            default_font = tkfont.nametofont("TkDefaultFont")
            default_font.configure(family=family, size=10)
            text_font = tkfont.nametofont("TkTextFont")
            text_font.configure(family=family, size=10)
            fixed_font = tkfont.nametofont("TkFixedFont")
            fixed_font.configure(family="Consolas", size=10)
        except Exception:
            pass

    def configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Panel.TFrame", background=self.colors["bg"])
        style.configure("Card.TFrame", background=self.colors["card"])
        style.configure(
            "Title.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["text"],
            font=self.title_font,
        )
        style.configure(
            "Subtitle.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["muted"],
            font=self.subtitle_font,
        )
        style.configure(
            "Card.TLabel",
            background=self.colors["card"],
            foreground=self.colors["text"],
            font=self.label_font,
        )
        style.configure(
            "Hint.TLabel",
            background=self.colors["card"],
            foreground=self.colors["muted"],
            font=self.subtitle_font,
        )
        style.configure(
            "StatusTitle.TLabel",
            background=self.colors["card"],
            foreground=self.colors["muted"],
            font=self.subtitle_font,
        )
        style.configure(
            "StatusInfo.TLabel",
            background=self.colors["card"],
            foreground=self.colors["text"],
            font=self.status_font,
        )
        style.configure(
            "StatusSuccess.TLabel",
            background=self.colors["card"],
            foreground=self.colors["success"],
            font=self.status_font,
        )
        style.configure(
            "StatusDanger.TLabel",
            background=self.colors["card"],
            foreground=self.colors["danger"],
            font=self.status_font,
        )
        style.configure(
            "Modern.TEntry",
            fieldbackground=self.colors["input_bg"],
            foreground=self.colors["text"],
            padding=(10, 9),
            borderwidth=1,
            relief="solid",
        )
        style.map(
            "Modern.TEntry",
            fieldbackground=[("focus", "#ffffff")],
            lightcolor=[("focus", self.colors["accent"])],
            darkcolor=[("focus", self.colors["accent"])],
            bordercolor=[("focus", self.colors["accent"])],
        )
        style.configure(
            "Primary.TButton",
            font=self.body_font,
            padding=(16, 10),
            borderwidth=0,
            relief="flat",
            background=self.colors["accent"],
            foreground="#ffffff",
        )
        style.map(
            "Primary.TButton",
            background=[
                ("pressed", self.colors["accent_pressed"]),
                ("active", self.colors["accent_hover"]),
            ],
            foreground=[("disabled", "#eef2ff")],
        )
        style.configure(
            "Secondary.TButton",
            font=self.body_font,
            padding=(16, 10),
            borderwidth=1,
            relief="solid",
            background=self.colors["card"],
            foreground=self.colors["text"],
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("pressed", "#e6ecff"),
                ("active", "#f3f7ff"),
            ],
        )
        style.configure(
            "Danger.TButton",
            font=self.body_font,
            padding=(16, 10),
            borderwidth=1,
            relief="solid",
            background=self.colors["danger_bg"],
            foreground=self.colors["danger"],
        )
        style.map(
            "Danger.TButton",
            background=[
                ("pressed", "#ffd7dd"),
                ("active", "#ffe6ea"),
            ],
        )

    def build_ui(self) -> None:
        container = ttk.Frame(self.root, style="Panel.TFrame", padding=20)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container, style="Panel.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Pawly Console", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="连接 OpenClaw、启动桌宠，并查看当前运行状态。",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        card_shell = tk.Frame(container, bg=self.colors["border"], bd=0, highlightthickness=0)
        card_shell.pack(fill="x", pady=(18, 12))
        card = tk.Frame(card_shell, bg=self.colors["card"], padx=18, pady=18)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        form = ttk.Frame(card, style="Card.TFrame")
        form.pack(fill="both", expand=True)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Gateway 地址 / OpenClaw 地址", style="Card.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.url_entry = ttk.Entry(form, textvariable=self.openclaw_url_var, style="Modern.TEntry")
        self.url_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 6))
        ttk.Label(
            form,
            text="支持示例：127.0.0.1:18789、192.168.1.20:18789、https://demo.example.com/overview",
            style="Hint.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(
            form,
            text="注：可填写本机地址、局域网 IP、服务器域名或带 /overview 的面板地址，程序会自动规范化。",
            style="Hint.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(form, text="OpenClaw Token（可留空）", style="Card.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(14, 0))
        self.token_entry = ttk.Entry(form, textvariable=self.openclaw_token_var, style="Modern.TEntry", show="*")
        self.token_entry.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 6))
        ttk.Label(
            form,
            text="如果地址里已经带有 token，这里可以留空。",
            style="Hint.TLabel",
        ).grid(row=6, column=0, columnspan=2, sticky="w")

        ttk.Label(form, text="设备 ID（OpenClaw 配对用）", style="Card.TLabel").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(14, 0)
        )
        device_row = ttk.Frame(form, style="Card.TFrame")
        device_row.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 6))
        device_row.columnconfigure(0, weight=1)
        self.device_id_entry = ttk.Entry(device_row, textvariable=self.device_id_var, style="Modern.TEntry")
        self.device_id_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(device_row, text="复制 ID", style="Secondary.TButton", command=self.on_copy_device_id).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(device_row, text="刷新 ID", style="Secondary.TButton", command=self.on_refresh_device_id).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Label(
            form,
            text="如果 OpenClaw 提示 pairing-required 或 not-paired，批准这里显示的 Device ID 即可，不用翻日志。",
            style="Hint.TLabel",
        ).grid(row=9, column=0, columnspan=2, sticky="w")

        button_row = ttk.Frame(form, style="Card.TFrame")
        button_row.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)

        ttk.Button(button_row, text="保存设置", style="Secondary.TButton", command=self.on_save).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(button_row, text="启动小猫", style="Primary.TButton", command=self.on_start).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )
        ttk.Button(button_row, text="关闭小猫", style="Danger.TButton", command=self.on_stop).grid(
            row=1, column=0, sticky="ew", padx=(0, 6), pady=(10, 0)
        )
        ttk.Button(button_row, text="打开目录", style="Secondary.TButton", command=self.on_open_folder).grid(
            row=1, column=1, sticky="ew", padx=(6, 0), pady=(10, 0)
        )

        status_shell = tk.Frame(container, bg=self.colors["border"], bd=0, highlightthickness=0)
        status_shell.pack(fill="x")
        status_card = tk.Frame(status_shell, bg=self.colors["card"], padx=18, pady=14)
        status_card.pack(fill="x", padx=1, pady=1)

        status_frame = ttk.Frame(status_card, style="Card.TFrame")
        status_frame.pack(fill="x")
        ttk.Label(status_frame, text="运行状态", style="StatusTitle.TLabel").pack(anchor="w")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, style="StatusInfo.TLabel")
        self.status_label.pack(anchor="w", pady=(6, 0))

        self.url_entry.focus_set()

    def fit_window_to_content(self) -> None:
        self.root.update_idletasks()
        width = max(560, self.root.winfo_reqwidth() + 8)
        height = max(430, self.root.winfo_reqheight() + 8)
        self.root.geometry(f"{width}x{height}")

    def set_status(self, message: str, tone: str = "info", hold_ms: int = 0) -> None:
        style_name = {
            "info": "StatusInfo.TLabel",
            "success": "StatusSuccess.TLabel",
            "danger": "StatusDanger.TLabel",
        }.get(tone, "StatusInfo.TLabel")
        self.status_var.set(message)
        if hasattr(self, "status_label"):
            self.status_label.configure(style=style_name)
        self.status_hold_until = time.monotonic() + hold_ms / 1000 if hold_ms > 0 else 0.0

    def refresh_device_id(self) -> str:
        device_id = load_device_id()
        if device_id:
            self.device_id_var.set(device_id)
        else:
            self.device_id_var.set("未生成（先点一次“启动小猫”）")
        return device_id

    def on_refresh_device_id(self) -> None:
        device_id = self.refresh_device_id()
        if device_id:
            self.set_status("设备 ID 已刷新", tone="success", hold_ms=1200)
        else:
            self.set_status("还没有设备 ID，先启动一次小猫", tone="info", hold_ms=1600)

    def on_copy_device_id(self) -> None:
        device_id = self.refresh_device_id()
        if not device_id:
            messagebox.showinfo(
                "设备 ID 未生成",
                "先点击一次“启动小猫”，程序会自动生成设备身份文件。\n"
                "如果 OpenClaw 提示 pairing-required 或 not-paired，再回来复制这里的 Device ID。",
                parent=self.root,
            )
            self.set_status("还没有设备 ID，先启动一次小猫", tone="info", hold_ms=1600)
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(device_id)
        self.root.update()
        self.set_status("设备 ID 已复制到剪贴板", tone="success", hold_ms=1400)

    def on_save(self) -> None:
        payload = {
            "openclaw_url": normalize_openclaw_url(self.openclaw_url_var.get()),
            "openclaw_token": self.openclaw_token_var.get().strip(),
        }
        save_config(payload)
        self.openclaw_url_var.set(payload["openclaw_url"])
        self.openclaw_token_var.set(payload["openclaw_token"])
        self.set_status("已保存 OpenClaw 配置", tone="success", hold_ms=1400)

    def on_start(self) -> None:
        self.on_save()
        stop_cat_process()
        try:
            command = resolve_cat_command(self.openclaw_url_var.get(), self.openclaw_token_var.get())
        except RuntimeError as exc:
            messagebox.showerror("启动失败", str(exc), parent=self.root)
            self.set_status("启动失败，请检查配置", tone="danger", hold_ms=2200)
            return

        subprocess.Popen(
            command,
            cwd=APP_DIR,
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.set_status("小猫启动中……", tone="info", hold_ms=1200)
        self.root.after(500, self.refresh_device_id)
        self.root.after(800, self.refresh_status)

    def on_stop(self) -> None:
        stopped = stop_cat_process()
        if stopped:
            self.set_status("小猫已关闭", tone="info", hold_ms=900)
        else:
            self.set_status("当前没有运行中的小猫", tone="info", hold_ms=1200)
        self.root.after(300, self.refresh_status)

    def on_open_folder(self) -> None:
        os.startfile(str(APP_DIR))

    def on_close(self) -> None:
        pid = load_runtime_pid()
        if pid is None:
            self.root.destroy()
            return

        result = messagebox.askyesnocancel(
            "退出 Pawly",
            f"检测到小猫仍在运行（PID {pid}）。\n\n"
            "选择“是”会同时关闭小猫。\n"
            "选择“否”只关闭面板，小猫继续运行。\n"
            "选择“取消”返回面板。",
            parent=self.root,
            icon="question",
        )
        if result is None:
            return
        if result:
            stopped = stop_cat_process()
            if not stopped:
                messagebox.showerror("关闭失败", "未能关闭正在运行的小猫，请先点击“关闭小猫”再退出面板。", parent=self.root)
                self.refresh_status()
                return
        self.root.destroy()

    def refresh_status(self) -> None:
        pid = load_runtime_pid()
        self.refresh_device_id()
        now = time.monotonic()
        if pid is None:
            if now >= self.status_hold_until:
                self.set_status("未运行", tone="info")
        else:
            self.set_status(f"运行中（PID {pid}）", tone="success")
        self.root.after(1500, self.refresh_status)


def main() -> None:
    root = tk.Tk()
    DesktopCatPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
