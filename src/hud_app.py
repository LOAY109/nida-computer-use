"""Floating Arabic Control HUD Launcher (Guaranteed Always-On-Top on Windows) + Global Emergency Stop."""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import threading
import time
import urllib.request

from src.config import NidaConfig, load_config
from src.desktop_engine import find_browser_executable
from src.state_server import create_server


def is_hub_running(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=0.8) as resp:
            return resp.status == 200
    except Exception:
        return False


def _trigger_stop_http(base_url: str, reason: str) -> None:
    try:
        data = json.dumps({"action": "stop", "reason": reason}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/control",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=1.5)
    except Exception:
        pass


def start_global_kill_switch(base_url: str) -> None:
    """Listens globally for Ctrl+Shift+X or rapid double-Esc to immediately halt automation."""

    def _run() -> None:
        try:
            from pynput import keyboard

            pressed: set = set()
            last_esc_time = 0.0

            def on_press(key):
                nonlocal last_esc_time
                pressed.add(key)

                if key == keyboard.Key.esc:
                    now = time.time()
                    if now - last_esc_time <= 0.45:
                        _trigger_stop_http(base_url, "تم الإيقاف الفوري عبر ضغط Esc مرتين")
                        last_esc_time = 0.0
                    else:
                        last_esc_time = now

                has_ctrl = keyboard.Key.ctrl_l in pressed or keyboard.Key.ctrl_r in pressed
                has_shift = (
                    keyboard.Key.shift in pressed
                    or keyboard.Key.shift_r in pressed
                    or keyboard.Key.shift_l in pressed
                )
                is_x = getattr(key, "char", None) in ("x", "X", "\x18")
                if has_ctrl and has_shift and is_x:
                    _trigger_stop_http(base_url, "تم الإيقاف الفوري عبر الاختصار Ctrl+Shift+X")

            def on_release(key):
                pressed.discard(key)

            with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
                listener.join()
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def pin_hud_window_topmost() -> None:
    """Finds the Nida Floating HUD window on Windows and pins it Always-On-Top (HWND_TOPMOST)."""
    if sys.platform != "win32":
        return

    def _pin_loop() -> None:
        user32 = ctypes.windll.user32
        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        for _ in range(30):
            found = False

            def callback(hwnd, _lparam):
                nonlocal found
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "نداء" in buf.value:
                    user32.SetWindowPos(
                        hwnd,
                        HWND_TOPMOST,
                        0,
                        0,
                        0,
                        0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
                    )
                    found = True
                    return False
                return True

            user32.EnumWindows(EnumWindowsProc(callback), 0)
            if found:
                break
            time.sleep(0.4)

    threading.Thread(target=_pin_loop, daemon=True).start()


def _launch_tkinter_fallback(base_url: str) -> bool:
    """Zero-dependency native dark RTL Always-On-Top HUD fallback if Edge/Chrome/pywebview fail."""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("نداء — لوحة التحكم بالكمبيوتر")
        root.geometry("360x220+24+24")
        root.configure(bg="#0b0d11")
        root.attributes("-topmost", True)

        status_var = tk.StringVar(value="جاهز للاستخدام الشخصي")
        step_var = tk.StringVar(value="بانتظار الأوامر من أنتي جرافيتي")

        tk.Label(
            root, text="نداء — صلاحيات مفتوحة", bg="#0b0d11", fg="#10b981", font=("Segoe UI", 12, "bold")
        ).pack(pady=(10, 2))
        tk.Label(root, textvariable=status_var, bg="#0b0d11", fg="#8e96a6", font=("Segoe UI", 9)).pack()
        tk.Label(
            root, textvariable=step_var, bg="#131720", fg="#f3f1ec", font=("Segoe UI", 10), wraplength=320, pady=8, padx=10
        ).pack(fill="x", padx=12, pady=10)

        def send_ctrl(act: str) -> None:
            data = json.dumps({"action": act}).encode("utf-8")
            req = urllib.request.Request(
                f"{base_url}/api/control", data=data, headers={"Content-Type": "application/json"}, method="POST"
            )
            try:
                urllib.request.urlopen(req, timeout=1.0)
            except Exception:
                pass

        btn_row = tk.Frame(root, bg="#0b0d11")
        btn_row.pack(fill="x", padx=12, pady=4)
        tk.Button(
            btn_row, text="إيقاف فوري", bg="#ef4444", fg="#ffffff", font=("Segoe UI", 10, "bold"),
            relief="flat", command=lambda: send_ctrl("stop"), height=2
        ).pack(side="right", expand=True, fill="x", padx=(4, 0))
        tk.Button(
            btn_row, text="إيقاف مؤقت", bg="#1b212e", fg="#f3f1ec", font=("Segoe UI", 10),
            relief="flat", command=lambda: send_ctrl("pause"), height=2
        ).pack(side="right", expand=True, fill="x", padx=4)
        tk.Button(
            btn_row, text="استئناف", bg="#10b981", fg="#062118", font=("Segoe UI", 10, "bold"),
            relief="flat", command=lambda: send_ctrl("resume"), height=2
        ).pack(side="right", expand=True, fill="x", padx=(0, 4))

        def poll() -> None:
            try:
                with urllib.request.urlopen(f"{base_url}/api/state", timeout=0.6) as resp:
                    st = json.loads(resp.read().decode("utf-8"))
                    status_var.set(st.get("status", "idle"))
                    step_var.set(st.get("current_step", ""))
            except Exception:
                pass
            root.after(700, poll)

        poll()
        root.mainloop()
        return True
    except Exception:
        return False


def launch_hud(config: NidaConfig | None = None) -> None:
    cfg = config or load_config()

    if not is_hub_running(cfg.hud_base_url):
        srv, _ = create_server(cfg)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        for _ in range(30):
            if is_hub_running(cfg.hud_base_url):
                break
            time.sleep(0.1)

    start_global_kill_switch(cfg.hud_base_url)

    hud_profile = cfg.data_dir / "hud_browser_profile"
    hud_profile.mkdir(parents=True, exist_ok=True)
    for browser_name in ("edge", "chrome"):
        exe = find_browser_executable(browser_name)
        if exe:
            proc = subprocess.Popen(
                [
                    exe,
                    f"--app={cfg.hud_base_url}",
                    f"--user-data-dir={hud_profile}",
                    "--window-size=420,640",
                    "--window-position=24,24",
                    "--no-first-run",
                    "--disable-default-apps",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            pin_hud_window_topmost()
            proc.wait()
            return

    try:
        import webview

        webview.create_window(
            title="نداء — لوحة التحكم بالكمبيوتر",
            url=cfg.hud_base_url,
            width=420,
            height=620,
            x=24,
            y=24,
            resizable=True,
            on_top=True,
            background_color="#0b0d11",
        )
        webview.start()
        return
    except Exception:
        pass

    if _launch_tkinter_fallback(cfg.hud_base_url):
        return

    while True:
        time.sleep(10)


if __name__ == "__main__":
    launch_hud()
