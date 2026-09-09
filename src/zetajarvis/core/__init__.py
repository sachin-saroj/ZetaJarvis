#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: __init__.py
# Project: ZetaJarvis - Core Multi-Model Routing Engine
# Description: Exports core router, dispatcher, and token economy APIs.
# ------------------------------------------------------------------------------

"""ZetaJarvis Core Multi-Model Engine."""

from __future__ import annotations

from zetajarvis.core.dispatcher import (
    DynamicToolDispatcher,
    TOOL_REGISTRY,
    calculate_jitter_backoff,
    load_tools_config,
    register_tool_handler,
)
from zetajarvis.core.brain import (
    Brain,
    FALLBACK_CHAIN,
    MODEL_PRIMARY,
    MODEL_SECONDARY,
    MODEL_TERTIARY,
    MultiModelRouter,
    RequestQueue,
    TFIDFResponseCache,
    abbreviate_prompt,
    estimate_messages_tokens,
    estimate_tokens,
    get_brain_response,
    get_usage_stats,
    heuristic_summarize,
    is_governor_throttled,
    reset_token_counter,
    set_governor_throttle,
    truncate_and_compress_history,
)

__all__ = [
    "Brain",
    "MultiModelRouter",
    "DynamicToolDispatcher",
    "RequestQueue",
    "TFIDFResponseCache",
    "get_brain_response",
    "get_usage_stats",
    "set_governor_throttle",
    "is_governor_throttled",
    "reset_token_counter",
    "abbreviate_prompt",
    "heuristic_summarize",
    "estimate_tokens",
    "estimate_messages_tokens",
    "truncate_and_compress_history",
    "TOOL_REGISTRY",
    "register_tool_handler",
    "load_tools_config",
    "calculate_jitter_backoff",
    "FALLBACK_CHAIN",
    "MODEL_PRIMARY",
    "MODEL_SECONDARY",
    "MODEL_TERTIARY",
]
