#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/config.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: Configuration parameters and key loader.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""ZetaJarvis configuration module."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Load env variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

# ---- Platform Detection (Jarvis supports macOS and Windows) ---------------------------
IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
OS_NAME = "Windows" if IS_WINDOWS else "macOS" if IS_MACOS else "Linux"

# ---- Adjustable Parameters ----------------------------------------------------------


def _read_first_line(filename: str) -> str:
    """Reads the first non-empty, non-comment (#) line of a file in the project root; returns empty string if not found."""
    p = _ROOT / filename
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return ""


# LLM Model Name (Jarvis's Brain). Priority: Env var JARVIS_MODEL > model.txt > default.
# When using an API gateway, enter the model name supported by the gateway (e.g., deepseek-chat, gpt-4o, etc.).
MODEL = (os.environ.get("JARVIS_MODEL") or _read_first_line("model.txt")
         or "deepseek-chat").strip()
MAX_TOKENS = 1024

# API gateway (OpenAI-compatible) URL. Priority: Env var JARVIS_BASE_URL > base_url.txt.
# Example: https://your-gateway/v1 (Jarvis will automatically append /chat/completions)
LLM_BASE_URL = (os.environ.get("JARVIS_BASE_URL")
                or _read_first_line("base_url.txt")).strip()


def llm_endpoint() -> str:
    """Constructs the chat/completions endpoint URL."""
    base = LLM_BASE_URL.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


# Whisper ASR model size: tiny / base / small / medium / large-v3
# small is balanced; use medium for higher accuracy (slower, larger download); use base on weaker hardware.
WHISPER_MODEL = os.environ.get("JARVIS_WHISPER", "small")
WHISPER_COMPUTE = "int8"          # Use int8 compute for CPU execution speed
# Auto-language detection: None = Whisper auto-detect language
# Set JARVIS_LANGUAGE=en for English-only, or leave empty/auto for multi-language
_lang = os.environ.get("JARVIS_LANGUAGE", "").strip()
ASR_LANGUAGE = None if not _lang or _lang == "auto" else _lang

# ---- ASR Precision/Speed Knobs (larger = more accurate but slower) ------------------------------
# Beam search size: 1=greedy (fastest, lower precision), 3=balanced, 5=most accurate (adds ~350ms latency). Configurable via JARVIS_ASR_BEAM.
ASR_BEAM = int(os.environ.get("JARVIS_ASR_BEAM", "5"))
# VAD silent segment filtering: enabled = reduces hallucinated words from noise, slightly slower.
ASR_VAD = os.environ.get("JARVIS_ASR_VAD", "1") not in ("0", "false", "False")
# Initial prompt for speech recognition (None = no language bias for multi-language support)
# Can include common words/names to help recognition: "Jarvis, Alpha, deepseek"
# For multi-language: leave empty or set to common English/Hindi words
ASR_INITIAL_PROMPT = os.environ.get("JARVIS_ASR_PROMPT") or None

# ---- iFlytek Cloud ASR (Speech Transcription IAT) -------------------------------------
# Three credentials: Env vars have higher priority; otherwise reads xfyun.txt in project root.


def _load_xfyun() -> tuple[str, str, str]:
    appid = os.environ.get("JARVIS_XFYUN_APPID", "").strip()
    apikey = os.environ.get("JARVIS_XFYUN_APIKEY", "").strip()
    secret = os.environ.get("JARVIS_XFYUN_APISECRET", "").strip()
    if not (appid and apikey and secret):
        p = _ROOT / "xfyun.txt"
        if p.exists():
            vals = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.strip().startswith("#")]
            if len(vals) >= 3:
                appid = appid or vals[0]
                apikey = apikey or vals[1]
                secret = secret or vals[2]
    return appid, apikey, secret


XFYUN_APP_ID, XFYUN_API_KEY, XFYUN_API_SECRET = _load_xfyun()

# ASR backend: local = local Whisper, xfyun = iFlytek Cloud (more accurate).
# Default: uses xfyun if all 3 credentials are provided, otherwise local. Configurable via JARVIS_ASR_BACKEND.
ASR_BACKEND = (os.environ.get("JARVIS_ASR_BACKEND")
               or ("xfyun" if (XFYUN_APP_ID and XFYUN_API_KEY
                               and XFYUN_API_SECRET) else "local")).strip()

# TTS Backend:
#   gptsovits = Calls local GPT-SoVITS API to speak with cloned voice (recommended)
#   clone     = Uses built-in XTTS voice cloning service (voice_clone/serve.py)
#   say       = System built-in voice (macOS say / Windows pyttsx3)
# Falls back automatically to system voice if cloning backends are unreachable.
TTS_BACKEND = os.environ.get("JARVIS_TTS", "say")
VOICE_SERVER = os.environ.get("JARVIS_VOICE_SERVER", "http://127.0.0.1:5111")

# ---- GPT-SoVITS Backend Parameters ----
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GPTSOVITS_URL = os.environ.get("GPTSOVITS_URL", "http://127.0.0.1:9880")
# Reference voice wav (determines Jarvis's voice) + its corresponding text transcript
GPTSOVITS_REF = os.environ.get(
    "GPTSOVITS_REF", os.path.join(_ROOT_DIR, "jarvis_ref.wav"))
GPTSOVITS_PROMPT = os.environ.get(
    "GPTSOVITS_PROMPT",
    "Let me tell you something interesting that happened today.")
GPTSOVITS_TEXT_LANG = os.environ.get("GPTSOVITS_TEXT_LANG", "en")
GPTSOVITS_PROMPT_LANG = os.environ.get("GPTSOVITS_PROMPT_LANG", "en")

# System say voice name (run "say -v '?'" on macOS to see all).
# Default is Zira/David on Windows, Daniel on macOS.
# Set JARVIS_VOICE to customize. On Windows, users can install an Indian-English or Hindi voice pack 
# (e.g. Microsoft Heera) via Settings -> Time & Language -> Speech.
TTS_VOICE = os.environ.get("JARVIS_VOICE", "Daniel")
TTS_RATE = int(os.environ.get("JARVIS_RATE", "190"))   # Speech rate, words per minute

# Wake words and common phonetic misspellings for fuzzy matching
WAKE_WORDS = [
    "jarvis", "Jarvis", "JARVIS", "jarvees", "zarvis", "alpha", "Alpha", "ALPHA",
]

# ---- WhatsApp API Credentials (Optional, falls back to UI automation if missing) ----
WHATSAPP_TOKEN = (os.environ.get("WHATSAPP_TOKEN") or _read_first_line("whatsapp_token.txt")).strip()
WHATSAPP_PHONE_ID = (os.environ.get("WHATSAPP_PHONE_ID") or _read_first_line("whatsapp_phone_id.txt")).strip()

# Active timeout duration (seconds); returns to idle if silent beyond this limit
ACTIVE_TIMEOUT = 25

# ---- Anti-false Wake (noise / television voice filtering) -------------------------------------------
# During standby, only speech segments matching these confidence thresholds are checked for wake words,
# filtering out hallucinations caused by background noise.
WAKE_MAX_NO_SPEECH = 0.5     # No-speech probability above this value is discarded as noise
WAKE_MIN_LOGPROB = -1.0      # Log probability below this value is discarded as noise
WAKE_MIN_LEN = 3            # ASR result too short (<3 characters) is discarded as false trigger
WAKE_SIM = 0.8             # Wake word similarity threshold (0.0 to 1.0); higher is stricter; lower to 0.72 if unresponsive

# ---- Audio Parameters ----------------------------------------------------------

SAMPLE_RATE = 16000               # Whisper requires 16000Hz
FRAME_MS = 30                     # Frame duration in milliseconds
SILENCE_TAIL = 0.5                # Trailing silence duration to trigger end-of-speech (seconds); lower to 0.5 for speed, but too low triggers on normal speech pauses.
MIN_SPEECH = 0.3                  # Audio shorter than 0.3s is ignored as noise
MAX_SEGMENT = 15                  # Maximum recording segment duration (seconds)

# ---- Credentials --------------------------------------------------------------


def load_api_key() -> str | None:
    """LLM Backend / Gateway API Key.
    Priority: Env var JARVIS_API_KEY > ANTHROPIC_API_KEY > api_key.txt > ~/.jarvis_key.
    When using an API gateway, paste the gateway key into api_key.txt."""
    for var in ("JARVIS_API_KEY", "ANTHROPIC_API_KEY"):
        key = os.environ.get(var)
        if key and key.strip():
            return key.strip()
    for path in (_ROOT / "api_key.txt", Path.home() / ".jarvis_key"):
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    return None
