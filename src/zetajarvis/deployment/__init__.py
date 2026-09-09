#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: __init__.py
# Project: ZetaJarvis - Deployment Layer
# Description: Exports persistence, process guardian, self-updater, and installer.
# ------------------------------------------------------------------------------

"""ZetaJarvis Deployment and Resilience Subsystems."""

from __future__ import annotations

from zetajarvis.deployment.persistence import (
    AUTO_STARTUP_ENABLED,
    ProcessGuardian,
    StartupManager,
    apply_stealth_mode,
)
from zetajarvis.deployment.self_update import SelfUpdater
from zetajarvis.deployment.installer import (
    ZetaInstaller,
    get_default_install_dir,
    is_admin,
)

__all__ = [
    "StartupManager",
    "ProcessGuardian",
    "apply_stealth_mode",
    "AUTO_STARTUP_ENABLED",
    "SelfUpdater",
    "ZetaInstaller",
    "is_admin",
    "get_default_install_dir",
]
