#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/audio.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: Microphone Audio Capture and VAD processing.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""ZetaJarvis Microphone Audio Capture and VAD processing."""

from __future__ import annotations

import queue
from collections.abc import Iterator

import numpy as np
import sounddevice as sd

from . import config

_FRAME = int(config.SAMPLE_RATE * config.FRAME_MS / 1000)   # Number of samples per frame


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)) + 1e-9)


class Microphone:
    """Continuously captures audio at 16k/mono/int16 and yields normalized float32 speech segments."""

    def __init__(self) -> None:
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=_FRAME,
            callback=self._on_audio,
        )
        self.threshold = 500.0   # Will be updated in calibrate()
        self.on_speech_start = None   # Callback triggered when speech start is detected (tells pet HUD to set state to listening)

    def _on_audio(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        self._q.put(indata[:, 0].copy())

    def __enter__(self) -> "Microphone":
        self._stream.start()
        self.calibrate()
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        self._stream.stop()
        self._stream.close()

    def flush(self) -> None:
        """Flushes the buffer queue. Called after TTS finishes speaking to prevent loopback self-triggering."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def calibrate(self, seconds: float = 1.0) -> None:
        """Measures ambient noise and sets speaking threshold to a multiple of the baseline level."""
        levels = []
        need = int(seconds * 1000 / config.FRAME_MS)
        while len(levels) < need:
            levels.append(_rms(self._q.get()))
        floor = float(np.median(levels))
        self.threshold = max(floor * 3.5, 400.0)

    def _frames(self) -> Iterator[np.ndarray]:
        while True:
            yield self._q.get()

    def segments(self) -> Iterator[np.ndarray]:
        """Yields audio segments blocking-style (float32, [-1,1])."""
        tail = int(config.SILENCE_TAIL * 1000 / config.FRAME_MS)
        max_frames = int(config.MAX_SEGMENT * 1000 / config.FRAME_MS)
        min_frames = int(config.MIN_SPEECH * 1000 / config.FRAME_MS)

        buf: list[np.ndarray] = []
        silence = 0
        speaking = False

        for frame in self._frames():
            loud = _rms(frame) > self.threshold
            if speaking:
                buf.append(frame)
                silence = 0 if loud else silence + 1
                if silence >= tail or len(buf) >= max_frames:
                    if len(buf) >= min_frames:
                        audio = np.concatenate(buf).astype(np.float32) / 32768.0
                        yield audio
                    buf, silence, speaking = [], 0, False
            elif loud:
                speaking = True
                buf = [frame]
                silence = 0
                if self.on_speech_start:
                    self.on_speech_start()
