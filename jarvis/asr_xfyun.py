#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/asr_xfyun.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: iFlytek Speech Transcription Cloud ASR Backend.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""iFlytek Cloud ASR Backend module."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time

import numpy as np

from . import config

_HOST = "iat-api.xfyun.cn"
_PATH = "/v2/iat"
_URL = f"wss://{_HOST}{_PATH}"


def _auth_url() -> str:
    """Generates the authenticated wss URL."""
    date = format_date_time(time.time())          # RFC1123 GMT time format
    sign_origin = f"host: {_HOST}\ndate: {date}\nGET {_PATH} HTTP/1.1"
    sign = base64.b64encode(
        hmac.new(config.XFYUN_API_SECRET.encode("utf-8"),
                 sign_origin.encode("utf-8"), hashlib.sha256).digest()
    ).decode()
    auth_origin = (f'api_key="{config.XFYUN_API_KEY}", '
                   f'algorithm="hmac-sha256", '
                   f'headers="host date request-line", signature="{sign}"')
    authorization = base64.b64encode(auth_origin.encode("utf-8")).decode()
    return _URL + "?" + urlencode(
        {"authorization": authorization, "date": date, "host": _HOST})


def transcribe(audio: np.ndarray) -> str:
    """Uploads audio and returns transcribed text (can be empty). Raises exception on failure."""
    import websocket  # Lazy import: does not affect local ASR backend if not installed

    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    frame = 1280                                   # 40ms frame @ 16k/16bit/mono
    chunks = [pcm[i:i + frame] for i in range(0, len(pcm), frame)] or [b""]

    ws = websocket.create_connection(_auth_url(), timeout=10)
    try:
        for i, ch in enumerate(chunks):
            status = 0 if i == 0 else 1            # 0=first frame, 1=middle frame
            payload: dict = {
                "data": {
                    "status": status,
                    "format": "audio/L16;rate=16000",
                    "encoding": "raw",
                    "audio": base64.b64encode(ch).decode(),
                }
            }
            if i == 0:
                payload["common"] = {"app_id": config.XFYUN_APP_ID}
                payload["business"] = {
                    "language": "zh_cn", "domain": "iat",
                    "accent": "mandarin", "vad_eos": 3000,
                }
            ws.send(json.dumps(payload))
            time.sleep(0.005)                      # Audio segment is fully pre-recorded; send chunks rapidly with minimal sleep to prevent rate limiting
        # End frame
        ws.send(json.dumps({"data": {
            "status": 2, "format": "audio/L16;rate=16000",
            "encoding": "raw", "audio": ""}}))

        text = ""
        while True:
            msg = ws.recv()
            if not msg:
                break
            obj = json.loads(msg)
            if obj.get("code") != 0:
                raise RuntimeError(
                    f"iFlytek returned error code {obj.get('code')}: {obj.get('message')}")
            data = obj.get("data") or {}
            for w in (data.get("result") or {}).get("ws", []):
                for c in w.get("cw", []):
                    text += c.get("w", "")
            if data.get("status") == 2:            # Last frame result
                break
        return text.strip()
    finally:
        ws.close()
