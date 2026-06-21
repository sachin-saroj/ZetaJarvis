#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/memory.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: Long-term Memory module for storing user facts.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""ZetaJarvis Long-term Memory module."""

from __future__ import annotations

import json
import time
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "memory.json"


def load() -> list[dict]:
    if _PATH.exists():
        try:
            return json.loads(_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save(items: list[dict]) -> None:
    _PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def add(fact: str) -> str:
    fact = (fact or "").strip()
    if not fact:
        return "(Nothing to remember)"
    items = load()
    if any(it.get("fact") == fact for it in items):
        return "I have already recorded this fact."
    items.append({"fact": fact, "at": time.strftime("%Y-%m-%d")})
    _save(items)
    return f"Understood. I have remembered: {fact}"


def forget(keyword: str) -> str:
    keyword = (keyword or "").strip()
    items = load()
    kept = [it for it in items if keyword not in it.get("fact", "")]
    removed = len(items) - len(kept)
    if removed:
        _save(kept)
        return f"Forgot {removed} related memory entries."
    return "No matching memory entries found."


def as_prompt() -> str:
    """Formats all memories to be injected into the system prompt."""
    items = load()
    if not items:
        return ""
    lines = "\n".join(f"- {it.get('fact', '')}" for it in items)
    return ("\n\n# Things you already remembered about the user (use them naturally, do not explicitly recite them):\n" + lines)
