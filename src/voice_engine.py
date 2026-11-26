"""Arabic Voice Engine (Neural TTS + Optional ElevenLabs + Offline SAPI + Arabic STT)."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from src.config import NidaConfig


class VoiceEngine:
    """Handles Arabic text-to-speech playback and microphone speech-to-text."""

    def __init__(self, config: NidaConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._speaking = False
        self._stop_requested = False

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def stop_speaking(self) -> None:
        self._stop_requested = True
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

    def speak(self, text: str, blocking: bool = False, voice: Optional[str] = None) -> dict:
        """Speak Arabic text aloud using Edge Neural TTS -> ElevenLabs -> SAPI fallback."""
        clean_text = (text or "").strip()
        if not clean_text:
            return {"spoken": False, "reason": "empty_text"}
        if not self.config.voice_enabled:
            return {"spoken": False, "reason": "voice_muted"}

        chosen_voice = voice or self.config.tts_voice
        self._stop_requested = False

        if blocking:
            ok, engine = self._speak_sync(clean_text, chosen_voice)
            return {"spoken": ok, "engine": engine, "voice": chosen_voice}

        t = threading.Thread(
            target=self._speak_sync,
            args=(clean_text, chosen_voice),
            daemon=True,
        )
        t.start()
        return {"spoken": True, "engine": "async", "voice": chosen_voice}

    def _speak_sync(self, text: str, voice: str) -> tuple[bool, str]:
        with self._lock:
            self._speaking = True
            try:
                if self.config.elevenlabs_api_key:
                    audio_path = self._synthesize_elevenlabs(text)
                    if audio_path and audio_path.exists():
                        self._play_audio_file(audio_path)
                        return True, "elevenlabs"

                audio_path = self._synthesize_edge_tts(text, voice)
                if audio_path and audio_path.exists():
                    self._play_audio_file(audio_path)
                    return True, f"edge-tts:{voice}"

                if self._speak_offline_sapi(text):
                    return True, "offline-sapi"

                return False, "none"
            finally:
                self._speaking = False

    def _cache_path(self, key: str, ext: str = "mp3") -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return self.config.audio_cache_dir / f"nida_{digest}.{ext}"

    def _synthesize_edge_tts(self, text: str, voice: str) -> Optional[Path]:
        try:
            import edge_tts

            out_path = self._cache_path(f"edge:{voice}:{self.config.tts_rate}:{text}", "mp3")
            if out_path.exists() and out_path.stat().st_size > 256:
                return out_path

            async def _run() -> None:
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=voice,
                    rate=self.config.tts_rate,
                )
                await communicate.save(str(out_path))

            asyncio.run(_run())
            return out_path if out_path.exists() else None
        except Exception:
            return None

    def _synthesize_elevenlabs(self, text: str) -> Optional[Path]:
        try:
            import httpx

            out_path = self._cache_path(f"el:{self.config.elevenlabs_voice_id}:{text}", "mp3")
            if out_path.exists() and out_path.stat().st_size > 256:
                return out_path

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.config.elevenlabs_voice_id}"
            headers = {
                "xi-api-key": self.config.elevenlabs_api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }
            payload = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.78},
            }
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                out_path.write_bytes(resp.content)
            return out_path
        except Exception:
            return None

    def _play_audio_file(self, path: Path) -> None:
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if self._stop_requested:
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.05)
            pygame.mixer.music.unload()
            return
        except Exception:
            pass

        if sys.platform == "win32":
            ps_script = (
                "Add-Type -AssemblyName presentationCore; "
                "$p = New-Object System.Windows.Media.MediaPlayer; "
                f"$p.Open([Uri]'{str(path)}'); "
                "$p.Play(); "
                "Start-Sleep -Milliseconds 400; "
                "while ($p.NaturalDuration.HasTimeSpan -and $p.Position -lt $p.NaturalDuration.TimeSpan) "
                "{ Start-Sleep -Milliseconds 100 }; "
                "$p.Close();"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _speak_offline_sapi(self, text: str) -> bool:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception:
            pass

        if sys.platform == "win32":
            safe_text = text.replace("'", " ")
            ps_script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Speak('{safe_text}');"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return res.returncode == 0
        return False

    def listen_arabic(self, timeout: float = 8.0, phrase_time_limit: float = 15.0) -> dict:
        """Capture spoken Arabic from default microphone and transcribe (ar-SA)."""
        try:
            import speech_recognition as sr

            recognizer = sr.Recognizer()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            transcript = recognizer.recognize_google(audio, language=self.config.stt_language)
            return {"ok": True, "transcript": transcript}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "transcript": ""}
