#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# File: test_domination_layer.py
# Project: ZetaJarvis - Desktop Domination Layer Test Suite
# Description: Unit and integration tests for HUD, Voice Pipeline,
#              Auto-Watchdog, Stealth Harness, and Central Orchestrator.
# ------------------------------------------------------------------------------

"""Comprehensive Test Suite for Desktop Domination Layer."""

import json
from pathlib import Path
import shutil
import time
import unittest
from unittest.mock import MagicMock, patch
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*Setting the shape on a NumPy array.*")

import auto_watchdog
import brain
import hud
import main
import stealth_harness
import voice_pipeline


class TestModule1HUD(unittest.TestCase):
    """Tests for Module 1: hud.py."""

    def test_telemetry_fields(self):
        telem = hud.get_system_telemetry()
        self.assertIn("cpu", telem)
        self.assertIn("ram", telem)
        self.assertIn("gpu", telem)
        self.assertTrue(isinstance(telem["cpu"], str))
        self.assertTrue(isinstance(telem["ram"], str))

    def test_hud_queue_actions(self):
        killed = False

        def on_kill():
            nonlocal killed
            killed = True

        h = hud.ZetaHUD(on_force_kill=on_kill)
        # Verify queue helper methods
        h.update_tokens(session=10, daily=200, quota=50000, model="test-model")
        self.assertFalse(h.queue.empty())
        item = h.queue.get_nowait()
        self.assertEqual(item["type"], "token_update")
        self.assertEqual(item["session"], 10)

        # Verify force kill
        h.trigger_force_kill()
        self.assertTrue(killed)


class TestModule2VoicePipeline(unittest.TestCase):
    """Tests for Module 2: voice_pipeline.py."""

    def test_pre_roll_math(self):
        self.assertEqual(voice_pipeline.SAMPLE_RATE, 16000)
        self.assertEqual(voice_pipeline.CHUNK_SIZE, 480)
        self.assertEqual(voice_pipeline.PRE_ROLL_CHUNKS, 10)
        total_samples = voice_pipeline.PRE_ROLL_CHUNKS * voice_pipeline.CHUNK_SIZE
        # 4800 samples at 16000 Hz = 0.300 seconds (300 ms)
        self.assertEqual(total_samples / voice_pipeline.SAMPLE_RATE, 0.3)

    def test_dynamic_tts_rate_modulation(self):
        tts = voice_pipeline.DualLayerTTS(base_rate=190)
        short_msg = "Short acknowledgment."
        long_msg = "A" * 501
        self.assertEqual(tts.calculate_rate(len(short_msg)), 190)
        # +20% speedup
        self.assertEqual(tts.calculate_rate(len(long_msg)), int(190 * 1.2))

    def test_vad_rms_logic(self):
        if voice_pipeline.np is not None:
            silence = voice_pipeline.np.zeros(480, dtype=voice_pipeline.np.float32)
            self.assertEqual(voice_pipeline.compute_rms(silence), 0.0)
        else:
            silence = [0.0] * 480
            self.assertEqual(voice_pipeline.compute_rms(silence), 0.0)


class TestModule3AutoWatchdog(unittest.TestCase):
    """Tests for Module 3: auto_watchdog.py."""

    def setUp(self):
        self.temp_dir = Path("test_watchdog_dir_temp")
        self.temp_config = Path("test_watchdog_config_temp.json")
        self.temp_dir.mkdir(exist_ok=True)
        self.watchdog = auto_watchdog.ToolWatchdog(
            tools_dir=self.temp_dir,
            config_path=self.temp_config,
            poll_interval=0.1,
        )

    def tearDown(self):
        self.watchdog.stop()
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        if self.temp_config.exists():
            self.temp_config.unlink(missing_ok=True)

    def test_dynamic_tool_loading_and_schema(self):
        t_file = self.temp_dir / "math_tool.py"
        t_file.write_text(
            'def multiply(x: int, y: int):\n    """Multiplies two numbers."""\n    return x * y\n',
            encoding="utf-8",
        )
        loaded = self.watchdog.load_tool_file(t_file)
        self.assertIn("multiply", loaded)
        self.assertIn("multiply", brain.TOOL_REGISTRY)

        # Check schema in JSON
        self.assertTrue(self.temp_config.exists())
        cfg = json.loads(self.temp_config.read_text(encoding="utf-8"))
        names = [t["function"]["name"] for t in cfg["tools"]]
        self.assertIn("multiply", names)

    def test_ast_self_healing(self):
        t_file = self.temp_dir / "brittle_tool.py"
        code = (
            "import requests\n"
            "def fetch_data():\n"
            "    return requests.get('https://api.test/data').text\n"
        )
        t_file.write_text(code, encoding="utf-8")
        self.watchdog.load_tool_file(t_file)

        # Simulate 3 failures
        for _ in range(3):
            self.watchdog.record_tool_failure("fetch_data")

        healed = t_file.read_text(encoding="utf-8")
        self.assertTrue("urllib" in healed or "_retry_attempt" in healed)

    def test_failure_blacklisting(self):
        t_file = self.temp_dir / "failing_tool.py"
        t_file.write_text("def doomed():\n    raise RuntimeError('broken')\n", encoding="utf-8")
        self.watchdog.load_tool_file(t_file)

        # Simulate 6 failures (exceeds threshold of 5)
        for _ in range(6):
            self.watchdog.record_tool_failure("doomed")

        disabled_path = self.temp_dir / "disabled" / "failing_tool.py"
        self.assertTrue(disabled_path.exists())
        self.assertNotIn("doomed", brain.TOOL_REGISTRY)


class TestModule4StealthHarness(unittest.TestCase):
    """Tests for Module 4: stealth_harness.py."""

    def setUp(self):
        self.test_log = Path("test_diag_logs_harness_temp.csv")
        self.harness = stealth_harness.StealthHarness(log_path=self.test_log)

    def tearDown(self):
        if self.test_log.exists():
            self.test_log.unlink(missing_ok=True)

    def test_encrypted_csv_zero_plaintext(self):
        cipher = stealth_harness.EncryptedLogCipher(master_key="TestSecretKey")
        plain = "timestamp,test_01,What time is it?,get_current_time,12.5,SUCCESS"
        encrypted = cipher.encrypt_string(plain)
        self.assertNotEqual(plain, encrypted)
        self.assertNotIn("get_current_time", encrypted)

        decrypted = cipher.decrypt_string(encrypted)
        self.assertEqual(plain, decrypted)

    def test_cloud_evasion_detection(self):
        with patch.dict("os.environ", {"GOOGLE_COLAB": "1"}):
            self.assertTrue(stealth_harness.is_cloud_or_shared_environment())

        with patch.dict("os.environ", {"GOOGLE_COLAB": "", "CI": "", "AGENT_MODE": ""}, clear=True):
            # Should be false when clear
            self.assertFalse(stealth_harness.is_cloud_or_shared_environment())

    def test_panic_lockdown_trigger(self):
        self.assertTrue(self.harness.check_panic_trigger("Zeta, lockdown immediately"))
        self.assertTrue(self.harness.check_panic_trigger("lockdown"))
        self.assertFalse(self.harness.check_panic_trigger("What is the weather?"))

        # Add data to cache and tokens
        brain._STATS_TRACKER.record_usage(100, brain.MODEL_PRIMARY)
        brain._TFIDF_CACHE.add("hello", "hi", 10, brain.MODEL_PRIMARY)

        # Trigger lockdown
        self.harness.trigger_lockdown()
        stats = brain.get_usage_stats()
        self.assertEqual(stats["daily_token_usage"], 0)
        self.assertIsNone(brain._TFIDF_CACHE.find_match("hello"))


class TestMainOrchestrator(unittest.TestCase):
    """Tests for main.py."""

    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings("ignore", category=DeprecationWarning)

    def test_app_lifecycle(self):
        app = main.ZetaJarvisDesktopApp(headless=True)
        app.start()
        time.sleep(0.3)
        self.assertTrue(app.voice._supervisor_thread.is_alive())
        self.assertTrue(app.watchdog._thread.is_alive())
        app.stop()
        self.assertTrue(app._shutdown_event.is_set())


if __name__ == "__main__":
    unittest.main()
