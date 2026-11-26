"""Direct CLI interface for Nida Computer Use (HUD launcher, voice tester, and visual controls)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from src.config import load_config
from src.desktop_engine import DesktopEngine
from src.hud_app import launch_hud
from src.voice_engine import VoiceEngine


def main() -> None:
    parser = argparse.ArgumentParser(prog="nida", description="Nida Computer Use CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("hud", help="Launch the Always-On-Top Floating Arabic Control HUD")

    p_speak = sub.add_parser("speak", help="Speak Arabic text aloud (blocking)")
    p_speak.add_argument("text", type=str)

    sub.add_parser("test-voice", help="Run a live Arabic voice self-test")

    p_browser = sub.add_parser("browser", help="Open URL in user's real Chrome / active browser")
    p_browser.add_argument("url", nargs="?", default="")

    sub.add_parser("shot", help="Capture a screenshot and print metadata")
    sub.add_parser("windows", help="List open Windows applications")

    args = parser.parse_args()
    cfg = load_config()

    if args.cmd == "hud":
        launch_hud(cfg)
    elif args.cmd == "speak":
        res = VoiceEngine(cfg).speak(args.text, blocking=True)
        print(json.dumps(res, ensure_ascii=False))
    elif args.cmd == "test-voice":
        res = VoiceEngine(cfg).speak("أهلاً بك، نظام نداء الصوتي شغال بنجاح على جهازك.", blocking=True)
        print(json.dumps(res, ensure_ascii=False))
    elif args.cmd == "browser":
        print(json.dumps(DesktopEngine(cfg).open_in_user_browser(args.url), ensure_ascii=False))
    elif args.cmd == "shot":
        shot = DesktopEngine(cfg).capture_screen(annotate_grid=True)
        shot.pop("image_base64_jpeg", None)
        print(json.dumps(shot, ensure_ascii=False))
    elif args.cmd == "windows":
        print(json.dumps(DesktopEngine(cfg).list_windows(), ensure_ascii=False))


if __name__ == "__main__":
    main()
