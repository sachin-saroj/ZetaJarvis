#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: helpers.py
# Project: ZetaJarvis - Enterprise Digital Worker Node
# Description: Dynamic path resolution, configuration discovery, and environment
#              helpers for source, packaged, and frozen (.exe) runtimes.
# ------------------------------------------------------------------------------

"""Utility helpers for dynamic path and resource resolution."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Optional


def get_project_root() -> Path:
    """Dynamically discovers and returns the absolute path to the project root.

    Works seamlessly across development, editable package, and PyInstaller frozen modes.
    """
    # 1. Environment variable override
    env_root = os.getenv("ZETA_PROJECT_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.exists():
            return p

    # 2. PyInstaller Frozen Binary execution
    if getattr(sys, "frozen", False):
        # When frozen, sys.executable is inside dist/ or install_dir
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "configs").exists() or (exe_dir / "tools_config.json").exists():
            return exe_dir
        # PyInstaller _MEIPASS temp directory for bundled one-file assets
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return exe_dir

    # 3. Sentinel discovery walking up from this file
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists() or (parent / "configs").exists() or (parent / "pyproject.toml").exists():
            return parent

    # 4. Fallback to current working directory
    return Path.cwd().resolve()


def get_config_path(filename: str) -> Path:
    """Resolves a configuration file located in configs/ or falling back to root.

    Args:
        filename: Name of the configuration file (e.g. 'tools_config.json', 'VERSION.txt').

    Returns:
        Resolved absolute Path to the configuration file.
    """
    root = get_project_root()
    # Check configs/ subdirectory first
    in_configs = root / "configs" / filename
    if in_configs.exists():
        return in_configs
    # Fallback to root directory
    in_root = root / filename
    if in_root.exists():
        return in_root
    # Default to configs/ path if creating new or not yet existing
    return in_configs


def get_resource_path(filename: str) -> Path:
    """Resolves an asset/resource file located in resources/ or falling back to root.

    Args:
        filename: Name of the asset (e.g. 'icon.ico').

    Returns:
        Resolved absolute Path to the resource file.
    """
    root = get_project_root()
    in_resources = root / "resources" / filename
    if in_resources.exists():
        return in_resources
    in_root = root / filename
    if in_root.exists():
        return in_root
    return in_resources


def get_tools_dir() -> Path:
    """Resolves the tools directory for dynamic tool discovery and registration."""
    root = get_project_root()
    env_dir = os.getenv("TOOLS_DIR")
    if env_dir:
        p = Path(env_dir)
        return p if p.is_absolute() else (root / p)
    return root / "tools"
