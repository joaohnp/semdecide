import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reflex_guard.client import ReflexAPIError, load_api_key
from reflex_guard.policy import decide, provider_failure


def answers(**overrides):
    values = {
        "destructive": {"noul": 0.05},
        "external_side_effect": {"noul": 0.05},
        "secret_exposure": {"noul": 0.02},
        "authorized": {"noul": 0.90},
        "intent_clear": {"noul": 0.90},
        "consequence": {"score": 0.10},
        "advisory_route": {"choice": "allow", "confidence": 0.9},
    }
    for key, value in overrides.items():
        field = "score" if key == "consequence" else "noul"
        values[key] = {field: value}
    return values


class PolicyTests(unittest.TestCase):
    def test_allows_authorized_low_risk_action(self):
        self.assertEqual(decide(answers()).route, "allow")

    def test_blocks_secret_exposure(self):
        self.assertEqual(decide(answers(secret_exposure=0.98, authorized=0.1)).route, "block")

    def test_blocks_unauthorized_severe_action(self):
        self.assertEqual(decide(answers(consequence=1.9, authorized=0.1)).route, "block")

    def test_escalates_external_action_without_exact_authorization(self):
        self.assertEqual(decide(answers(external_side_effect=0.95, authorized=0.4)).route, "escalate")

    def test_escalates_ambiguous_scope(self):
        self.assertEqual(decide(answers(intent_clear=0.2, authorized=0.1, consequence=0.8)).route, "escalate")

    def test_provider_failure_fails_closed(self):
        self.assertEqual(provider_failure("offline").route, "escalate")


class CredentialTests(unittest.TestCase):
    def test_environment_key_wins(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "env-key"}, clear=True):
            self.assertEqual(load_api_key(), "env-key")

    def test_loads_shell_quoted_credentials_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.env"
            path.write_text("export TYPESAFE_API_KEY='file-key'\n")
            with patch.dict(os.environ, {"TYPESAFE_CREDENTIALS_FILE": str(path)}, clear=True):
                self.assertEqual(load_api_key(), "file-key")

    def test_missing_credentials_fail(self):
        with patch.dict(os.environ, {"TYPESAFE_CREDENTIALS_FILE": "/missing/reflex.env"}, clear=True):
            with self.assertRaises(ReflexAPIError):
                load_api_key()


if __name__ == "__main__":
    unittest.main()
