#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: __init__.py
# Project: ZetaJarvis - Automation Layer
# Description: Exports UI automation, window control, and metaprogramming watchdog.
# ------------------------------------------------------------------------------

"""ZetaJarvis Automation Subsystems."""

from __future__ import annotations

from zetajarvis.automation.auto_watchdog import ToolWatchdog
from zetajarvis.automation.ui_automation import (
    ApplicationController,
    WindowController,
    check_abort_phrase,
    is_aborted,
    register_ui_tools_to_config,
    reset_abort,
    trigger_abort,
)

abort_automation = trigger_abort

__all__ = [
    "ToolWatchdog",
    "ApplicationController",
    "WindowController",
    "trigger_abort",
    "abort_automation",
    "is_aborted",
    "reset_abort",
    "check_abort_phrase",
    "register_ui_tools_to_config",
]
