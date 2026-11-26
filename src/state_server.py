"""Local HTTP Control Hub bridging the MCP Server, Floating Arabic HUD, and Kill-Switch."""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from src.config import NidaConfig, load_config
from src.voice_engine import VoiceEngine


class ControlHubState:
    """Thread-safe shared state for Nida Computer Use."""

    def __init__(self, config: NidaConfig) -> None:
        self.config = config
        self.voice = VoiceEngine(config)
        self._lock = threading.Lock()
        self.status: str = "idle"
        self.current_step: str = "جاهز لاستلام الأوامر"
        self.logs: list[dict[str, Any]] = []
        self.pending_question: Optional[dict[str, Any]] = None
        self._question_event = threading.Event()
        self._question_answer: Optional[dict[str, Any]] = None
        self.user_commands: list[dict[str, Any]] = []
        self.add_log("تم تشغيل مركز التحكم الشخصي (صلاحيات مفتوحة)", level="info")

    def add_log(self, message: str, level: str = "action") -> None:
        with self._lock:
            entry = {
                "id": uuid.uuid4().hex[:8],
                "time": datetime.now().strftime("%H:%M:%S"),
                "message": message,
                "level": level,
            }
            self.logs.insert(0, entry)
            self.logs = self.logs[:60]

    def set_status(self, status: str, step: Optional[str] = None) -> None:
        with self._lock:
            self.status = status
            if step is not None:
                self.current_step = step

    def trigger_stop(self, reason: str = "تم الإيقاف الفوري بواسطة المستخدم") -> None:
        with self._lock:
            self.status = "stopped"
            self.current_step = reason
            self._question_answer = {"stopped": True, "answer": "__STOPPED__", "via": "kill_switch"}
            self._question_event.set()
            self.pending_question = None
        self.voice.stop_speaking()
        self.add_log(reason, level="stop")

    def trigger_pause(self) -> None:
        with self._lock:
            if self.status in ("running", "waiting_user"):
                self.status = "paused"
                self.current_step = "متوقف مؤقتاً — اضغط استئناف للمتابعة"
        self.add_log("تم الإيقاف المؤقت من لوحة التحكم", level="warn")

    def trigger_resume(self) -> None:
        with self._lock:
            if self.status in ("paused", "stopped"):
                self.status = "running"
                self.current_step = "تم الاستئناف — جاري المتابعة"
        self.add_log("تم استئناف العمل", level="info")

    def trigger_reset(self) -> None:
        with self._lock:
            self.status = "idle"
            self.current_step = "جاهز لاستلام الأوامر"
            self.pending_question = None
            self._question_answer = None
            self._question_event.clear()
        self.add_log("تمت إعادة تعيين الحالة للوضع الجاهز", level="info")

    def start_question(self, question: str, options: Optional[list[str]] = None) -> dict[str, Any]:
        qid = uuid.uuid4().hex[:10]
        with self._lock:
            self.status = "waiting_user"
            self.current_step = "بانتظار ردك بالصوت أو الكتابة"
            self.pending_question = {
                "id": qid,
                "question": question,
                "options": options or ["كمل", "لا، وقف", "عدل الخطوة"],
                "created_at": time.time(),
            }
            self._question_answer = None
            self._question_event.clear()
        self.add_log(f"سؤال صوتي: {question}", level="voice")
        self.voice.speak(question, blocking=False)
        return self.pending_question

    def submit_reply(self, question_id: str, answer: str, via: str = "text") -> bool:
        with self._lock:
            if not self.pending_question:
                return False
            if question_id and self.pending_question["id"] != question_id:
                return False
            self._question_answer = {
                "stopped": False,
                "answer": answer.strip(),
                "via": via,
            }
            self.pending_question = None
            self.status = "running"
            self.current_step = f"تم استلام ردك: {answer.strip()[:50]}"
            self._question_event.set()
        self.add_log(f"ردك ({'صوت' if via == 'voice' else 'كتابة'}): {answer.strip()}", level="user")
        return True

    def wait_for_reply(self, timeout: float = 300.0) -> dict[str, Any]:
        answered = self._question_event.wait(timeout=timeout)
        with self._lock:
            if not answered:
                self.pending_question = None
                self.status = "idle"
                return {"stopped": False, "timeout": True, "answer": ""}
            result = self._question_answer or {"stopped": False, "answer": ""}
            self._question_answer = None
            return result

    def push_user_command(self, text: str, via: str = "text") -> dict[str, Any]:
        clean = text.strip()
        with self._lock:
            cmd = {
                "id": uuid.uuid4().hex[:8],
                "time": datetime.now().strftime("%H:%M:%S"),
                "text": clean,
                "via": via,
            }
            self.user_commands.append(cmd)
        self.add_log(f"توجيه مباشر منك: {clean}", level="user")
        return cmd

    def pop_user_commands(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self.user_commands)
            self.user_commands.clear()
            return items

    def update_settings(self, payload: dict[str, Any]) -> None:
        with self._lock:
            if "voice_enabled" in payload:
                self.config.voice_enabled = bool(payload["voice_enabled"])
            if "tts_voice" in payload and payload["tts_voice"]:
                self.config.tts_voice = str(payload["tts_voice"])
            if "tts_rate" in payload and payload["tts_rate"]:
                self.config.tts_rate = str(payload["tts_rate"])

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "current_step": self.current_step,
                "voice_enabled": self.config.voice_enabled,
                "tts_voice": self.config.tts_voice,
                "tts_rate": self.config.tts_rate,
                "unrestricted_mode": self.config.unrestricted_personal_mode,
                "is_speaking": self.voice.is_speaking,
                "pending_question": self.pending_question,
                "pending_commands_count": len(self.user_commands),
                "logs": self.logs[:35],
            }


def create_server(config: Optional[NidaConfig] = None) -> tuple[ThreadingHTTPServer, ControlHubState]:
    cfg = config or load_config()
    state = ControlHubState(cfg)
    hud_html_path = Path(__file__).resolve().parent / "hud_ui.html"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {}

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                if hud_html_path.exists():
                    content = hud_html_path.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self._send_json({"error": "hud_ui.html not found"}, HTTPStatus.NOT_FOUND)
                return

            if self.path == "/api/health":
                self._send_json({"ok": True, "service": "nida-control-hub"})
                return

            if self.path == "/api/state":
                self._send_json(state.snapshot())
                return

            if self.path == "/api/internal/commands":
                self._send_json({"commands": state.pop_user_commands()})
                return

            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            payload = self._read_json()

            if self.path == "/api/control":
                action = str(payload.get("action", "")).lower()
                if action == "stop":
                    state.trigger_stop(payload.get("reason", "تم الإيقاف الفوري من لوحة التحكم"))
                elif action == "pause":
                    state.trigger_pause()
                elif action == "resume":
                    state.trigger_resume()
                elif action == "reset":
                    state.trigger_reset()
                else:
                    self._send_json({"error": "unknown_action"}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"ok": True, "state": state.snapshot()})
                return

            if self.path == "/api/reply":
                ok = state.submit_reply(
                    question_id=str(payload.get("question_id", "")),
                    answer=str(payload.get("answer", "")),
                    via=str(payload.get("via", "text")),
                )
                self._send_json({"ok": ok, "state": state.snapshot()})
                return

            if self.path == "/api/command":
                text = str(payload.get("text", "")).strip()
                if not text:
                    self._send_json({"ok": False, "error": "empty"}, HTTPStatus.BAD_REQUEST)
                    return
                if state.pending_question:
                    state.submit_reply(state.pending_question["id"], text, via=str(payload.get("via", "text")))
                    self._send_json({"ok": True, "routed_to": "reply", "state": state.snapshot()})
                    return
                cmd = state.push_user_command(text, via=str(payload.get("via", "text")))
                self._send_json({"ok": True, "command": cmd, "state": state.snapshot()})
                return

            if self.path == "/api/settings":
                state.update_settings(payload)
                self._send_json({"ok": True, "state": state.snapshot()})
                return

            if self.path == "/api/listen":
                res = state.voice.listen_arabic(
                    timeout=float(payload.get("timeout", 8.0)),
                    phrase_time_limit=float(payload.get("phrase_time_limit", 15.0)),
                )
                self._send_json(res)
                return

            if self.path == "/api/internal/status":
                if "status" in payload:
                    state.set_status(str(payload["status"]), payload.get("step"))
                if payload.get("log"):
                    state.add_log(str(payload["log"]), level=str(payload.get("level", "action")))
                self._send_json({"ok": True, "status": state.status})
                return

            if self.path == "/api/internal/speak":
                res = state.voice.speak(
                    text=str(payload.get("text", "")),
                    blocking=bool(payload.get("blocking", False)),
                    voice=payload.get("voice"),
                )
                if payload.get("text"):
                    state.add_log(f"نطق صوتي: {payload['text']}", level="voice")
                self._send_json(res)
                return

            if self.path == "/api/internal/ask":
                question = str(payload.get("question", "")).strip()
                options = payload.get("options")
                timeout = float(payload.get("timeout", 300.0))
                state.start_question(question, options=options)
                reply = state.wait_for_reply(timeout=timeout)
                self._send_json(reply)
                return

            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    server = ThreadingHTTPServer((cfg.hud_host, cfg.hud_port), Handler)
    return server, state


if __name__ == "__main__":
    cfg = load_config()
    srv, _ = create_server(cfg)
    print(f"Nida Control Hub listening on {cfg.hud_base_url}", flush=True)
    srv.serve_forever()
