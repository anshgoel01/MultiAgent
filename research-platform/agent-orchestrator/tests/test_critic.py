import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "agents" / "critic.py"
spec = importlib.util.spec_from_file_location("critic_module", MODULE_PATH)
critic_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = critic_module
spec.loader.exec_module(critic_module)

critic_agent = critic_module.critic_agent
route_after_critic = critic_module.route_after_critic


class CriticAgentTests(unittest.TestCase):
    def test_route_after_critic_retries_until_limit(self):
        self.assertEqual(route_after_critic({"status": "insufficient", "critic_retries": 1}), "requery")
        self.assertEqual(route_after_critic({"status": "insufficient", "critic_retries": 2}), "writer")
        self.assertEqual(route_after_critic({"status": "sufficient", "critic_retries": 5}), "writer")

    def test_critic_agent_parses_verdict(self):
        class FakeLLM:
            def invoke(self, prompt):
                return type("Response", (), {"content": "SUFFICIENT"})()

        with patch.object(critic_module, "llm", FakeLLM()):
            result = critic_agent({"query": "What is AI?", "findings": ["A", "B"], "critic_retries": 0})

        self.assertEqual(result["status"], "sufficient")
        self.assertEqual(result["critic_retries"], 1)

    def test_critic_agent_rejects_insufficient_verdict(self):
        class FakeLLM:
            def invoke(self, prompt):
                return type("Response", (), {"content": "INSUFFICIENT"})()

        with patch.object(critic_module, "llm", FakeLLM()):
            result = critic_agent({"query": "What is AI?", "findings": ["A", "B"], "critic_retries": 0})

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["critic_retries"], 1)


if __name__ == "__main__":
    unittest.main()
