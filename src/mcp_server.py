"""Google Antigravity MCP Server for Nida Computer Use (Arabic Voice + Floating HUD + Full Personal Control)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from src.config import load_config
from src.desktop_engine import DesktopEngine, EmergencyStopError

cfg = load_config()
mcp = FastMCP("nida-desktop")


def _http_get(path: str, timeout: float = 2.0) -> dict[str, Any]:
    with urllib.request.urlopen(f"{cfg.hud_base_url}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(path: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{cfg.hud_base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_hud_running() -> bool:
    """Guarantees the local Control Hub and Floating Arabic HUD are active."""
    try:
        res = _http_get("/api/health", timeout=0.6)
        if res.get("ok"):
            return True
    except Exception:
        pass

    if not cfg.auto_launch_hud:
        return False

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )

    subprocess.Popen(
        [sys.executable, "-m", "src.hud_app"],
        cwd=str(cfg.plugin_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    for _ in range(30):
        time.sleep(0.15)
        try:
            if _http_get("/api/health", timeout=0.6).get("ok"):
                return True
        except Exception:
            continue
    return False


def _poll_control_state() -> str:
    try:
        st = _http_get("/api/state", timeout=0.8)
        return str(st.get("status", "running"))
    except Exception:
        return "running"


def _hud_log(message: str, level: str = "action", status: Optional[str] = None) -> None:
    try:
        payload: dict[str, Any] = {"log": message, "level": level}
        if status:
            payload["status"] = status
            payload["step"] = message
        _http_post("/api/internal/status", payload, timeout=1.5)
    except Exception:
        pass


def _attach_user_steering(result: dict[str, Any]) -> dict[str, Any]:
    """Reads any live Arabic steering instructions typed/spoken by the user in the Floating HUD."""
    try:
        cmds = _http_get("/api/internal/commands", timeout=0.8).get("commands", [])
        if cmds:
            result["user_hud_instructions"] = cmds
    except Exception:
        pass
    return result


engine = DesktopEngine(
    config=cfg,
    state_poller=_poll_control_state,
    log_callback=lambda msg, lvl="action": _hud_log(msg, level=lvl),
)


def _begin_action(step_label: str) -> None:
    ensure_hud_running()
    st = _poll_control_state()
    if st == "stopped":
        raise EmergencyStopError("تم إيقاف التحكم الفوري من لوحة نداء. اضغط استئناف أو إعادة تهيئة للمتابعة.")
    _hud_log(step_label, level="action", status="running")


@mcp.tool()
def hud_launch() -> str:
    """Launch and verify the Floating Arabic Control HUD window."""
    ok = ensure_hud_running()
    return json.dumps(
        {"ok": ok, "hud_url": cfg.hud_base_url, "unrestricted_mode": cfg.unrestricted_personal_mode},
        ensure_ascii=False,
    )


@mcp.tool()
def hud_status() -> str:
    """Read current HUD control state (running/paused/stopped) and any direct user commands."""
    ensure_hud_running()
    st = _http_get("/api/state", timeout=2.0)
    return json.dumps(_attach_user_steering(st), ensure_ascii=False)


@mcp.tool()
def voice_speak(message: str, blocking: bool = False) -> str:
    """Speak a natural Arabic status update aloud to the user instead of only replying in chat."""
    ensure_hud_running()
    res = _http_post(
        "/api/internal/speak",
        {"text": message, "blocking": blocking},
        timeout=30.0 if blocking else 5.0,
    )
    return json.dumps(_attach_user_steering(res), ensure_ascii=False)


@mcp.tool()
def voice_ask(
    question: str,
    options: Optional[list[str]] = None,
    timeout_seconds: int = 300,
) -> str:
    """Speak a question aloud in Arabic and wait for the user's spoken or typed reply in the Floating Arabic HUD."""
    ensure_hud_running()
    res = _http_post(
        "/api/internal/ask",
        {
            "question": question,
            "options": options or ["كمل", "لا، وقف", "عدل الخطوة"],
            "timeout": timeout_seconds,
        },
        timeout=float(timeout_seconds + 15),
    )
    return json.dumps(res, ensure_ascii=False)


@mcp.tool()
def screen_capture(annotate_grid: bool = False, monitor_index: int = 1) -> list[Any]:
    """Capture the current Windows desktop screen and return both the image and exact screen dimensions."""
    try:
        _begin_action("التقاط لقطة شاشة لتحليل الواجهة")
        shot = engine.capture_screen(monitor_index=monitor_index, annotate_grid=annotate_grid)
        b64 = shot.pop("image_base64_jpeg")
        meta = _attach_user_steering(shot)
        return [
            ImageContent(type="image", data=b64, mimeType="image/jpeg"),
            TextContent(type="text", text=json.dumps(meta, ensure_ascii=False)),
        ]
    except EmergencyStopError as exc:
        return [TextContent(type="text", text=json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False))]


@mcp.tool()
def mouse_click(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
    from_scaled_image: bool = False,
) -> str:
    """Click at (x, y) on the screen."""
    try:
        _begin_action(f"النقر عند ({x}, {y})")
        res = engine.click(x, y, button=button, clicks=clicks, from_scaled_image=from_scaled_image)
        return json.dumps(_attach_user_steering(res), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def mouse_drag(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration: float = 0.35,
    from_scaled_image: bool = False,
) -> str:
    """Drag the mouse from (x1, y1) to (x2, y2)."""
    try:
        _begin_action(f"سحب المؤشر من ({x1},{y1}) إلى ({x2},{y2})")
        res = engine.drag(x1, y1, x2, y2, duration=duration, from_scaled_image=from_scaled_image)
        return json.dumps(_attach_user_steering(res), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def mouse_scroll(amount: int, x: Optional[int] = None, y: Optional[int] = None) -> str:
    """Scroll the mouse wheel (positive = up, negative = down)."""
    try:
        _begin_action(f"تمرير الشاشة ({amount})")
        res = engine.scroll(amount, x=x, y=y)
        return json.dumps(_attach_user_steering(res), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def keyboard_type(text: str, press_enter: bool = False) -> str:
    """Type Arabic or English text reliably at the active cursor."""
    try:
        _begin_action("كتابة نص على الشاشة")
        res = engine.type_text(text, press_enter=press_enter)
        return json.dumps(_attach_user_steering(res), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def keyboard_hotkey(keys: list[str]) -> str:
    """Press a key or keyboard shortcut, e.g. ['ctrl', 'c'] or ['win', 'r'] or ['enter']."""
    try:
        _begin_action(f"ضغط الاختصار {' + '.join(keys)}")
        res = engine.hotkey(keys)
        return json.dumps(_attach_user_steering(res), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def window_list() -> str:
    """List all open desktop windows with their titles and positions."""
    try:
        _begin_action("فحص النوافذ المفتوحة")
        return json.dumps(_attach_user_steering({"windows": engine.list_windows()}), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def window_focus(title_query: str) -> str:
    """Bring a window matching title_query to the foreground."""
    try:
        _begin_action(f"الانتقال إلى نافذة: {title_query}")
        return json.dumps(_attach_user_steering(engine.focus_window(title_query)), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def app_launch(target: str, args: str = "") -> str:
    """Launch any Windows app, executable, file, or folder directly without restrictions."""
    try:
        _begin_action(f"تشغيل التطبيق: {target}")
        return json.dumps(_attach_user_steering(engine.launch_app(target, args=args)), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def url_open(url: str) -> str:
    """Open any website or web app (e.g. Gmail, Outlook, GitHub) directly in the user's browser."""
    try:
        _begin_action(f"فتح الرابط: {url}")
        return json.dumps(_attach_user_steering(engine.open_url(url)), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def shell_run(command: str, timeout: int = 30) -> str:
    """Run a PowerShell command directly on the user's PC (unrestricted personal mode)."""
    try:
        _begin_action("تنفيذ أمر نظام مباشر")
        return json.dumps(_attach_user_steering(engine.run_shell(command, timeout=timeout)), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def ui_tree(max_elements: int = 60) -> str:
    """Inspect UIAutomation elements (buttons, text fields, links + center coordinates) of the active window."""
    try:
        _begin_action("قراءة عناصر الواجهة التفاعلية")
        return json.dumps(_attach_user_steering(engine.get_ui_tree(max_elements=max_elements)), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def plan_run(steps: list[dict[str, Any]]) -> str:
    """Execute multiple desktop actions in a single call with instant stop/pause checks between every step."""
    try:
        _begin_action(f"تنفيذ خطة من {len(steps)} خطوات")
        return json.dumps(_attach_user_steering(engine.run_plan(steps)), ensure_ascii=False)
    except EmergencyStopError as exc:
        return json.dumps({"stopped": True, "error": str(exc)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")
