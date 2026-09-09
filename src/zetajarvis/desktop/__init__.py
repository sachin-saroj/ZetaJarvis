#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: __init__.py
# Project: ZetaJarvis - Desktop Domination Layer
# Description: Exports HUD, voice pipeline, telemetry, resource governor, and log rotator.
# ------------------------------------------------------------------------------

"""ZetaJarvis Desktop Domination Subsystems."""

from __future__ import annotations

from zetajarvis.desktop.hud import ZetaHUD, get_system_telemetry
from zetajarvis.desktop.voice_pipeline import VoicePipeline
from zetajarvis.desktop.governor import ResourceGovernor
from zetajarvis.desktop.log_rotator import LogRotator
from zetajarvis.desktop.stealth_harness import StealthHarness

HUDOverlay = ZetaHUD

__all__ = [
    "ZetaHUD",
    "HUDOverlay",
    "get_system_telemetry",
    "VoicePipeline",
    "ResourceGovernor",
    "LogRotator",
    "StealthHarness",
]
