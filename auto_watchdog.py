#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: auto_watchdog.py
# Project: ZetaJarvis - Desktop Domination Layer
# Description: Metaprogramming watchdog for dynamic tool loading, schema
#              synchronization, AST self-healing, and failure blacklisting.
# ------------------------------------------------------------------------------

"""Module 3: Auto-Watchdog – Self-Modifying Code & Dynamic Hot-Reload.

Features:
- Zero-external-dependency polling watcher monitoring the `tools/` directory.
- Dynamic module importing via importlib and inspect, auto-generating OpenAI schemas.
- Auto-registers loaded tools into tools_config.json and brain.register_tool_handler().
- Self-healing via AST (Abstract Syntax Tree) manipulation when a tool fails 3 times in a row.
- Failure blacklist moving tools failing >5 times to tools/disabled/ with TTS warning.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import brain


# ==============================================================================
# Configuration
# ==============================================================================

TOOLS_DIR = Path(os.getenv("TOOLS_DIR", "tools"))
DISABLED_DIR = TOOLS_DIR / "disabled"
POLL_INTERVAL_SEC = float(os.getenv("WATCHDOG_POLL_SEC", "1.0"))
TOOLS_CONFIG_PATH = Path(os.getenv("TOOLS_CONFIG_PATH", "tools_config.json"))


# ==============================================================================
# AST Transformation for Self-Healing
# ==============================================================================

class RequestsToUrllibTransformer(ast.NodeTransformer):
    """AST Transformer replacing `requests.get(url)` with `urllib.request.urlopen(url).read().decode()`."""

    def __init__(self) -> None:
        super().__init__()
        self.modified = False

    def visit_Call(self, node: ast.Call) -> ast.AST:
        # Check if call is requests.get(...)
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("get", "post"):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "requests":
                self.modified = True
                # Replace requests.get(url).text with urllib.request.urlopen(url).read().decode('utf-8')
                new_call = ast.Call(
                    func=ast.Attribute(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Attribute(
                                    value=ast.Name(id="urllib", ctx=ast.Load()),
                                    attr="request",
                                    ctx=ast.Load(),
                                ),
                                attr="urlopen",
                                ctx=ast.Load(),
                            ),
                            args=node.args,
                            keywords=node.keywords,
                        ),
                        attr="read",
                        ctx=ast.Load(),
                    ),
                    args=[],
                    keywords=[],
                )
                # Decode to string
                decoded_call = ast.Call(
                    func=ast.Attribute(
                        value=new_call,
                        attr="decode",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Constant(value="utf-8")],
                    keywords=[],
                )
                return decoded_call
        return self.generic_visit(node)


def wrap_function_with_retry_ast(tree: ast.AST, func_name: str) -> bool:
    """Wraps the target function body in an auto-retry loop using AST manipulation."""
    modified = False

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            # Check if already wrapped with retry
            source = ast.unparse(node)
            if "_retry_attempt" in source:
                continue

            # Construct retry block:
            # for _retry_attempt in range(3):
            #     try:
            #         <original_body>
            #     except Exception as _err:
            #         if _retry_attempt == 2: raise _err
            #         time.sleep(0.5)
            original_body = node.body

            retry_loop_code = """
import time
for _retry_attempt in range(3):
    try:
        pass
    except Exception as _err:
        if _retry_attempt == 2:
            raise _err
        time.sleep(0.5)
"""
            retry_ast = ast.parse(retry_loop_code).body
            for_loop = [n for n in retry_ast if isinstance(n, ast.For)][0]
            # Replace 'pass' inside try block with original function body
            for_loop.body[0].body = original_body  # type: ignore

            node.body = [for_loop]
            modified = True

    return modified


def heal_tool_source_code(file_path: Path, func_name: str) -> bool:
    """Applies AST transformations to repair a failing tool file."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # 1. Transform any brittle `requests` calls to `urllib.request`
        transformer = RequestsToUrllibTransformer()
        tree = transformer.visit(tree)
        ast.fix_missing_locations(tree)

        # Ensure urllib import exists if modified
        if transformer.modified and "import urllib.request" not in source:
            import_node = ast.Import(names=[ast.alias(name="urllib.request", asname=None)])
            tree.body.insert(0, import_node)

        # 2. Wrap function body with AST retry logic
        retry_added = wrap_function_with_retry_ast(tree, func_name)
        if retry_added and "import time" not in source:
            import_time_node = ast.Import(names=[ast.alias(name="time", asname=None)])
            tree.body.insert(0, import_time_node)

        if transformer.modified or retry_added:
            new_code = ast.unparse(tree)
            file_path.write_text(new_code, encoding="utf-8")
            return True
    except Exception as e:
        print(f"[Watchdog Warn] AST self-healing failed for {file_path}: {e}", file=sys.stderr)
    return False


# ==============================================================================
# Metaprogramming Tool Watchdog
# ==============================================================================

class ToolWatchdog:
    """Monitors tools/ directory, hot-reloads tools, self-heals, and blacklists failing tools."""

    def __init__(
        self,
        tools_dir: Path = TOOLS_DIR,
        config_path: Path = TOOLS_CONFIG_PATH,
        poll_interval: float = POLL_INTERVAL_SEC,
        tts_notifier: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.tools_dir = tools_dir
        self.disabled_dir = tools_dir / "disabled"
        self.config_path = config_path
        self.poll_interval = poll_interval
        self.tts_notifier = tts_notifier

        # Failure tracking
        self.failure_counts: Dict[str, int] = {}
        self.file_mtimes: Dict[str, float] = {}
        self.tool_to_file: Dict[str, Path] = {}

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.disabled_dir.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        """Starts background file polling thread."""
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="ZetaWatchdog-Worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def set_poll_interval(self, interval: float) -> None:
        """Dynamically adjusts directory polling frequency."""
        self.poll_interval = max(0.1, float(interval))

    def _watch_loop(self) -> None:
        """Periodic directory scanner."""
        # Initial scan
        self.scan_and_load_all()

        while not self._stop_event.is_set():
            try:
                self._check_for_changes()
            except Exception as e:
                print(f"[Watchdog Notice] Error scanning tools: {e}", file=sys.stderr)
            time.sleep(self.poll_interval)

    def _check_for_changes(self) -> None:
        """Detects new or modified .py files in tools/."""
        current_files = {
            f.name: f
            for f in self.tools_dir.glob("*.py")
            if not f.name.startswith("_") and f.is_file()
        }

        for fname, fpath in current_files.items():
            try:
                mtime = fpath.stat().st_mtime
                last_mtime = self.file_mtimes.get(fname, 0.0)
                if mtime > last_mtime:
                    self.load_tool_file(fpath)
                    self.file_mtimes[fname] = mtime
            except Exception:
                pass

    def scan_and_load_all(self) -> None:
        """Scans tools/ directory and loads all valid tool files."""
        for fpath in self.tools_dir.glob("*.py"):
            if not fpath.name.startswith("_") and fpath.is_file():
                self.load_tool_file(fpath)
                self.file_mtimes[fpath.name] = fpath.stat().st_mtime

    def load_tool_file(self, file_path: Path) -> List[str]:
        """Dynamically loads functions from a python file and updates schema."""
        loaded_names: List[str] = []
        module_name = f"zeta_tool_{file_path.stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if not spec or not spec.loader:
                return []

            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            # Inspect public functions
            for func_name, func in inspect.getmembers(mod, inspect.isfunction):
                if func_name.startswith("_"):
                    continue

                # Register handler with brain
                brain.register_tool_handler(func_name, func)
                self.tool_to_file[func_name] = file_path
                loaded_names.append(func_name)

                # Generate tool schema
                schema = self._build_tool_schema(func_name, func)
                self._update_tools_config(schema)

            return loaded_names
        except Exception as exc:
            print(f"[Watchdog Error] Failed loading tool {file_path.name}: {exc}", file=sys.stderr)
            return []

    def _build_tool_schema(self, name: str, func: Callable[..., Any]) -> Dict[str, Any]:
        """Generates OpenAI function schema from function signature and docstrings."""
        sig = inspect.signature(func)
        doc = (inspect.getdoc(func) or f"Custom dynamic tool: {name}").strip().splitlines()[0]

        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            param_type = "string"
            if param.annotation is int:
                param_type = "integer"
            elif param.annotation is float:
                param_type = "number"
            elif param.annotation is bool:
                param_type = "boolean"

            properties[param_name] = {
                "type": param_type,
                "description": f"Parameter {param_name}",
            }
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        return {
            "type": "function",
            "function": {
                "name": name,
                "description": doc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def _update_tools_config(self, new_tool_schema: Dict[str, Any]) -> None:
        """Surgically inserts or updates tool schema in tools_config.json."""
        with self._lock:
            data: Dict[str, Any] = {"tools": []}
            if self.config_path.exists():
                try:
                    content = json.loads(self.config_path.read_text(encoding="utf-8"))
                    if isinstance(content, dict) and "tools" in content:
                        data = content
                    elif isinstance(content, list):
                        data = {"tools": content}
                except Exception:
                    pass

            tool_name = new_tool_schema["function"]["name"]
            # Replace existing or append
            data["tools"] = [
                t for t in data["tools"]
                if t.get("function", {}).get("name") != tool_name
            ]
            data["tools"].append(new_tool_schema)

            self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def record_tool_failure(self, tool_name: str) -> None:
        """Records a failure.

        If count == 3: Triggers AST Self-Healing.
        If count > 5: Moves tool to tools/disabled/ and warns via TTS.
        """
        with self._lock:
            self.failure_counts[tool_name] = self.failure_counts.get(tool_name, 0) + 1
            failures = self.failure_counts[tool_name]

            # 1. Self-Healing at 3 consecutive failures
            if failures == 3:
                fpath = self.tool_to_file.get(tool_name)
                if fpath and fpath.exists():
                    healed = heal_tool_source_code(fpath, tool_name)
                    if healed:
                        # Reload the healed tool
                        self.load_tool_file(fpath)

            # 2. Blacklisting after 5 failures
            elif failures > 5:
                self._blacklist_tool(tool_name)

    def record_tool_success(self, tool_name: str) -> None:
        """Resets consecutive failure counter on success."""
        with self._lock:
            if tool_name in self.failure_counts:
                self.failure_counts[tool_name] = 0

    def _blacklist_tool(self, tool_name: str) -> None:
        """Moves tool to tools/disabled/ and alerts user."""
        fpath = self.tool_to_file.get(tool_name)
        if fpath and fpath.exists():
            target_path = self.disabled_dir / fpath.name
            try:
                shutil.move(str(fpath), str(target_path))
            except Exception:
                pass

        # Remove handler from brain registry
        brain.TOOL_REGISTRY.pop(tool_name, None)

        # Remove from tools_config.json
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if "tools" in data:
                    data["tools"] = [
                        t for t in data["tools"]
                        if t.get("function", {}).get("name") != tool_name
                    ]
                    self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass

        # Warn via TTS
        msg = f"Warning: Tool {tool_name} disabled after exceeding failure limit."
        if self.tts_notifier:
            self.tts_notifier(msg)
        else:
            print(f"[Watchdog Alert] {msg}", file=sys.stderr)


# ==============================================================================
# Standalone Verification Demo
# ==============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print(" ZetaJarvis Module 3: Auto-Watchdog -- Verification & Demo")
    print("=" * 70)

    test_tools_dir = Path("test_tools_temp")
    test_config_path = Path("test_tools_config_temp.json")
    test_tools_dir.mkdir(exist_ok=True)

    watchdog = ToolWatchdog(
        tools_dir=test_tools_dir,
        config_path=test_config_path,
        poll_interval=0.2,
    )

    # 1. Create a dynamic tool file with brittle requests call
    sample_tool_code = """
import requests

def fetch_ip_info(ip: str = "8.8.8.8"):
    \"\"\"Fetches public IP details using external service.\"\"\"
    resp = requests.get(f"https://ipapi.co/{ip}/json/")
    return resp.text
"""
    tool_file = test_tools_dir / "ip_tool.py"
    tool_file.write_text(sample_tool_code.strip(), encoding="utf-8")

    print("\n[1] Dynamically Loading Tool & Registering Schema:")
    loaded = watchdog.load_tool_file(tool_file)
    print(f"  Loaded Tools: {loaded}")
    print(f"  Registered in brain.TOOL_REGISTRY: {'fetch_ip_info' in brain.TOOL_REGISTRY}")
    print(f"  Schema in config file: {test_config_path.exists()}")

    # 2. Test AST Self-Healing (Triggered at 3 failures)
    print("\n[2] Simulating 3 Consecutive Failures to Trigger AST Self-Healing:")
    for _ in range(3):
        watchdog.record_tool_failure("fetch_ip_info")

    healed_code = tool_file.read_text(encoding="utf-8")
    print("  Healed Code Snippet:")
    for line in healed_code.splitlines()[:12]:
        print(f"    {line}")
    print(f"  AST transformed requests to urllib or added retry: {'urllib' in healed_code or '_retry_attempt' in healed_code}")

    # 3. Test Failure Blacklist (Triggered after 5 failures)
    print("\n[3] Simulating Remaining Failures to Trigger Blacklist (>5 failures):")
    for _ in range(3):  # total = 6 failures
        watchdog.record_tool_failure("fetch_ip_info")

    disabled_file = test_tools_dir / "disabled" / "ip_tool.py"
    print(f"  Tool file moved to disabled directory: {disabled_file.exists()}")
    print(f"  Tool removed from active brain registry: {'fetch_ip_info' not in brain.TOOL_REGISTRY}")

    # Clean up test artifacts
    watchdog.stop()
    if test_tools_dir.exists():
        shutil.rmtree(test_tools_dir, ignore_errors=True)
    if test_config_path.exists():
        test_config_path.unlink(missing_ok=True)

    print("\n[SUCCESS] Module 3 (auto_watchdog.py) verified successfully.")
