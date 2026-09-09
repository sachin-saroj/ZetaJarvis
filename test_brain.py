#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: test_brain.py
# Project: ZetaJarvis - Brain Engine Test Suite
# Description: Rigorous unit and integration test suite validating all core
#              capabilities of the self-adaptive multi-model routing engine.
# ------------------------------------------------------------------------------

"""Comprehensive Test Suite for ZetaJarvis brain.py."""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

import brain
from brain import (
    FALLBACK_CHAIN,
    MODEL_PRIMARY,
    MODEL_SECONDARY,
    MODEL_TERTIARY,
    Brain,
    DynamicToolDispatcher,
    MultiModelRouter,
    RequestQueue,
    TFIDFResponseCache,
    abbreviate_prompt,
    calculate_jitter_backoff,
    estimate_messages_tokens,
    estimate_tokens,
    get_brain_response,
    get_usage_stats,
    heuristic_summarize,
    register_tool_handler,
    reset_token_counter,
    truncate_and_compress_history,
)


class TestJitterAndBackoff(unittest.TestCase):
    """Tests exponential jitter backoff calculations."""

    def test_jitter_bounds(self):
        base = 1.0
        max_b = 30.0
        for attempt in range(6):
            backoff = calculate_jitter_backoff(attempt, base=base, max_backoff=max_b)
            self.assertGreaterEqual(backoff, base)
            self.assertLessEqual(backoff, max_b)

    def test_request_queue_retries_transient_error(self):
        queue = RequestQueue()
        attempts_recorded = []

        def failing_function(attempt: int):
            attempts_recorded.append(attempt)
            if attempt < 2:
                # Simulate transient 429 rate limit error
                err = Exception("HTTP 429 Too Many Requests: Rate limit reached")
                setattr(err, "status_code", 429)
                raise err
            return "success_after_retries"

        # Patch sleep to make test instant
        with patch("time.sleep", return_value=None) as mock_sleep:
            result = queue.execute_with_jitter_retry(
                failing_function, max_retries=3, model_name="test_model"
            )
            self.assertEqual(result, "success_after_retries")
            self.assertEqual(attempts_recorded, [0, 1, 2])
            self.assertEqual(mock_sleep.call_count, 2)


class TestDynamicToolDispatcher(unittest.TestCase):
    """Tests dynamic tool schema loading, parallel execution, and auto-retry."""

    def setUp(self):
        self.dispatcher = DynamicToolDispatcher()

    def test_tools_loaded_from_json(self):
        self.assertTrue(len(self.dispatcher.tools) >= 3)
        tool_names = [
            t["function"]["name"]
            for t in self.dispatcher.tools
            if "function" in t
        ]
        self.assertIn("get_current_time", tool_names)
        self.assertIn("get_weather", tool_names)
        self.assertIn("calculate", tool_names)

    def test_parallel_execution(self):
        mock_calls = [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "calculate", "arguments": '{"expression": "10 * 5"}'},
            },
            {
                "id": "c2",
                "type": "function",
                "function": {"name": "get_current_time", "arguments": '{"timezone": "UTC"}'},
            },
            {
                "id": "c3",
                "type": "function",
                "function": {"name": "system_info", "arguments": "{}"},
            },
        ]
        results = self.dispatcher.dispatch_parallel(mock_calls)
        self.assertEqual(len(results), 3)

        res_map = {r["tool_call_id"]: r["content"] for r in results}
        self.assertEqual(res_map["c1"], "50")
        self.assertIn("timezone: UTC", res_map["c2"])
        self.assertIn("os", res_map["c3"])

    def test_tool_auto_retry_transient_error(self):
        attempts = []

        def flaky_tool(location: str):
            attempts.append(location)
            if len(attempts) < 2:
                raise ConnectionError("Temporary network glitch connecting to weather service")
            return json.dumps({"location": location, "temp": 28})

        register_tool_handler("flaky_weather", flaky_tool)

        with patch("time.sleep", return_value=None):
            output = self.dispatcher._execute_single_tool("flaky_weather", {"location": "Delhi"})
            data = json.loads(output)
            self.assertEqual(data["location"], "Delhi")
            self.assertEqual(data["temp"], 28)
            self.assertEqual(len(attempts), 2)


class TestConversationTruncationAndSummarization(unittest.TestCase):
    """Tests token-aware history truncation with entity/date/action preservation."""

    def test_heuristic_summarizer_extracts_entities_dates_actions(self):
        messages = [
            {"role": "user", "content": "I am Sachin Saroj. Today is 2026-09-09 in Mumbai."},
            {"role": "assistant", "content": "I searched the web for artificial intelligence."},
        ]
        summary = heuristic_summarize(messages)
        self.assertIn("Sachin Saroj", summary)
        self.assertIn("2026-09-09", summary)
        self.assertIn("searched", summary)

    def test_system_prompt_and_last_3_tool_calls_preserved(self):
        history = [
            {"role": "system", "content": "Master System Instruction"},
            {"role": "user", "content": "Turn 1: hello"},
            {"role": "assistant", "content": "Turn 1 reply"},
            {"role": "user", "content": "Turn 2: how are you"},
            {"role": "assistant", "content": "Turn 2 reply"},
            # Tool call 1
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "tool1", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "t1", "content": "t1_result"},
            # Tool call 2
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "t2", "type": "function", "function": {"name": "tool2", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "t2", "content": "t2_result"},
            # Tool call 3
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "t3", "type": "function", "function": {"name": "tool3", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "t3", "content": "t3_result"},
            {"role": "user", "content": "Latest user message"},
        ]

        # Force truncation with small max_history and small token threshold
        truncated = truncate_and_compress_history(history, max_history=4, token_threshold=20)

        # Invariant 1: System prompt is at index 0
        self.assertEqual(truncated[0]["role"], "system")
        self.assertEqual(truncated[0]["content"], "Master System Instruction")

        # Invariant 2: Summary exists
        self.assertEqual(truncated[1]["role"], "system")
        self.assertTrue(truncated[1]["content"].startswith("[Context Summary:"))

        # Invariant 3: Last 3 tool calls are all preserved
        tool_ids_present = {m.get("tool_call_id") for m in truncated if m.get("role") == "tool"}
        self.assertIn("t1", tool_ids_present)
        self.assertIn("t2", tool_ids_present)
        self.assertIn("t3", tool_ids_present)


class TestStealthTokenEconomy(unittest.TestCase):
    """Tests TF-IDF semantic caching and proactive prompt abbreviation."""

    def setUp(self):
        reset_token_counter()

    def test_tfidf_cache_hit_and_miss(self):
        cache = TFIDFResponseCache(similarity_threshold=0.85)
        cache.add(
            "What is quantum computing and how does it work?",
            "Quantum computing uses qubits and superposition.",
            50,
            MODEL_PRIMARY,
        )

        # Highly similar query
        hit = cache.find_match("Tell me what is quantum computing and how does it work")
        self.assertIsNotNone(hit)
        self.assertIn("(cached)", hit[0])

        # Dissimilar query
        miss = cache.find_match("What is the recipe for baking chocolate cookies?")
        self.assertIsNone(miss)

    def test_proactive_abbreviation(self):
        verbose = (
            "Could you please kindly tell me basically what is the weather in Delhi, "
            "and furthermore would you mind actually calculating 25 * 4?"
        )
        shortened = abbreviate_prompt(verbose)
        self.assertNotIn("could you please kindly", shortened.lower())
        self.assertNotIn("basically", shortened.lower())
        self.assertNotIn("furthermore", shortened.lower())
        self.assertNotIn("actually", shortened.lower())
        self.assertIn("weather in Delhi", shortened)
        self.assertIn("25 * 4", shortened)

    def test_proactive_abbreviation_activates_at_80_percent_quota(self):
        reset_token_counter()
        stats = brain._STATS_TRACKER
        stats.quota = 1000

        # Under 80%
        stats.record_usage(700, MODEL_PRIMARY)
        self.assertFalse(stats.is_abbreviation_mode())

        # Reach 80%
        stats.record_usage(100, MODEL_PRIMARY)
        self.assertTrue(stats.is_abbreviation_mode())


class TestModelFallbackChain(unittest.TestCase):
    """Tests model fallback sequence: Primary -> Secondary -> Tertiary."""

    def test_fallback_chain_triggers_on_429(self):
        router = MultiModelRouter(
            api_key="mock_key",
            fallback_chain=[MODEL_PRIMARY, MODEL_SECONDARY, MODEL_TERTIARY],
        )

        # Create mock client
        mock_client = MagicMock()

        def mock_create(**kwargs):
            model = kwargs.get("model")
            if model == MODEL_PRIMARY:
                err = Exception("Rate limit reached (HTTP 429)")
                setattr(err, "status_code", 429)
                raise err
            elif model == MODEL_SECONDARY:
                # Secondary model succeeds
                mock_msg = MagicMock()
                mock_msg.content = "Response from LLaMA 3.3 70B"
                mock_msg.tool_calls = None
                mock_choice = MagicMock()
                mock_choice.message = mock_msg
                mock_resp = MagicMock()
                mock_resp.choices = [mock_choice]
                mock_resp.usage.prompt_tokens = 20
                mock_resp.usage.completion_tokens = 10
                return mock_resp
            raise RuntimeError("Unexpected model called")

        mock_client.chat.completions.create.side_effect = mock_create
        router._client = mock_client

        with patch("time.sleep", return_value=None):
            msg, tokens, model_used = router.route_completion(
                [{"role": "user", "content": "Test prompt"}]
            )

            self.assertEqual(model_used, MODEL_SECONDARY)
            self.assertEqual(msg["content"], "Response from LLaMA 3.3 70B")
            self.assertGreater(tokens, 0)


class TestAdminStatsAndPublicAPIs(unittest.TestCase):
    """Tests get_brain_response, reset_token_counter, get_usage_stats, and Brain class."""

    def setUp(self):
        reset_token_counter()

    def test_reset_and_stats(self):
        stats_before = get_usage_stats()
        self.assertEqual(stats_before["daily_token_usage"], 0)

        brain._STATS_TRACKER.record_usage(150, MODEL_PRIMARY)
        stats_after = get_usage_stats()
        self.assertEqual(stats_after["daily_token_usage"], 150)
        self.assertEqual(stats_after["total_requests"], 1)

        reset_token_counter()
        stats_reset = get_usage_stats()
        self.assertEqual(stats_reset["daily_token_usage"], 0)

    def test_brain_class_ask_and_ask_stream(self):
        b = Brain()
        b.reset()
        self.assertEqual(len(b._history), 0)

        # Mock the router for Brain.ask
        mock_router = MagicMock()
        mock_router.route_completion.return_value = (
            {"role": "assistant", "content": "Hello! I am ready. How can I help?"},
            25,
            MODEL_PRIMARY,
        )
        b._router = mock_router

        ans = b.ask("Hello")
        self.assertIn("Hello! I am ready", ans)

        # Test ask_stream yields sentences
        chunks = list(b.ask_stream("Hello again"))
        self.assertTrue(len(chunks) >= 1)
        self.assertIn("Hello! I am ready", " ".join(chunks))


if __name__ == "__main__":
    unittest.main()
