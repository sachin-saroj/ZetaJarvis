#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: voice_clone/serve.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: ZetaJarvis voice cloning service (independent process).
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""ZetaJarvis voice cloning service (independent process).

Uses XTTS-v2 for zero-shot cloning: synthesizes text into speech using the voice characteristics of a reference audio.
The model is loaded only once on startup (about 1.8GB, downloaded automatically on the first run), and handles rapid synthesis for subsequent requests.

Endpoints (local HTTP):
  GET /health            -> ok
  POST /tts  body=text   -> {"path": "/tmp/xxx.wav"}   synthesized wav path

Environment Variables:
  JARVIS_VOICE_REF   Reference audio path (determines the voice tone)
  JARVIS_VOICE_PORT  Port (default: 5111)
  JARVIS_VOICE_LANG  Language (default: en)
  JARVIS_VOICE_DEVICE cpu/mps (default: cpu, most stable)
"""

from __future__ import annotations

import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("COQUI_TOS_AGREED", "1")   # Skip XTTS license interactive prompt

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.environ.get("JARVIS_VOICE_REF", os.path.join(_ROOT_DIR, "jarvis_ref.wav"))
PORT = int(os.environ.get("JARVIS_VOICE_PORT", "5111"))
LANG = os.environ.get("JARVIS_VOICE_LANG", "en")
DEVICE = os.environ.get("JARVIS_VOICE_DEVICE", "cpu")

_tts = None


def _load():
    global _tts
    if _tts is not None:
        return
    print("⏳ Loading XTTS-v2 cloning model (will download about 1.8GB on first run)...", flush=True)
    from TTS.api import TTS
    _tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(DEVICE)
    print(f"✓ Cloning model ready (device={DEVICE}, voice reference={REF})", flush=True)


def _split(text: str, limit: int = 200):
    """XTTS single text should not be too long, split into sentences roughly by punctuation."""
    import re
    parts, cur = [], ""
    for seg in re.split(r"(?<=[。！？.!?；;\n])", text):
        if len(cur) + len(seg) > limit and cur:
            parts.append(cur)
            cur = seg
        else:
            cur += seg
    if cur.strip():
        parts.append(cur)
    return parts or [text]


def synth(text: str) -> str:
    _load()
    chunks = _split(text)
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    if len(chunks) == 1:
        _tts.tts_to_file(text=chunks[0], speaker_wav=REF, language=LANG,
                         file_path=out)
        return out
    # Multiple sentences: synthesize sentence by sentence and concatenate
    import wave
    paths = []
    for c in chunks:
        p = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        _tts.tts_to_file(text=c, speaker_wav=REF, language=LANG, file_path=p)
        paths.append(p)
    with wave.open(out, "wb") as w:
        for i, p in enumerate(paths):
            with wave.open(p, "rb") as r:
                if i == 0:
                    w.setparams(r.getparams())
                w.writeframes(r.readframes(r.getnframes()))
            os.remove(p)
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # Mute access logs
        pass

    def do_GET(self):
        if self.path == "/health":
            self._json({"status": "ok"})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/tts":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        text = self.rfile.read(n).decode("utf-8").strip()
        if not text:
            self._json({"error": "empty"})
            return
        try:
            path = synth(text)
            self._json({"path": path})
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)})

    def _json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    _load()   # Load on startup to avoid delay on the first sentence
    print(f"🔊 Cloning voice service listening at http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

