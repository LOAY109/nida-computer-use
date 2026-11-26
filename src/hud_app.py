"""Floating Arabic Control HUD Launcher + Global Emergency Stop Hotkey Guard."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from src.config import NidaConfig, load_config
from src.state_server import create_server


def is_hub_running(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=0.8) as resp:
            return resp.status == 200
    except Exception:
        return False


def _trigger_stop_http(base_url: str, reason: str) -> None:
    try:
        import json

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
                has_shift = keyboard.Key.shift in pressed or keyboard.Key.shift_r in pressed or keyboard.Key.shift_l in pressed
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


def launch_hud(config: NidaConfig | None = None) -> None:
    cfg = config or load_config()

    if not is_hub_running(cfg.hud_base_url):
        srv, _ = create_server(cfg)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        for _ in range(25):
            if is_hub_running(cfg.hud_base_url):
                break
            time.sleep(0.1)

    start_global_kill_switch(cfg.hud_base_url)

    try:
        import webview

        webview.create_window(
            title="نداء — التحكم بالكمبيوتر",
            url=cfg.hud_base_url,
            width=410,
            height=600,
            x=28,
            y=28,
            resizable=True,
            on_top=True,
            background_color="#0b0d11",
        )
        webview.start()
        return
    except Exception:
        pass

    for browser in ("msedge", "chrome", "chromium"):
        exe = shutil.which(browser)
        if exe:
            subprocess.Popen(
                [
                    exe,
                    f"--app={cfg.hud_base_url}",
                    "--window-size=420,620",
                    "--window-position=30,30",
                ]
            )
            while True:
                time.sleep(10)

    print(f"Nida HUD available at {cfg.hud_base_url}", flush=True)
    while True:
        time.sleep(10)


if __name__ == "__main__":
    launch_hud()
