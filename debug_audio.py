#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: debug_audio.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: Debug utility for audio input and ASR detection.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""Debug audio input and ASR detection for ZetaJarvis"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jarvis import config, asr, audio
import numpy as np

print("=" * 70)
print("🎤 Audio Debug Tool - ZetaJarvis")
print("=" * 70)

print("\n📊 Current Configuration:")
print(f"  ASR_LANGUAGE: {config.ASR_LANGUAGE}")
print(f"  ASR_INITIAL_PROMPT: {config.ASR_INITIAL_PROMPT}")
print(f"  WHISPER_MODEL: {config.WHISPER_MODEL}")
print(f"  ASR_BEAM: {config.ASR_BEAM}")
print(f"  ASR_VAD: {config.ASR_VAD}")
print(f"  WAKE_WORDS: {config.WAKE_WORDS[:5]}...")
print(f"  WAKE_MAX_NO_SPEECH: {config.WAKE_MAX_NO_SPEECH}")
print(f"  WAKE_MIN_LOGPROB: {config.WAKE_MIN_LOGPROB}")
print(f"  WAKE_MIN_LEN: {config.WAKE_MIN_LEN}")

print("\n🔊 Microphone Test:")
print("  Listening for 3 seconds... Say something!")

# Initialize ASR
print("\n⏳ Loading Whisper model...")
asr.load()
print("✓ Model loaded")

# Record test audio
from jarvis.audio import Microphone

try:
    with Microphone() as mic:
        print(f"\n✓ Microphone ready (threshold: {mic.threshold:.0f})")
        print("\n🎙️ Recording for 3 seconds... SPEAK NOW!")
        
        # Wait for speech
        import time
        start = time.time()
        audio_data = []
        
        while time.time() - start < 3:
            frame = mic.read()
            if frame is not None:
                audio_data.append(frame)
        
        if audio_data:
            audio_np = np.concatenate(audio_data)
            print(f"✓ Recorded {len(audio_np)/config.SAMPLE_RATE:.1f} seconds")
            
            # Transcribe
            print("\n⏳ Transcribing...")
            result = asr.transcribe(audio_np, cloud=False)
            
            print("\n📝 Results:")
            print(f"  Text: '{result.text}'")
            print(f"  No Speech Prob: {result.no_speech:.3f} (threshold: {config.WAKE_MAX_NO_SPEECH})")
            print(f"  Avg Log Prob: {result.avg_logprob:.3f} (threshold: {config.WAKE_MIN_LOGPROB})")
            print(f"  Length: {len(result.text)} chars (min: {config.WAKE_MIN_LEN})")
            
            # Check wake word detection
            print("\n🔔 Wake Word Detection:")
            text_lower = result.text.lower()
            wake_detected = any(w.lower() in text_lower for w in config.WAKE_WORDS)
            print(f"  Detected: {wake_detected}")
            if wake_detected:
                print("  ✓ Wake word found!")
            else:
                print("  ✗ No wake word detected")
            
            # Check if would pass filters
            print("\n🚦 Filter Check:")
            passes = True
            if result.no_speech > config.WAKE_MAX_NO_SPEECH:
                print(f"  ✗ FAILED: Too much noise (no_speech={result.no_speech:.3f})")
                passes = False
            else:
                print(f"  ✓ PASS: Noise level OK")
            
            if result.avg_logprob < config.WAKE_MIN_LOGPROB:
                print(f"  ✗ FAILED: Low confidence (logprob={result.avg_logprob:.3f})")
                passes = False
            else:
                print(f"  ✓ PASS: Confidence OK")
            
            if len(result.text) < config.WAKE_MIN_LEN:
                print(f"  ✗ FAILED: Too short ({len(result.text)} chars)")
                passes = False
            else:
                print(f"  ✓ PASS: Length OK")
            
            if passes and wake_detected:
                print("\n✅ WOULD WAKE ZETAJARVIS")
            elif passes:
                print("\n⚠️  Would be heard but no wake word")
            else:
                print("\n❌ Would be FILTERED OUT (good for noise rejection)")
        else:
            print("✗ No audio recorded!")
            
except KeyboardInterrupt:
    print("\n\n👋 Interrupted by user")
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("💡 Tips:")
print("  - Close background videos/audio players")
print("  - Speak clearly and directly into microphone")
print("  - Try saying: 'Jarvis' or 'Alpha'")
print("  - If too sensitive, increase WAKE_MAX_NO_SPEECH in config.py")
print("=" * 70)
