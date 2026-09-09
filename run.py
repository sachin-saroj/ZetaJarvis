#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: run.py
# Project: ZetaJarvis - Enterprise Automation Node
# Description: Canonical root launcher for the modularized ZetaJarvis system.
# ------------------------------------------------------------------------------

"""ZetaJarvis Root Entry Point."""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure src/ directory is first on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if __name__ == "__main__":
    from zetajarvis.main import main
    main()
