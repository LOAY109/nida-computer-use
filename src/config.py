"""Central configuration for Nida Computer Use (Personal Unrestricted Mode)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NidaConfig:
    plugin_root: Path
    data_dir: Path
    hud_host: str = "127.0.0.1"
    hud_port: int = 8765
    unrestricted_personal_mode: bool = True
    tts_voice: str = "ar-SA-HamedNeural"
    tts_rate: str = "+4%"
    stt_language: str = "ar-SA"
    voice_enabled: bool = True
    auto_launch_hud: bool = True
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"
    screenshot_max_width: int = 1600
    action_delay_ms: int = 120

    @property
    def hud_base_url(self) -> str:
        return f"http://{self.hud_host}:{self.hud_port}"

    @property
    def screenshots_dir(self) -> Path:
        path = self.data_dir / "screenshots"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def audio_cache_dir(self) -> Path:
        path = self.data_dir / "audio"
        path.mkdir(parents=True, exist_ok=True)
        return path


def load_config() -> NidaConfig:
    plugin_root = Path(
        os.environ.get("NIDA_PLUGIN_ROOT", Path(__file__).resolve().parent.parent)
    )
    default_data = Path.home() / ".nida-computer-use"
    data_dir = Path(os.environ.get("NIDA_DATA_DIR", default_data))
    data_dir.mkdir(parents=True, exist_ok=True)

    return NidaConfig(
        plugin_root=plugin_root,
        data_dir=data_dir,
        hud_host=os.environ.get("NIDA_HUD_HOST", "127.0.0.1"),
        hud_port=int(os.environ.get("NIDA_HUD_PORT", "8765")),
        unrestricted_personal_mode=os.environ.get("NIDA_PERSONAL_UNRESTRICTED", "1") == "1",
        tts_voice=os.environ.get("NIDA_TTS_VOICE", "ar-SA-HamedNeural"),
        tts_rate=os.environ.get("NIDA_TTS_RATE", "+4%"),
        stt_language=os.environ.get("NIDA_STT_LANG", "ar-SA"),
        voice_enabled=os.environ.get("NIDA_VOICE_ENABLED", "1") == "1",
        auto_launch_hud=os.environ.get("NIDA_AUTO_HUD", "1") == "1",
        elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=os.environ.get("NIDA_ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB"),
    )
