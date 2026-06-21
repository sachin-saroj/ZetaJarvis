#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: test_tts_simple.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: Simple TTS connectivity test.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""Simple TTS test for ZetaJarvis"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("🔊 Testing Windows TTS (pyttsx3)...")
print("You should hear: 'Hello, I am ZetaJarvis. Testing voice output.'")
print()

try:
    import pyttsx3
    
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    
    print(f"Available voices: {len(voices)}")
    for i, v in enumerate(voices):
        print(f"  {i}. {v.name} [{v.languages}]")
    
    # Use first English voice
    for v in voices:
        if 'english' in v.name.lower() or 'zira' in v.name.lower():
            engine.setProperty('voice', v.id)
            print(f"\nUsing voice: {v.name}")
            break
    
    engine.setProperty('rate', 180)
    engine.setProperty('volume', 1.0)
    
    text = "Hello, I am ZetaJarvis. Testing voice output."
    print(f"\nSpeaking: '{text}'")
    
    engine.say(text)
    engine.runAndWait()
    engine.stop()
    
    print("\n✅ TTS test complete!")
    print("If you heard the voice, TTS is working correctly.")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    print("\nTry: pip install pyttsx3")
