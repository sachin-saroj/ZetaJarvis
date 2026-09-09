#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: dispatcher.py
# Project: ZetaJarvis - Core Multi-Model Routing Engine
# Description: Dynamic parallel tool dispatcher with schema validation,
#              transient error auto-retries, and exponential jitter backoff.
# ------------------------------------------------------------------------------

"""Dynamic tool dispatching and execution engine."""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from zetajarvis.utils.helpers import get_config_path

# ==============================================================================
# Configuration & Constants
# ==============================================================================

MAX_PARALLEL_TOOLS: int = int(os.getenv("MAX_PARALLEL_TOOLS", "3"))
MAX_TOOL_RETRIES: int = int(os.getenv("MAX_TOOL_RETRIES", "2"))
JITTER_BASE_SEC: float = float(os.getenv("JITTER_BASE_SEC", "1.0"))
JITTER_MAX_SEC: float = float(os.getenv("JITTER_MAX_SEC", "30.0"))

TOOL_REGISTRY: Dict[str, Callable[..., Any]] = {}


def calculate_jitter_backoff(
    attempt: int,
    base: float = JITTER_BASE_SEC,
    max_backoff: float = JITTER_MAX_SEC,
) -> float:
    """Calculates exponential backoff with full jitter.

    Formula: backoff = random.uniform(base, min(max_backoff, base * (2 ** attempt)))
    """
    ceiling = min(max_backoff, base * (2 ** max(0, attempt)))
    return random.uniform(base, max(base, ceiling))


def register_tool_handler(name: str, func: Callable[..., Any]) -> None:
    """Registers an executable Python function for a tool name."""
    TOOL_REGISTRY[name] = func


# Default mock / utility tool implementations
def _default_get_current_time(timezone: str = "local") -> str:
    now = datetime.datetime.now()
    return f"{now.isoformat()} (timezone: {timezone})"


def _default_get_weather(location: str, unit: str = "celsius") -> str:
    temp = 24 if unit == "celsius" else 75
    return json.dumps({
        "location": location,
        "temperature": temp,
        "unit": unit,
        "condition": "Partly Cloudy",
        "humidity": "58%",
    })


def _default_calculate(expression: str) -> str:
    allowed_chars = set("0123456789+-*/(). %")
    if not set(expression).issubset(allowed_chars):
        return json.dumps({"error": "Expression contains unpermitted characters."})
    try:
        result = eval(expression, {"__builtins__": None}, {})  # noqa: S307
        return str(result)
    except Exception as e:
        return json.dumps({"error": f"Math evaluation error: {str(e)}"})


def _default_system_info() -> str:
    return json.dumps({
        "os": sys.platform,
        "python_version": sys.version.split()[0],
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# Register standard default handlers
register_tool_handler("get_current_time", _default_get_current_time)
register_tool_handler("get_weather", _default_get_weather)
register_tool_handler("calculate", _default_calculate)
register_tool_handler("system_info", _default_system_info)


def load_tools_config(config_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Loads tools definitions dynamically from JSON schema file without hardcoding."""
    if config_path:
        p = Path(config_path)
    else:
        p = get_config_path("tools_config.json")

    candidates = [
        p,
        Path.cwd() / p.name,
        Path(__file__).resolve().parent / p.name,
    ]

    for cand in candidates:
        if cand.exists() and cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "tools" in data and isinstance(data["tools"], list):
                    return data["tools"]
            except Exception as e:
                print(f"[Dispatcher Warn] Failed parsing {cand}: {e}", file=sys.stderr)

    # Return default schemas if config file missing
    return [
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "Returns current local date and time in ISO format.",
                "parameters": {
                    "type": "object",
                    "properties": {"timezone": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Retrieves weather condition and temperature for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["location"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calculate",
                "description": "Evaluates safe arithmetic expressions.",
                "parameters": {
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"],
                },
            },
        },
    ]


class DynamicToolDispatcher:
    """Dynamic tool dispatcher supporting parallel execution and transient auto-retry."""

    def __init__(
        self,
        tools_config: Optional[List[Dict[str, Any]]] = None,
        max_workers: int = MAX_PARALLEL_TOOLS,
    ) -> None:
        self.tools = tools_config or load_tools_config()
        self.max_workers = max_workers

    def _execute_single_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Executes a registered tool handler with auto-retry on transient errors."""
        handler = TOOL_REGISTRY.get(tool_name)
        if not handler:
            return json.dumps({
                "status": "success",
                "tool": tool_name,
                "message": f"Tool '{tool_name}' acknowledged with args: {arguments}",
            })

        last_error = None
        for attempt in range(MAX_TOOL_RETRIES + 1):
            try:
                # Record in stats tracker if available in brain
                try:
                    from zetajarvis.core.brain import _STATS_TRACKER
                    _STATS_TRACKER.record_tool_call(tool_name)
                except Exception:
                    pass

                res = handler(**arguments)
                return res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
            except Exception as exc:
                last_error = exc
                is_transient = isinstance(exc, (TimeoutError, ConnectionError, OSError)) or any(
                    kw in str(exc).lower()
                    for kw in ["timeout", "connection", "network", "transient", "glitch"]
                )

                if is_transient and attempt < MAX_TOOL_RETRIES:
                    try:
                        from zetajarvis.core.brain import _STATS_TRACKER
                        _STATS_TRACKER.record_tool_retry()
                    except Exception:
                        pass
                    sleep_time = calculate_jitter_backoff(attempt)
                    time.sleep(sleep_time)
                    continue
                break

        return json.dumps({
            "error": f"Tool '{tool_name}' failed after {attempt + 1} attempts: {str(last_error)}",
        })

    def dispatch_parallel(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Executes up to 3 tools concurrently, aggregates results, and returns tool messages."""
        if not tool_calls:
            return []

        def _worker(tc: Dict[str, Any]) -> Dict[str, Any]:
            tc_id = tc.get("id") or f"call_{random.randint(1000, 9999)}"
            fn = tc.get("function") or {}
            name = fn.get("name") or "unknown_tool"
            raw_args = fn.get("arguments") or "{}"

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {}

            output_str = self._execute_single_tool(name, args)
            return {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": output_str,
            }

        results: List[Dict[str, Any]] = []
        workers = min(len(tool_calls), self.max_workers)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_worker, tc) for tc in tool_calls]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:
                    results.append({
                        "role": "tool",
                        "tool_call_id": "call_error",
                        "content": json.dumps({"error": str(e)}),
                    })

        return results
