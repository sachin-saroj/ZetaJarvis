#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: __init__.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Top-level package initialization exposing core APIs.
# ------------------------------------------------------------------------------

"""ZetaJarvis Enterprise Digital Worker Node & Desktop Domination Layer."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src directory is in sys.path when imported
_SRC_DIR = str(Path(__file__).resolve().parent.parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from zetajarvis.core.brain import (
    Brain,
    MultiModelRouter,
    get_brain_response,
    get_usage_stats,
)
from zetajarvis.core.dispatcher import DynamicToolDispatcher
from zetajarvis.desktop.hud import ZetaHUD
from zetajarvis.desktop.voice_pipeline import VoicePipeline

__version__ = "1.0.0.0"

__all__ = [
    "Brain",
    "MultiModelRouter",
    "DynamicToolDispatcher",
    "get_brain_response",
    "get_usage_stats",
    "ZetaHUD",
    "VoicePipeline",
    "ZetaJarvisDesktopApp",
    "__version__",
]


def __getattr__(name: str):
    if name == "ZetaJarvisDesktopApp":
        from zetajarvis.main import ZetaJarvisDesktopApp
        return ZetaJarvisDesktopApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
