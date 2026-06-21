#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: test_fixes.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: Test script to verify Windows fixes for ZetaJarvis.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""Test script to verify all Windows fixes for ZetaJarvis"""

import sys
import os

# Add jarvis to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_tts():
    """Test Text-to-Speech with pyttsx3"""
    print("\n🔊 Testing TTS (pyttsx3)...")
    try:
        from jarvis import tts
        print("✓ TTS module imported successfully")
        
        # Test speak function
        test_text = "Hello, I am ZetaJarvis. Testing Windows TTS with pyttsx three."
        print(f"  Speaking: '{test_text}'")
        tts.speak(test_text, blocking=True)
        print("✓ TTS working! You should have heard the voice.")
        return True
    except Exception as e:
        print(f"✗ TTS test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_asr_language():
    """Test ASR language configuration"""
    print("\n🎤 Testing ASR Language Configuration...")
    try:
        from jarvis import config
        print(f"  ASR_LANGUAGE: {config.ASR_LANGUAGE}")
        print(f"  ASR_INITIAL_PROMPT: {config.ASR_INITIAL_PROMPT}")
        
        if config.ASR_LANGUAGE is None:
            print("✓ ASR configured for auto-language detection")
            return True
        else:
            print(f"⚠ ASR language is set to: {config.ASR_LANGUAGE}")
            print("  Tip: Set JARVIS_LANGUAGE=auto in .env for multi-language")
            return True
    except Exception as e:
        print(f"✗ ASR config test failed: {e}")
        return False

def test_wake_words():
    """Test wake word configuration"""
    print("\n🔔 Testing Wake Words...")
    try:
        from jarvis import config
        print(f"  Wake words: {config.WAKE_WORDS}")
        
        english_words = [w for w in config.WAKE_WORDS if w.lower() in ['jarvis', 'alpha']]
        if english_words:
            print(f"✓ English wake words configured: {english_words}")
            return True
        else:
            print("⚠ No English wake words found in configuration")
            return False
    except Exception as e:
        print(f"✗ Wake word test failed: {e}")
        return False

def test_system_prompt():
    """Test system prompt language"""
    print("\n🧠 Testing System Prompt...")
    try:
        from jarvis import brain
        prompt = brain.SYSTEM_PROMPT
        
        if "SAME LANGUAGE" in prompt or "ENGLISH ONLY" in prompt or "respond in ENGLISH" in prompt:
            print("✓ System prompt configured correctly for response language")
            print(f"  Preview: {prompt[:200]}...")
            return True
        else:
            print("⚠ System prompt may not be configured correctly")
            print(f"  Preview: {prompt[:200]}...")
            return False
    except Exception as e:
        print(f"✗ System prompt test failed: {e}")
        return False

def test_env_config():
    """Test .env configuration"""
    print("\n⚙️  Testing .env Configuration...")
    try:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            print(f"✓ .env file exists at: {env_path}")
            with open(env_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if 'JARVIS_LANGUAGE=auto' in content:
                    print("✓ JARVIS_LANGUAGE=auto configured")
                if 'JARVIS_TTS=say' in content:
                    print("✓ JARVIS_TTS=say configured (will use pyttsx3)")
            return True
        else:
            print(f"⚠ .env file not found at: {env_path}")
            return False
    except Exception as e:
        print(f"✗ .env test failed: {e}")
        return False

def main():
    print("=" * 70)
    print("ZetaJarvis Windows Fix Verification")
    print("=" * 70)
    
    results = {
        "Environment Config": test_env_config(),
        "ASR Language": test_asr_language(),
        "Wake Words": test_wake_words(),
        "System Prompt": test_system_prompt(),
        "TTS (pyttsx3)": test_tts(),
    }
    
    print("\n" + "=" * 70)
    print("Test Results Summary:")
    print("=" * 70)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status:10} {test_name}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n🎉 All tests passed! ZetaJarvis is ready for Windows.")
        print("\nTo run ZetaJarvis:")
        print("  .venv\\Scripts\\python.exe -m jarvis --no-pet")
        print("\nOr with GUI:")
        print("  .venv\\Scripts\\python.exe -m jarvis")
    else:
        print("\n⚠ Some tests failed. Please review the output above.")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
