"""Direct CLI interface for Nida Computer Use (useful for testing or script-only execution)."""

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

    sub.add_parser("hud", help="Launch the Floating Arabic Control HUD")

    p_speak = sub.add_parser("speak", help="Speak Arabic text aloud")
    p_speak.add_argument("text", type=str)
    p_speak.add_argument("--blocking", action="store_true")

    sub.add_parser("shot", help="Capture a screenshot and print metadata")
    sub.add_parser("windows", help="List open Windows applications")

    p_shell = sub.add_parser("shell", help="Run a PowerShell command")
    p_shell.add_argument("command", type=str)

    args = parser.parse_args()
    cfg = load_config()

    if args.cmd == "hud":
        launch_hud(cfg)
    elif args.cmd == "speak":
        res = VoiceEngine(cfg).speak(args.text, blocking=True)
        print(json.dumps(res, ensure_ascii=False))
    elif args.cmd == "shot":
        shot = DesktopEngine(cfg).capture_screen()
        shot.pop("image_base64_jpeg", None)
        print(json.dumps(shot, ensure_ascii=False))
    elif args.cmd == "windows":
        print(json.dumps(DesktopEngine(cfg).list_windows(), ensure_ascii=False))
    elif args.cmd == "shell":
        print(json.dumps(DesktopEngine(cfg).run_shell(args.command), ensure_ascii=False))


if __name__ == "__main__":
    main()
