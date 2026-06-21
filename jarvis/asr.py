#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/asr.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: Speech Recognition (ASR) local Whisper backend.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""ZetaJarvis Speech Recognition (ASR) module."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
from faster_whisper import WhisperModel

from . import config

_model: WhisperModel | None = None
_xfyun_warned = False          # iFlytek fallback warning only shows once to avoid spamming


class ASRResult(NamedTuple):
    text: str
    no_speech: float       # Larger values indicate noise / silence
    avg_logprob: float     # Larger values indicate higher confidence


def load() -> None:
    """Loads the local model (downloads automatically to ~/.cache on first run).

    Loaded even if using the iFlytek backend, as a fallback when the cloud is unreachable.
    """
    global _model
    if _model is None:
        _model = WhisperModel(
            config.WHISPER_MODEL,
            device="cpu",
            compute_type=config.WHISPER_COMPUTE,
        )


def transcribe(audio: np.ndarray, cloud: bool = False) -> ASRResult:
    """Transcribes an audio segment and returns text with confidence metrics.

    If cloud=True and backend is xfyun, uses iFlytek cloud (more accurate but uploads audio and incurs API cost);
    otherwise, uses local ASR.
    Quota saving strategy: Standby wake word listening uses local (cloud=False), while commands after wake use iFlytek cloud (cloud=True).
    """
    if cloud and config.ASR_BACKEND == "xfyun":
        global _xfyun_warned
        try:
            from . import asr_xfyun
            text = asr_xfyun.transcribe(audio)
            # Cloud results are assumed credible (low no_speech, high logprob to pass wake word filtering);
            # An empty string indicates cloud VAD determined no speech was present; processed as "no speech detected", no fallback to local.
            return ASRResult(text, 0.0, 0.0)
        except Exception as e:  # noqa: BLE001 Cloud ASR exception -> fallback to local
            if not _xfyun_warned:
                print(f"  ⚠️  iFlytek recognition failed, falling back to local Whisper: {e}")
                _xfyun_warned = True
    return _transcribe_local(audio)


def _transcribe_local(audio: np.ndarray) -> ASRResult:
    """Local faster-whisper recognition."""
    if _model is None:
        load()
    assert _model is not None
    segments, _ = _model.transcribe(
        audio,
        language=config.ASR_LANGUAGE,
        beam_size=config.ASR_BEAM,             # Accuracy/speed toggle (config.ASR_BEAM)
        vad_filter=config.ASR_VAD,             # VAD filtering to reduce background noise hallucinations
        initial_prompt=config.ASR_INITIAL_PROMPT,  # Language bias / initial prompt with common words or names
        condition_on_previous_text=False,      # Disable conditioning on previous text to avoid extra overhead and repetitive drift
    )
    segs = list(segments)
    text = "".join(s.text for s in segs).strip()
    if not segs:
        return ASRResult("", 1.0, -10.0)
    no_speech = sum(s.no_speech_prob for s in segs) / len(segs)
    avg_logprob = sum(s.avg_logprob for s in segs) / len(segs)
    return ASRResult(text, no_speech, avg_logprob)
