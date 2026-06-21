#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/mcp_bridge.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: MCP Bridge integrating local MCP servers into ZetaJarvis.
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""ZetaJarvis MCP Bridge module."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
from contextlib import AsyncExitStack
from pathlib import Path

from . import config

_CONFIG = Path(__file__).resolve().parent.parent / "mcp.json"


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:60]


def _resolve_command(cmd: str) -> str:
    """On Windows, command names like npx/npm/uvx are wrappers (.cmd/.exe). Subprocess fails
    to start them by name alone, so this function resolves them to absolute paths (returns original if not found)."""
    if not config.IS_WINDOWS or os.path.splitext(cmd)[1]:
        return cmd
    for cand in (cmd, cmd + ".cmd", cmd + ".exe", cmd + ".bat"):
        found = shutil.which(cand)
        if found:
            return found
    return cmd


def load_config() -> dict:
    if not _CONFIG.exists():
        return {}
    try:
        return json.loads(_CONFIG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


class McpBridge:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stack: AsyncExitStack | None = None
        self._schemas: list[dict] = []
        self._dispatch: dict[str, tuple] = {}   # full_name -> (session, tool_name)
        self._ready = threading.Event()
        self.names: list[str] = []              # Names of successfully connected servers

    # ---- Startup ----------------------------------------------------
    def start(self, config: dict, log=print, timeout: float = 60) -> None:
        if not config:
            return
        try:
            import mcp  # noqa: F401
        except ImportError:
            log("⚠️  mcp library not installed, skipping MCP (run: pip install mcp to enable)")
            return
        threading.Thread(target=self._run, args=(config, log),
                         daemon=True).start()
        self._ready.wait(timeout=timeout)

    def _run(self, config: dict, log) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._setup(config, log))
        finally:
            self._ready.set()
        self._loop.run_forever()

    async def _setup(self, config: dict, log) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._stack = AsyncExitStack()
        for name, conf in config.items():
            if not conf.get("enabled", True):
                continue
            try:
                args = [os.path.expanduser(a) for a in conf.get("args", [])]
                env = {**os.environ, **conf.get("env", {})}
                # Avoid broken ~/.npm permissions: use project-local cache for npx
                if "npx" in conf["command"] and "npm_config_cache" not in env:
                    cache = _CONFIG.parent / ".npm-cache"
                    cache.mkdir(exist_ok=True)
                    env["npm_config_cache"] = str(cache)
                params = StdioServerParameters(
                    command=_resolve_command(conf["command"]), args=args, env=env,
                )
                read, write = await self._stack.enter_async_context(
                    stdio_client(params))
                session = await self._stack.enter_async_context(
                    ClientSession(read, write))
                await session.initialize()
                resp = await session.list_tools()
                for t in resp.tools:
                    full = f"mcp__{_sanitize(name)}__{_sanitize(t.name)}"[:64]
                    self._schemas.append({
                        "name": full,
                        "description": (t.description or t.name)[:1000],
                        "input_schema": t.inputSchema or {
                            "type": "object", "properties": {}},
                    })
                    self._dispatch[full] = (session, t.name)
                self.names.append(name)
                log(f"  ✓ MCP \"{name}\" connected ({len(resp.tools)} tools)")
            except Exception as e:  # noqa: BLE001
                log(f"  ⚠️  MCP \"{name}\" failed to start: {e}")

    # ---- Public Interface ----------------------------------------------------
    def tool_schemas(self) -> list[dict]:
        return self._schemas

    def has(self, name: str) -> bool:
        return name in self._dispatch

    def call(self, full_name: str, args: dict) -> str:
        if self._loop is None or full_name not in self._dispatch:
            return f"Unknown MCP tool: {full_name}"
        session, tool_name = self._dispatch[full_name]
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._call(session, tool_name, args or {}), self._loop)
            return fut.result(timeout=90)
        except Exception as e:  # noqa: BLE001
            return f"Error calling MCP tool: {e}"

    async def _call(self, session, tool_name: str, args: dict) -> str:
        res = await session.call_tool(tool_name, args)
        parts = []
        for c in getattr(res, "content", []) or []:
            text = getattr(c, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts) or "(Executed, no text output)"
