import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]

INTENT_MODULE_PATH = ROOT / "agents" / "intent_classifier.py"
intent_spec = importlib.util.spec_from_file_location("intent_classifier_module", INTENT_MODULE_PATH)
intent_module = importlib.util.module_from_spec(intent_spec)
sys.modules[intent_spec.name] = intent_module
intent_spec.loader.exec_module(intent_module)

FOLLOWUP_MODULE_PATH = ROOT / "agents" / "followup_answerer.py"
followup_spec = importlib.util.spec_from_file_location("followup_answerer_module", FOLLOWUP_MODULE_PATH)
followup_module = importlib.util.module_from_spec(followup_spec)
sys.modules[followup_spec.name] = followup_module
followup_spec.loader.exec_module(followup_module)


class IntentClassifierTests(unittest.TestCase):
    def test_no_previous_report_returns_new_topic_without_llm(self):
        fake_llm = Mock()
        with patch.object(intent_module, "llm", fake_llm):
            result = intent_module.classify_intent("What changed in AI this year?", None)

        self.assertEqual(result, "NEW_TOPIC")
        fake_llm.invoke.assert_not_called()

    def test_followup_prompt_uses_previous_report(self):
        class FakeLLM:
            def invoke(self, prompt):
                self.prompt = prompt
                return type("Response", (), {"content": "FOLLOWUP"})()

        fake_llm = FakeLLM()
        with patch.object(intent_module, "llm", fake_llm):
            result = intent_module.classify_intent("What about the business impact?", "Earlier summary")

        self.assertEqual(result, "FOLLOWUP")
        self.assertIn("Earlier summary", fake_llm.prompt)


class FollowupAnswererTests(unittest.TestCase):
    def test_followup_answerer_uses_previous_context(self):
        class FakeLLM:
            def invoke(self, prompt):
                self.prompt = prompt
                return type("Response", (), {"content": "Updated answer"})()

        fake_llm = FakeLLM()
        with patch.object(followup_module, "llm", fake_llm):
            result = followup_module.followup_answerer(
                query="What changed?",
                previous_report="Earlier summary",
                history=[{"role": "user", "content": "First question"}],
            )

        self.assertEqual(result, "Updated answer")
        self.assertIn("Earlier summary", fake_llm.prompt)
        self.assertIn("First question", fake_llm.prompt)


if __name__ == "__main__":
    unittest.main()
