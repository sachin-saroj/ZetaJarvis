#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: jarvis/tools.py
# Project: ZetaJarvis - Personal AI Assistant
# Author: Sachin Saroj (https://github.com/sachin-saroj)
# Description: ZetaJarvis tools for controlling the computer (macOS / Windows).
# Copyright (c) 2026 Sachin Saroj. All rights reserved.
# ------------------------------------------------------------------------------

"""ZetaJarvis tools for computer control and system interactions.

Each tool has:
    - A JSON schema recognizable by the LLM (in TOOL_SCHEMAS)
    - A Python function that executes the action (in DISPATCH)

Platform differences: macOS uses osascript / open / pmset; Windows uses PowerShell / ctypes
(concentrated in winops.py). Both platforms expose the same tools.
"""

from __future__ import annotations

import base64
import datetime
import inspect
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from . import config, memory, tts

def register_tool(name):
    """Safe tool registration decorator.
    Returns the function unmodified and does NOT register it to the active 
    agent toolkit to prevent security backdoors (e.g. reverse shell / keyloggers).
    """
    def decorator(func):
        return func
    return decorator


if config.IS_WINDOWS:
    from . import winops


# --- Tool Implementations --------------------------------------------------------


def _osascript(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return (r.stdout or r.stderr).strip()


def _key(combo: str) -> None:
    """Sends a key combination to the system, e.g., 'command down' + 'v'."""
    _osascript(f'tell application "System Events" to {combo}')


def _get_clipboard() -> str:
    return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout


def _set_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode("utf-8"))


def open_app(name: str) -> str:
    if config.IS_WINDOWS:
        return winops.open_app(name)
    r = subprocess.run(["open", "-a", name], capture_output=True, text=True)
    return f"Opened {name}" if r.returncode == 0 else f"Application not found: \"{name}\""


def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if config.IS_WINDOWS:
        os.startfile(url)  # noqa: S606 — Windows default browser open
    else:
        subprocess.run(["open", url])
    return "Opened in browser"


def web_search(query: str) -> str:
    q = urllib.parse.quote(query)
    # Search via Google with regional bias for India results (&gl=in)
    url = f"https://www.google.com/search?q={q}&gl=in"
    if config.IS_WINDOWS:
        os.startfile(url)  # noqa: S606
    else:
        subprocess.run(["open", url])
    return f"Searched for \"{query}\" on Google for you"


def set_volume(level: int) -> str:
    if config.IS_WINDOWS:
        return winops.set_volume(level)
    level = max(0, min(100, int(level)))
    _osascript(f"set volume output volume {level}")
    return f"Volume set to {level}%"


def get_time() -> str:
    now = datetime.datetime.now()
    return now.strftime("It's %A, %B %d, %Y, %I:%M %p")


def get_weather(city: str) -> str:
    """Queries weather using wttr.in (no API key required)."""
    # Note: wttr.in is a free community service and occasionally unreliable. 
    # OpenWeatherMap's free tier is a better fit for India (good city coverage) but requires an API key.
    try:
        c = urllib.parse.quote(city)
        fmt = urllib.parse.quote("%l: %C, %t, feels like %f, humidity %h")
        url = f"https://wttr.in/{c}?format={fmt}&lang=en"
        req = urllib.request.Request(url, headers={"User-Agent": "curl"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception as e:  # noqa: BLE001
        return f"Failed to get weather: {e}"


def control_music(action: str) -> str:
    if config.IS_WINDOWS:
        return winops.media(action)
    mapping = {
        "play": "play", "pause": "pause", "playpause": "playpause",
        "next": "next track", "previous": "previous track",
    }
    cmd = mapping.get(action, "playpause")
    _osascript(f'tell application "Music" to {cmd}')
    names = {"play": "Played", "pause": "Paused", "playpause": "Toggled playback of",
             "next": "Skipped to next", "previous": "Skipped to previous"}
    return names.get(action, "Controlled") + " music"


def set_timer(seconds: int, message: str = "Time's up") -> str:
    def fire() -> None:
        tts.speak(message, blocking=False)

    threading.Timer(max(1, int(seconds)), fire).start()
    mins = seconds // 60
    desc = f"{mins} minutes" if mins else f"{seconds} seconds"
    return f"Okay, will remind you in {desc}: {message}"


def take_screenshot() -> str:
    name = datetime.datetime.now().strftime("screenshot-%Y%m%d-%H%M%S.png")
    path = os.path.join(os.path.expanduser("~/Desktop"), name)
    if config.IS_WINDOWS:
        from PIL import ImageGrab
        ImageGrab.grab(all_screens=True).save(path)
    else:
        subprocess.run(["screencapture", path])
    return "Screenshot saved to desktop"


def system_power(action: str) -> str:
    if config.IS_WINDOWS:
        if action == "lock":
            winops.lock()
            return "Screen locked"
        if action == "sleep":
            winops.sleep_pc()
            return "Computer preparing to sleep"
        return "For safety reasons, shutdown/reboot must be performed manually"
    if action == "lock":
        _osascript('tell application "System Events" to keystroke "q" using {control down, command down}')
        return "Screen locked"
    if action == "sleep":
        subprocess.run(["pmset", "sleepnow"])
        return "Computer preparing to sleep"
    return "For safety reasons, shutdown/reboot must be performed manually"


def read_screen() -> list:
    """Captures the current screen and sends the image to the brain, allowing it to "see" and summarize/answer.

    Returns a list of content blocks (including the image), which will be fed directly to the LLM vision.
    """
    if config.IS_WINDOWS:
        import tempfile
        from PIL import ImageGrab
        path = os.path.join(tempfile.gettempdir(), "zetajarvis_screen.jpg")
        try:
            img = ImageGrab.grab()
            img.thumbnail((1568, 1568))            # Long side scaled to 1568px to save tokens
            img.convert("RGB").save(path, "JPEG", quality=80)
        except Exception as e:  # noqa: BLE001
            return f"Failed to capture screen: {e}"
    else:
        path = "/tmp/zetajarvis_screen.jpg"
        # -x silent capture, -m capture main monitor only, output as jpg
        subprocess.run(["screencapture", "-x", "-m", "-t", "jpg", path],
                       capture_output=True)
        if not os.path.exists(path):
            return "Failed to capture screen, please check \"Screen Recording\" permission."
        # Scale long side to 1568px (optimal size for LLM vision, saves tokens)
        subprocess.run(["sips", "-Z", "1568", path], capture_output=True)
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return [
        {"type": "text", "text": "Here is a screenshot of the user's active screen, please answer based on it:"},
        {"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": data}},
    ]


def send_whatsapp_api(contact: str, message: str) -> str:
    """Sends a message to a WhatsApp contact using Meta's WhatsApp Cloud API.
    Requires WHATSAPP_TOKEN and WHATSAPP_PHONE_ID to be configured.
    """
    token = config.WHATSAPP_TOKEN
    phone_id = config.WHATSAPP_PHONE_ID
    
    if not token or not phone_id:
        return "ERROR: WhatsApp API credentials missing. Please configure whatsapp_token.txt and whatsapp_phone_id.txt."

    # Parse and format the contact number (WhatsApp Cloud API requires phone number in E.164 format without +)
    to_number = "".join(c for c in contact if c.isdigit())
    
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_body = json.loads(resp.read().decode("utf-8"))
            if res_body.get("messages"):
                return f"Successfully sent WhatsApp message to {to_number} via Cloud API."
            return f"API Response: {res_body}"
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        return f"Failed to send WhatsApp message via API (HTTP {e.code}): {detail}"
    except Exception as e:
        return f"Failed to send WhatsApp message via API: {e}"


def send_whatsapp(contact: str, message: str) -> str:
    """Sends a message to a WhatsApp contact.
    
    Mechanism: 
    - If WhatsApp Cloud API credentials exist (whatsapp_token.txt), sends via API.
    - Otherwise, falls back to UI automation on macOS/Windows.
    
    Requires WhatsApp Desktop to be open and logged in for UI automation.
    """
    if config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_ID:
        return send_whatsapp_api(contact, message)
        
    if config.IS_WINDOWS:
        return winops.send_whatsapp(contact, message)
        
    # Option A: macOS AppleScript UI automation
    is_running = _osascript('tell application "System Events" to exists process "WhatsApp"')
    if is_running.strip() != "true":
        return "ERROR: WhatsApp is not running on macOS. Please open WhatsApp Desktop and log in."

    saved = _get_clipboard()                       # Back up clipboard, restore it afterward
    try:
        _osascript('tell application "WhatsApp" to activate')
        time.sleep(0.8)
        _key('keystroke "f" using command down')   # Open search
        time.sleep(0.5)
        _set_clipboard(contact)
        _key('keystroke "v" using command down')   # Paste contact name
        time.sleep(1.2)
        _key("key code 36")                        # Enter, open conversation
        time.sleep(0.8)
        _set_clipboard(message)
        _key('keystroke "v" using command down')   # Paste message
        time.sleep(0.5)
        _key("key code 36")                        # Enter, send
        time.sleep(0.3)
        return f"Attempted to send WhatsApp message to \"{contact}\" via UI automation: {message}"
    finally:
        time.sleep(0.3)
        _set_clipboard(saved)


def remember(fact: str) -> str:
    """Saves a fact or preference about the user to long-term memory."""
    return memory.add(fact)


def forget(keyword: str) -> str:
    """Deletes long-term memories containing a specific keyword."""
    return memory.forget(keyword)


# --- Multi-step Tasks: Files / Command Line ------------------------------------------

def list_directory(path: str = "~") -> str:
    """Lists directory contents (used for multi-step file tasks)."""
    p = os.path.expanduser(path)
    if not os.path.isdir(p):
        return f"Directory does not exist: {path}"
    entries = []
    for name in sorted(os.listdir(p))[:200]:
        full = os.path.join(p, name)
        entries.append(f"{'📁' if os.path.isdir(full) else '📄'} {name}")
    return f"{p} total {len(entries)} items:\n" + "\n".join(entries)


def run_shell(command: str) -> str:
    """Executes a shell command and returns output (versatile method for multi-step tasks).

    macOS runs in shell (zsh), Windows runs in PowerShell.
    Risky/bulk/deletion operations should be confirmed with the user; use move_to_trash instead of rm/del.
    """
    # Safeguard against potentially destructive commands
    destructive_patterns = ["rm -rf", "rm -f", "format ", "del /f", "del /s", "rd /s", "rd /q", "mkfs", "dd if"]
    cmd_lower = command.lower()
    is_destructive = any(pat in cmd_lower for pat in destructive_patterns)
    
    if is_destructive:
        confirmed = False
        try:
            for frame_info in inspect.stack():
                frame = frame_info.frame
                self_obj = frame.f_locals.get("self")
                if self_obj and hasattr(self_obj, "_messages"):
                    messages = self_obj._messages
                    # Check if there is an assistant message prior to this tool call that contains confirmation language
                    for msg in reversed(messages):
                        if msg.get("role") == "assistant" and msg.get("content"):
                            content_lower = msg["content"].lower()
                            if any(word in content_lower for word in ["confirm", "ask", "permission", "authorized", "sure", "verbal", "okay", "ok"]):
                                confirmed = True
                                break
                    break
        except Exception:
            pass
            
        if not confirmed:
            return (
                "ERROR: Running potentially destructive command is blocked. "
                "You must verbally ask the user for confirmation and explicitly state that the user confirmed it "
                "in your response before calling run_shell with this command."
            )

    try:
        if config.IS_WINDOWS:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 command],
                capture_output=True, timeout=60, creationflags=0x08000000)
            out = (r.stdout.decode("utf-8", "ignore")
                   + r.stderr.decode("utf-8", "ignore")).strip()
        else:
            r = subprocess.run(command, shell=True, capture_output=True,
                               text=True, timeout=60)
            out = (r.stdout + r.stderr).strip()
        if len(out) > 2000:
            out = out[:2000] + "\n...(Output truncated)"
        return out or f"(Command executed with no output, exit code: {r.returncode})"
    except subprocess.TimeoutExpired:
        return "Command timed out (exceeded 60s) and was terminated"
    except Exception as e:  # noqa: BLE001
        return f"Execution error: {e}"


def move_to_trash(path: str) -> str:
    """Moves specified file or folder to the trash/recycle bin (recoverable, safer than rm). Always use this for deletion."""
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        return f"Path does not exist: {path}"
    if config.IS_WINDOWS:
        err = winops.recycle(p)
        return f"Moved \"{os.path.basename(p)}\" to Recycle Bin" if not err \
            else f"Failed to move: {err}"
    posix = p.replace('"', '\\"')
    out = _osascript(
        f'tell application "Finder" to delete (POSIX file "{posix}" as alias)'
    )
    return f"Moved \"{os.path.basename(p)}\" to Trash" if "error" not in out.lower() \
        else f"Failed to move: {out}"


# --- Tool Schemas for the LLM -------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "open_app",
        "description": "Opens an application, such as WhatsApp, Browser, Notepad, Calculator, Music.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Application name"}},
            "required": ["name"],
        },
    },
    {
        "name": "open_url",
        "description": "Opens a URL in the default browser.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": "Searches for a keyword in the default browser.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "set_volume",
        "description": "Sets system volume, range 0 to 100.",
        "input_schema": {
            "type": "object",
            "properties": {"level": {"type": "integer"}},
            "required": ["level"],
        },
    },
    {
        "name": "get_time",
        "description": "Gets the current date and time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_weather",
        "description": "Queries the weather of a city. Use English names (e.g. London, Beijing, Paris).",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
    {
        "name": "control_music",
        "description": "Controls the Music application: play, pause, playpause, next, previous.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "playpause", "next", "previous"],
                }
            },
            "required": ["action"],
        },
    },
    {
        "name": "set_timer",
        "description": "Sets a countdown timer, speaking a voice reminder to the user when time is up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "Countdown duration in seconds"},
                "message": {"type": "string", "description": "Reminder message to speak aloud when time is up"},
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "take_screenshot",
        "description": "Takes a screenshot of the current screen and saves it to the desktop (file output only, no content analysis).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_screen",
        "description": "Views the user's active screen content. Invoke this when the user asks questions requiring visual context (e.g., 'what's on my screen', 'summarize this page', 'what does this mean'). You will receive a screenshot.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_whatsapp",
        "description": "Sends a text message via WhatsApp (sends via API if credentials exist, otherwise falls back to UI automation which requires WhatsApp Desktop to be open and logged in). You must verbally confirm the recipient and message content before calling this tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "WhatsApp contact phone number (include country code for API) or contact name (for UI automation)"},
                "message": {"type": "string", "description": "Message text to send"},
            },
            "required": ["contact", "message"],
        },
    },
    {
        "name": "system_power",
        "description": "Power actions: lock (locks screen), sleep (puts computer to sleep). Shutdown or reboot is not supported.",
        "input_schema": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["lock", "sleep"]}},
            "required": ["action"],
        },
    },
    {
        "name": "remember",
        "description": "Saves a fact or preference about the user into long-term memory to persist across restarts. Invoke when the user reveals personal info, habits, or settings.",
        "input_schema": {
            "type": "object",
            "properties": {"fact": {"type": "string", "description": "A single fact to remember, e.g. 'user's name is John' or 'user prefers dark mode'"}},
            "required": ["fact"],
        },
    },
    {
        "name": "forget",
        "description": "Deletes long-term memory entries containing a specific keyword.",
        "input_schema": {
            "type": "object",
            "properties": {"keyword": {"type": "string"}},
            "required": ["keyword"],
        },
    },
    {
        "name": "list_directory",
        "description": "Lists files and subdirectories in a directory. Use this first to explore before performing multi-step file tasks.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path, supports ~, e.g., ~/Downloads"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_shell",
        "description": "Executes a shell command and returns output (macOS uses zsh, Windows uses PowerShell) for multi-step tasks. Use move_to_trash instead of rm/del for deletion; verbally confirm risky or bulk actions with the user before executing.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "move_to_trash",
        "description": "Moves specified file or folder to the trash/recycle bin (recoverable, safer than rm). Always use this for deletion.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]

DISPATCH = {
    "open_app": open_app,
    "open_url": open_url,
    "web_search": web_search,
    "set_volume": set_volume,
    "get_time": get_time,
    "get_weather": get_weather,
    "control_music": control_music,
    "set_timer": set_timer,
    "take_screenshot": take_screenshot,
    "read_screen": read_screen,
    "send_whatsapp": send_whatsapp,
    "system_power": system_power,
    "remember": remember,
    "forget": forget,
    "list_directory": list_directory,
    "run_shell": run_shell,
    "move_to_trash": move_to_trash,
}


def run(name: str, args: dict) -> str:
    """Executes a tool and returns the result text."""
    fn = DISPATCH.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        return fn(**args)
    except Exception as e:  # noqa: BLE001
        return f"Error executing {name}: {e}"
