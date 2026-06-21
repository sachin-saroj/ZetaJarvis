#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: test_llm.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: API Endpoint Connectivity Self-Test.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""API Endpoint Connectivity Self-Test for ZetaJarvis.
Tests basic conversation and tool calling. If both pass, ZetaJarvis's brain is connected successfully.
"""
import sys
sys.path.insert(0, ".")
from jarvis import config, brain  # noqa: E402

print(f"Model: {config.MODEL}")
print(f"URL  : {config.LLM_BASE_URL}  ->  {config.llm_endpoint()}")
key = config.load_api_key()
print(f"Key  : {'Read successfully (' + key[:6] + '...)' if key else '✗ Not read'}")
if not config.LLM_BASE_URL or not key:
    print("\nPlease fill in base_url.txt and api_key.txt first.")
    sys.exit(1)

b = brain.Brain(api_key=key, mcp=None)

print("\n① Basic Conversation Test...")
try:
    print("   ZetaJarvis:", b.ask("Introduce yourself in one sentence."))
except Exception as e:  # noqa: BLE001
    print("   ✗ Failed:", e)
    sys.exit(1)

print("\n② Tool Calling Test (asking for the time, which should trigger the get_time tool)...")
b.reset()
try:
    print("   ZetaJarvis:", b.ask("What time is it now?"))
    used = any(m.get("role") == "tool" for m in b._messages)
    print("   Was tool called:", "✅ Yes" if used else "⚠ No (model didn't call tool, but conversation succeeded)")
except Exception as e:  # noqa: BLE001
    print("   ✗ Failed:", e)
    sys.exit(1)

print("\n✅ API Endpoint is connected. You can now start ZetaJarvis with run.bat or run.sh.")

