#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/tts.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: ZetaJarvis Text-to-Speech (TTS) integration.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""ZetaJarvis Text-to-Speech (TTS) engine.

Two backends:
  - clone / gptsovits: Calls local voice cloning service to speak with reference voice; falls back automatically if offline.
  - say: System built-in voice — macOS uses `say`, Windows uses pyttsx3, zero dependency, instant.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import urllib.request

from . import config

_proc: subprocess.Popen | None = None

# Hide PowerShell window on Windows
_NO_WINDOW = 0x08000000 if config.IS_WINDOWS else 0


def _clean(text: str) -> str:
    """Removes markdown symbols and emojis unsuitable for reading aloud to make speech natural."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)      # Code blocks
    text = re.sub(r"[*_`#>\-]+", "", text)                  # Markdown symbols
    text = re.sub(r"https?://\S+", "website link", text)     # URLs
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", text)  # Emojis
    return text.strip()


def _play_file(path: str, blocking: bool) -> None:
    global _proc
    if config.IS_WINDOWS:
        # Play wav using PowerShell SoundPlayer; placed in a separate process so stop() can terminate it
        cmd = ["powershell", "-NoProfile", "-Command",
               f"(New-Object System.Media.SoundPlayer '{path}').PlaySync()"]
    else:
        cmd = ["afplay", path]
    if blocking:
        subprocess.run(cmd, creationflags=_NO_WINDOW)
    else:
        _proc = subprocess.Popen(cmd, creationflags=_NO_WINDOW)


def _speak_say(text: str, blocking: bool) -> None:
    """System built-in voice: macOS=say, Windows=pyttsx3."""
    global _proc
    if config.IS_WINDOWS:
        _speak_sapi(text, blocking)
        return
    cmd = ["say", "-v", config.TTS_VOICE, "-r", str(config.TTS_RATE), text]
    if blocking:
        subprocess.run(cmd)
    else:
        _proc = subprocess.Popen(cmd)


def _speak_sapi(text: str, blocking: bool) -> None:
    """Windows TTS using pyttsx3 – offline, multi-language, works on all Windows versions."""
    global _proc
    try:
        import pyttsx3
    except ImportError:
        print("⚠️  pyttsx3 not installed. Run: pip install pyttsx3")
        return
    
    def _speak():
        try:
            # Create engine in the thread that will use it
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            
            # Prefer English (US/UK/India) voices
            voice_set = False
            for v in voices:
                if 'zira' in v.name.lower() or 'david' in v.name.lower() or 'english' in v.name.lower():
                    engine.setProperty('voice', v.id)
                    voice_set = True
                    break
            
            # If no English voice found, use first available
            if not voice_set and voices:
                engine.setProperty('voice', voices[0].id)
            
            engine.setProperty('rate', 180)
            engine.setProperty('volume', 1.0)
            
            # Check for custom voice from environment
            voice_name = os.environ.get("JARVIS_VOICE", "")
            if voice_name:
                for v in voices:
                    if voice_name.lower() in v.name.lower():
                        engine.setProperty('voice', v.id)
                        break
            
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"⚠️  TTS error: {e}")
    
    if blocking:
        _speak()
    else:
        thread = threading.Thread(target=_speak, daemon=True)
        thread.start()


def _speak_clone(text: str, blocking: bool) -> bool:
    """Requests voice cloning service to synthesize and play. Returns True on success, False on failure."""
    try:
        req = urllib.request.Request(
            config.VOICE_SERVER + "/tts",
            data=text.encode("utf-8"), method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        path = obj.get("path")
        if not path:
            return False
        _play_file(path, blocking)
        return True
    except Exception:  # noqa: BLE001
        return False


def _speak_gptsovits(text: str, blocking: bool) -> bool:
    """Requests local GPT-SoVITS API (v2) to synthesize and play. Returns False on failure to allow fallback."""
    import tempfile
    payload = json.dumps({
        "text": text,
        "text_lang": config.GPTSOVITS_TEXT_LANG,
        "ref_audio_path": config.GPTSOVITS_REF,
        "prompt_text": config.GPTSOVITS_PROMPT,
        "prompt_lang": config.GPTSOVITS_PROMPT_LANG,
        "text_split_method": "cut5",
        "media_type": "wav",
        "streaming_mode": False,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            config.GPTSOVITS_URL + "/tts", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if not data or len(data) < 100:        # Error response is usually JSON text rather than raw audio data
            return False
        path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        with open(path, "wb") as f:
            f.write(data)
        _play_file(path, blocking)
        return True
    except Exception:  # noqa: BLE001
        return False


def speak(text: str, blocking: bool = True) -> None:
    """Speaks text aloud. Automatically falls back to system TTS if cloning backends are unavailable."""
    text = _clean(text)
    if not text:
        return
    stop()  # Interrupt the previous utterance first
    backend = config.TTS_BACKEND
    if backend == "gptsovits" and _speak_gptsovits(text, blocking):
        return
    if backend == "clone" and _speak_clone(text, blocking):
        return
    _speak_say(text, blocking)


def stop() -> None:
    """Interrupts current speech playback."""
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
    _proc = None
