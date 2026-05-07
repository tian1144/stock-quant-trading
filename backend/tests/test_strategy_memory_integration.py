from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import ai_model_service, strategy_memory_service  # noqa: E402


class FakeResponse:
    status_code = 200
    text = '{"ok": true}'

    def __init__(self, content: str = '{"ok": true}'):
        self._content = content

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


class StrategyMemoryIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.original_memory_path = strategy_memory_service.MEMORY_PATH
        self.original_trading_mode_path = strategy_memory_service.TRADING_MODE_PATH
        self.original_config_path = ai_model_service.CONFIG_PATH
        strategy_memory_service.MEMORY_PATH = str(self.tmp_path / "strategy_memory.json")
        strategy_memory_service.TRADING_MODE_PATH = str(self.tmp_path / "ai_trading_mode.json")
        ai_model_service.CONFIG_PATH = str(self.tmp_path / "model_config.json")
        self.sentinel = "MEMORY_SENTINEL_MODEL_SWITCH_REFLECTION"

    def tearDown(self) -> None:
        strategy_memory_service.MEMORY_PATH = self.original_memory_path
        strategy_memory_service.TRADING_MODE_PATH = self.original_trading_mode_path
        ai_model_service.CONFIG_PATH = self.original_config_path
        self.tmp.cleanup()

    def _write_config(self, selected_model: str = "model-a", risk_model: str = "risk-model") -> None:
        config = ai_model_service._default_config()
        config.update(
            {
                "enabled": True,
                "provider": "openai_compatible",
                "provider_name": "OpenAI compatible test",
                "base_url": "http://fake.local/v1",
                "api_key": "test-key",
                "selected_model": selected_model,
            }
        )
        config["risk_verifier"].update(
            {
                "enabled": True,
                "provider": "openai_compatible",
                "provider_name": "Risk verifier test",
                "base_url": "http://risk.fake.local/v1",
                "api_key": "risk-key",
                "selected_model": risk_model,
            }
        )
        with open(ai_model_service.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def _seed_memory(self) -> None:
        strategy_memory_service.append_learning_note(
            {
                "type": "autonomous_reflection_test",
                "title": "AI autonomous reflection integration test",
                "takeaways": [
                    self.sentinel,
                    "model-independent memory must survive provider and model switches",
                    "reflections must appear in future AI prompts",
                ],
            }
        )

    def test_memory_context_contains_autonomous_reflection(self) -> None:
        self._seed_memory()

        context = strategy_memory_service.get_model_memory_context("trade_decision")

        self.assertIn(self.sentinel, context)
        self.assertIn("autonomous reflection", context.lower())

    def test_chat_json_injects_memory_and_memory_version(self) -> None:
        self._write_config(selected_model="model-a")
        self._seed_memory()
        calls = []

        def fake_post(*args, **kwargs):
            calls.append(kwargs["json"])
            return FakeResponse('{"decision": "ok"}')

        with patch.object(ai_model_service.requests, "post", side_effect=fake_post):
            parsed, meta = ai_model_service.chat_json(
                "trade_decision",
                "SYSTEM_BASE_PROMPT",
                {"candidates": [{"code": "000001", "name": "Ping An"}]},
                schema_hint='{"decision": "string"}',
            )

        self.assertEqual(parsed, {"decision": "ok"})
        self.assertTrue(meta["used_ai"])
        self.assertEqual(meta["model"], "model-a")
        system_message = calls[0]["messages"][0]["content"]
        user_message = calls[0]["messages"][1]["content"]
        self.assertIn("SYSTEM_BASE_PROMPT", system_message)
        self.assertIn(self.sentinel, system_message)
        self.assertIn("strategy_memory_version", user_message)

    def test_memory_survives_model_switch_for_text_chat(self) -> None:
        self._write_config(selected_model="model-a")
        self._seed_memory()
        self._write_config(selected_model="model-b")
        calls = []

        def fake_post(*args, **kwargs):
            calls.append(kwargs["json"])
            return FakeResponse("memory carried over")

        with patch.object(ai_model_service.requests, "post", side_effect=fake_post):
            answer, meta = ai_model_service.chat_text(
                "deep_analysis",
                "TEXT_SYSTEM_PROMPT",
                "Does the strategy memory still exist?",
                context={"code": "000001"},
            )

        self.assertEqual(answer, "memory carried over")
        self.assertTrue(meta["used_ai"])
        self.assertEqual(meta["model"], "model-b")
        payload = calls[0]
        self.assertEqual(payload["model"], "model-b")
        self.assertIn(self.sentinel, payload["messages"][0]["content"])
        self.assertIn("strategy_memory", payload["messages"][1]["content"])

    def test_risk_verifier_also_receives_memory(self) -> None:
        self._write_config(selected_model="model-a", risk_model="risk-model-a")
        self._seed_memory()
        calls = []

        def fake_post(*args, **kwargs):
            calls.append(kwargs["json"])
            return FakeResponse('{"risk": "pass"}')

        with patch.object(ai_model_service.requests, "post", side_effect=fake_post):
            parsed, meta = ai_model_service.chat_json_with_risk_verifier(
                "RISK_SYSTEM_PROMPT",
                {"code": "000001", "risk": "check"},
                schema_hint='{"risk": "string"}',
            )

        self.assertEqual(parsed, {"risk": "pass"})
        self.assertTrue(meta["used_ai"])
        self.assertEqual(meta["model"], "risk-model-a")
        self.assertEqual(calls[0]["model"], "risk-model-a")
        self.assertIn(self.sentinel, calls[0]["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
