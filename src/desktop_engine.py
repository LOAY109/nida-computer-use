"""Unrestricted Personal Desktop Automation Engine for Windows (Nida Computer Use)."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional

from src.config import NidaConfig


class EmergencyStopError(RuntimeError):
    """Raised immediately when the user activates Emergency Stop in the HUD or via hotkey."""


class DesktopEngine:
    """Drives the user's real screen, mouse, keyboard, apps, and shell with zero artificial blocks."""

    def __init__(
        self,
        config: NidaConfig,
        state_poller: Optional[Callable[[], str]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.config = config
        self._state_poller = state_poller
        self._log = log_callback or (lambda msg, lvl="action": None)
        self._scale_x = 1.0
        self._scale_y = 1.0
        self._setup_pyautogui()

    def _setup_pyautogui(self) -> None:
        try:
            import pyautogui

            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = max(0.02, self.config.action_delay_ms / 1000.0)
        except Exception:
            pass

    def check_control(self) -> None:
        """Checks HUD control state before every action. Blocks while paused; aborts on stop."""
        if not self._state_poller:
            return
        while True:
            st = self._state_poller()
            if st == "stopped":
                self.release_all_inputs()
                raise EmergencyStopError("تم إيقاف التحكم فوراً بناءً على طلب المستخدم.")
            if st == "paused":
                time.sleep(0.25)
                continue
            return

    def release_all_inputs(self) -> None:
        """Immediately release all modifier keys and mouse buttons on Emergency Stop."""
        try:
            import pyautogui

            for key in ("ctrl", "shift", "alt", "win"):
                try:
                    pyautogui.keyUp(key)
                except Exception:
                    pass
            for btn in ("left", "right", "middle"):
                try:
                    pyautogui.mouseUp(button=btn)
                except Exception:
                    pass
        except Exception:
            pass

    def _to_real_coords(self, x: int, y: int, normalized: bool = False) -> tuple[int, int]:
        if normalized:
            return int(round(x * self._scale_x)), int(round(y * self._scale_y))
        return int(x), int(y)

    def capture_screen(
        self,
        monitor_index: int = 1,
        annotate_grid: bool = False,
        save_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Capture screen, optionally overlay coordinate grid, return file path + base64 JPEG."""
        self.check_control()
        import mss
        from PIL import Image, ImageDraw

        with mss.mss() as sct:
            monitors = sct.monitors
            idx = monitor_index if 0 <= monitor_index < len(monitors) else 1
            mon = monitors[idx]
            raw = sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.rgb)

        orig_w, orig_h = img.size
        target_w = min(orig_w, self.config.screenshot_max_width)
        scale = orig_w / float(target_w)
        target_h = int(round(orig_h / scale))

        self._scale_x = scale
        self._scale_y = scale

        if target_w != orig_w:
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)

        if annotate_grid:
            draw = ImageDraw.Draw(img)
            step = 160
            for gx in range(step, target_w, step):
                draw.line([(gx, 0), (gx, target_h)], fill=(16, 185, 129), width=1)
                draw.text((gx + 4, 4), str(int(gx * scale)), fill=(16, 185, 129))
            for gy in range(step, target_h, step):
                draw.line([(0, gy), (target_w, gy)], fill=(16, 185, 129), width=1)
                draw.text((4, gy + 4), str(int(gy * scale)), fill=(16, 185, 129))

        fname = save_name or f"screen_{int(time.time() * 1000)}.jpg"
        out_path = self.config.screenshots_dir / fname
        img.save(out_path, format="JPEG", quality=82, optimize=True)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        self._log(f"التقاط لقطة شاشة ({orig_w}x{orig_h})", "action")
        return {
            "path": str(out_path),
            "original_width": orig_w,
            "original_height": orig_h,
            "image_width": target_w,
            "image_height": target_h,
            "scale_factor": round(scale, 4),
            "image_base64_jpeg": b64,
        }

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        from_scaled_image: bool = False,
    ) -> dict[str, Any]:
        self.check_control()
        import pyautogui

        rx, ry = self._to_real_coords(x, y, normalized=from_scaled_image)
        pyautogui.click(x=rx, y=ry, clicks=clicks, button=button)
        self._log(f"نقر ({button} ×{clicks}) عند ({rx}, {ry})", "action")
        return {"ok": True, "x": rx, "y": ry, "button": button, "clicks": clicks}

    def move(self, x: int, y: int, duration: float = 0.15, from_scaled_image: bool = False) -> dict[str, Any]:
        self.check_control()
        import pyautogui

        rx, ry = self._to_real_coords(x, y, normalized=from_scaled_image)
        pyautogui.moveTo(rx, ry, duration=duration)
        return {"ok": True, "x": rx, "y": ry}

    def drag(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: float = 0.35,
        button: str = "left",
        from_scaled_image: bool = False,
    ) -> dict[str, Any]:
        self.check_control()
        import pyautogui

        sx, sy = self._to_real_coords(x1, y1, normalized=from_scaled_image)
        ex, ey = self._to_real_coords(x2, y2, normalized=from_scaled_image)
        pyautogui.moveTo(sx, sy, duration=0.1)
        pyautogui.dragTo(ex, ey, duration=duration, button=button)
        self._log(f"سحب من ({sx},{sy}) إلى ({ex},{ey})", "action")
        return {"ok": True, "from": [sx, sy], "to": [ex, ey]}

    def scroll(
        self,
        amount: int,
        x: Optional[int] = None,
        y: Optional[int] = None,
        from_scaled_image: bool = False,
    ) -> dict[str, Any]:
        self.check_control()
        import pyautogui

        if x is not None and y is not None:
            rx, ry = self._to_real_coords(x, y, normalized=from_scaled_image)
            pyautogui.scroll(amount, x=rx, y=ry)
        else:
            pyautogui.scroll(amount)
        self._log(f"تمرير الشاشة بمقدار {amount}", "action")
        return {"ok": True, "amount": amount}

    def type_text(self, text: str, press_enter: bool = False) -> dict[str, Any]:
        """Types both Arabic/Unicode and English reliably (clipboard paste for Unicode)."""
        self.check_control()
        import pyautogui
        import pyperclip

        has_non_ascii = any(ord(ch) > 127 for ch in text)
        if has_non_ascii or "\n" in text:
            previous = ""
            try:
                previous = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.08)
            try:
                pyperclip.copy(previous)
            except Exception:
                pass
            method = "unicode_clipboard_paste"
        else:
            pyautogui.write(text, interval=0.015)
            method = "direct_keys"

        if press_enter:
            pyautogui.press("enter")

        preview = text[:36] + ("…" if len(text) > 36 else "")
        self._log(f"كتابة نص: {preview}", "action")
        return {"ok": True, "method": method, "length": len(text)}

    def hotkey(self, keys: list[str]) -> dict[str, Any]:
        self.check_control()
        import pyautogui

        cleaned = [k.strip().lower() for k in keys if k.strip()]
        if len(cleaned) == 1:
            pyautogui.press(cleaned[0])
        elif len(cleaned) > 1:
            pyautogui.hotkey(*cleaned)
        self._log(f"اختصار لوحة مفاتيح: {' + '.join(cleaned)}", "action")
        return {"ok": True, "keys": cleaned}

    def list_windows(self) -> list[dict[str, Any]]:
        self.check_control()
        try:
            import pygetwindow as gw

            items = []
            for win in gw.getAllWindows():
                title = (win.title or "").strip()
                if not title:
                    continue
                items.append(
                    {
                        "title": title,
                        "left": win.left,
                        "top": win.top,
                        "width": win.width,
                        "height": win.height,
                        "active": bool(getattr(win, "isActive", False)),
                        "minimized": bool(getattr(win, "isMinimized", False)),
                    }
                )
            return items
        except Exception as exc:
            return [{"error": str(exc)}]

    def focus_window(self, title_query: str) -> dict[str, Any]:
        self.check_control()
        import pygetwindow as gw

        q = title_query.lower().strip()
        for win in gw.getAllWindows():
            if q in (win.title or "").lower():
                try:
                    if win.isMinimized:
                        win.restore()
                    win.activate()
                    self._log(f"التركيز على النافذة: {win.title}", "action")
                    return {"ok": True, "title": win.title}
                except Exception as exc:
                    return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": f"لم يتم العثور على نافذة تطابق: {title_query}"}

    def launch_app(self, target: str, args: str = "") -> dict[str, Any]:
        """Open any local Windows application, executable, folder, or protocol unrestricted."""
        self.check_control()
        self._log(f"تشغيل تطبيق: {target}", "action")
        if sys.platform == "win32":
            if args:
                subprocess.Popen(f'start "" "{target}" {args}', shell=True)
            else:
                os.startfile(target)  # type: ignore[attr-defined]
            return {"ok": True, "launched": target, "args": args}
        subprocess.Popen([target] + (args.split() if args else []))
        return {"ok": True, "launched": target}

    def open_url(self, url: str) -> dict[str, Any]:
        self.check_control()
        self._log(f"فتح رابط: {url}", "action")
        webbrowser.open(url)
        return {"ok": True, "url": url}

    def run_shell(self, command: str, timeout: int = 30) -> dict[str, Any]:
        """Execute PowerShell/shell commands directly in unrestricted personal mode."""
        self.check_control()
        self._log(f"تنفيذ أمر نظام: {command[:50]}", "action")
        shell_cmd = (
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
            if sys.platform == "win32"
            else ["bash", "-lc", command]
        )
        proc = subprocess.run(
            shell_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-2000:],
        }

    def get_ui_tree(self, max_elements: int = 60) -> dict[str, Any]:
        """Inspect interactive UI controls of the active foreground window on Windows via UIA."""
        self.check_control()
        if sys.platform != "win32":
            return {"ok": False, "reason": "UI tree inspection is currently Windows-only."}

        ps_script = f"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::FocusedElement
if (-not $root) {{ '[]'; exit }}
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$win = $root
while ($win -and $win.Current.ControlType.ProgrammaticName -ne 'ControlType.Window') {{
    $parent = $walker.GetParent($win)
    if (-not $parent -or $parent -eq [System.Windows.Automation.AutomationElement]::RootElement) {{ break }}
    $win = $parent
}}
$cond = [System.Windows.Automation.Condition]::TrueCondition
$els = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
$out = @()
foreach ($el in $els) {{
    if ($out.Count -ge {int(max_elements)}) {{ break }}
    try {{
        $name = $el.Current.Name
        $rect = $el.Current.BoundingRectangle
        $ctype = $el.Current.ControlType.ProgrammaticName -replace 'ControlType\\.', ''
        if ($name -and -not [double]::IsInfinity($rect.X) -and $rect.Width -gt 4 -and $rect.Height -gt 4) {{
            $out += [PSCustomObject]@{{
                name = $name
                type = $ctype
                x = [int]($rect.X + $rect.Width / 2)
                y = [int]($rect.Y + $rect.Height / 2)
                w = [int]$rect.Width
                h = [int]$rect.Height
            }}
        }}
    }} catch {{}}
}}
$out | ConvertTo-Json -Compress
"""
        res = self.run_shell(ps_script, timeout=15)
        try:
            parsed = json.loads(res["stdout"].strip() or "[]")
            if isinstance(parsed, dict):
                parsed = [parsed]
            return {"ok": True, "elements": parsed}
        except Exception:
            return {"ok": False, "raw": res["stdout"], "stderr": res["stderr"]}

    def run_plan(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute a multi-step batch plan with per-step emergency stop/pause verification."""
        results = []
        for idx, step in enumerate(steps, start=1):
            self.check_control()
            kind = str(step.get("action", "")).lower()
            if kind == "click":
                r = self.click(
                    int(step["x"]),
                    int(step["y"]),
                    button=step.get("button", "left"),
                    clicks=int(step.get("clicks", 1)),
                    from_scaled_image=bool(step.get("from_scaled_image", False)),
                )
            elif kind == "move":
                r = self.move(
                    int(step["x"]),
                    int(step["y"]),
                    from_scaled_image=bool(step.get("from_scaled_image", False)),
                )
            elif kind == "drag":
                r = self.drag(
                    int(step["x1"]),
                    int(step["y1"]),
                    int(step["x2"]),
                    int(step["y2"]),
                    from_scaled_image=bool(step.get("from_scaled_image", False)),
                )
            elif kind == "scroll":
                r = self.scroll(int(step.get("amount", -300)), step.get("x"), step.get("y"))
            elif kind == "type":
                r = self.type_text(str(step.get("text", "")), press_enter=bool(step.get("press_enter", False)))
            elif kind == "hotkey":
                r = self.hotkey(list(step.get("keys", [])))
            elif kind == "wait":
                ms = int(step.get("ms", 500))
                time.sleep(ms / 1000.0)
                r = {"ok": True, "waited_ms": ms}
            elif kind == "launch_app":
                r = self.launch_app(str(step["target"]), str(step.get("args", "")))
            elif kind == "open_url":
                r = self.open_url(str(step["url"]))
            elif kind == "focus_window":
                r = self.focus_window(str(step["title"]))
            else:
                r = {"ok": False, "error": f"Unknown step action: {kind}"}
            results.append({"step": idx, "action": kind, "result": r})
        return {"ok": True, "completed_steps": len(results), "results": results}
