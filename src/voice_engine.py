"""Arabic Voice Engine (Edge Neural TTS + Optional ElevenLabs + Offline SAPI + Win32 MCI Player + Arabic STT)."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from src.config import NidaConfig


class VoiceEngine:
    """Reliable Arabic TTS playback (no premature cutoff) and microphone STT."""

    def __init__(self, config: NidaConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._speaking = False
        self._stop_requested = False
        self._active_mci_alias: Optional[str] = None
        self._queue: queue.Queue[tuple[str, str, threading.Event]] = queue.Queue()
        self._worker = threading.Thread(target=self._queue_loop, daemon=True)
        self._worker.start()

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def _mci_send(self, command: str) -> tuple[int, str]:
        if sys.platform != "win32":
            return -1, ""
        buf = ctypes.create_unicode_buffer(256)
        err = ctypes.windll.winmm.mciSendStringW(command, buf, 255, 0)
        return int(err), buf.value

    def stop_speaking(self) -> None:
        self._stop_requested = True
        while not self._queue.empty():
            try:
                _, _, done_evt = self._queue.get_nowait()
                done_evt.set()
            except queue.Empty:
                break

        if self._active_mci_alias:
            try:
                self._mci_send(f"stop {self._active_mci_alias}")
                self._mci_send(f"close {self._active_mci_alias}")
            except Exception:
                pass
            self._active_mci_alias = None

        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

    def _queue_loop(self) -> None:
        while True:
            text, voice, done_evt = self._queue.get()
            try:
                self._speak_sync(text, voice)
            finally:
                done_evt.set()

    def speak(self, text: str, blocking: bool = True, voice: Optional[str] = None) -> dict:
        """Speak Arabic text aloud reliably using Edge Neural TTS -> ElevenLabs -> SAPI fallback."""
        clean_text = (text or "").strip()
        if not clean_text:
            return {"spoken": False, "reason": "empty_text"}
        if not self.config.voice_enabled:
            return {"spoken": False, "reason": "voice_muted"}

        chosen_voice = voice or self.config.tts_voice
        self._stop_requested = False

        if blocking:
            ok, engine, player = self._speak_sync(clean_text, chosen_voice)
            return {"spoken": ok, "engine": engine, "player": player, "voice": chosen_voice}

        done_evt = threading.Event()
        self._queue.put((clean_text, chosen_voice, done_evt))
        return {"spoken": True, "queued": True, "voice": chosen_voice}

    def _speak_sync(self, text: str, voice: str) -> tuple[bool, str, str]:
        with self._lock:
            self._speaking = True
            self._stop_requested = False
            try:
                if self.config.elevenlabs_api_key:
                    audio_path = self._synthesize_elevenlabs(text)
                    if audio_path and audio_path.exists():
                        player = self._play_audio_file(audio_path)
                        if player:
                            return True, "elevenlabs", player

                audio_path = self._synthesize_edge_tts(text, voice)
                if audio_path and audio_path.exists():
                    player = self._play_audio_file(audio_path)
                    if player:
                        return True, f"edge-tts:{voice}", player

                if self._speak_offline_sapi(text):
                    return True, "offline-sapi", "sapi"

                return False, "none", "none"
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

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run())
            finally:
                loop.close()

            return out_path if out_path.exists() and out_path.stat().st_size > 256 else None
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
            return out_path if out_path.exists() else None
        except Exception:
            return None

    def _play_with_winmm_mci(self, path: Path) -> bool:
        """Native Windows WinMM MCI MP3 player — zero dependencies, never cuts off early."""
        if sys.platform != "win32":
            return False
        alias = f"nida_{uuid.uuid4().hex[:8]}"
        safe_path = str(path.resolve())
        err, _ = self._mci_send(f'open "{safe_path}" type mpegvideo alias {alias}')
        if err != 0:
            return False
        self._active_mci_alias = alias
        try:
            err, _ = self._mci_send(f"play {alias}")
            if err != 0:
                return False
            time.sleep(0.12)
            while True:
                if self._stop_requested:
                    self._mci_send(f"stop {alias}")
                    break
                err, mode = self._mci_send(f"status {alias} mode")
                if err != 0 or mode.strip().lower() != "playing":
                    break
                time.sleep(0.08)
            return True
        finally:
            self._mci_send(f"close {alias}")
            if self._active_mci_alias == alias:
                self._active_mci_alias = None

    def _play_audio_file(self, path: Path) -> str:
        if sys.platform == "win32" and self._play_with_winmm_mci(path):
            return "winmm_mci"

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
            return "pygame"
        except Exception:
            pass

        if sys.platform == "win32":
            safe = str(path.resolve()).replace("'", "''")
            ps_script = (
                "Add-Type -AssemblyName presentationCore; "
                "$p = New-Object System.Windows.Media.MediaPlayer; "
                f"$p.Open([Uri]'{safe}'); "
                "$p.Play(); "
                "$waited = 0; "
                "while (-not $p.NaturalDuration.HasTimeSpan -and $waited -lt 4000) { Start-Sleep -Milliseconds 100; $waited += 100 }; "
                "if ($p.NaturalDuration.HasTimeSpan) { "
                "  while ($p.Position -lt $p.NaturalDuration.TimeSpan) { Start-Sleep -Milliseconds 120 } "
                "} else { Start-Sleep -Seconds 3 }; "
                "$p.Close();"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if res.returncode == 0:
                return "powershell_media"

        return ""

    def _speak_offline_sapi(self, text: str) -> bool:
        if sys.platform == "win32":
            safe_text = text.replace("'", " ").replace("\n", " ")
            ps_script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$ar = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'ar-*' } | Select-Object -First 1; "
                "if ($ar) { $s.SelectVoice($ar.VoiceInfo.Name) }; "
                f"$s.Speak('{safe_text}');"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if res.returncode == 0:
                return True

        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception:
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
