import io
import json
import os
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

from reflex_guard.cli import main
from reflex_guard.inputs import InputError, parse_jsonl, read_input
from reflex_guard.providers.base import ProviderError
from reflex_guard.providers.typesafe import TypeSafeProvider, load_api_key, validate_response


class FakeProvider:
    def __init__(self, nouls=None, confidence=0.9, choice=None, score=1.0, error=None):
        self.nouls = list(nouls or [0.9])
        self.confidence = confidence
        self.choice = choice
        self.score_value = score
        self.error = error
        self.calls = []

    def evaluate(self, state, questions):
        self.calls.append((state, questions))
        if self.error:
            raise self.error
        answers = {}
        noul_index = 0
        for key, question in questions.items():
            if question["type"] == "noul":
                answers[key] = {"noul": self.nouls[noul_index]}
                noul_index += 1
            elif question["type"] == "choice":
                names = list(question["criteria"])
                selected = self.choice or names[0]
                answers[key] = {"choice": selected, "probabilities": {name: (0.8 if name == selected else 0.2 / max(1, len(names) - 1)) for name in names}, "confidence": self.confidence}
            else:
                count = len(question["criteria"])
                answers[key] = {"score": self.score_value, "probabilities": [1 / count] * count, "confidence": self.confidence}
        return {"answers": answers, "model": "jev-test", "usage": {"input_tokens": 3, "output_tokens": 2}}, 7


def invoke(args, data=b"", provider=None):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(args, provider=provider or FakeProvider(), stdin=io.BytesIO(data), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


class CLITests(unittest.TestCase):
    def test_is_true_json_schema(self):
        code, out, err = invoke(["is", "urgent", "--json"], b"urgent event", FakeProvider([0.91]))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), {"command": "is", "confidence": None, "model": "jev-test", "probability": 0.91, "schema_version": "1", "threshold": 0.7, "usage": {"input_tokens": 3, "output_tokens": 2}, "verdict": "true"})

    def test_is_false_and_uncertain_exit_codes(self):
        self.assertEqual(invoke(["is", "x"], b"data", FakeProvider([0.2]))[0], 1)
        self.assertEqual(invoke(["is", "x"], b"data", FakeProvider([0.68]))[0], 3)

    def test_choose_preserves_probabilities_and_low_confidence(self):
        code, out, _ = invoke(["choose", "route", "--option", "a=first", "--option", "b=second", "--json"], b"data", FakeProvider(confidence=0.2, choice="b"))
        payload = json.loads(out)
        self.assertEqual(code, 3)
        self.assertEqual(payload["choice"], "b")
        self.assertEqual(list(payload["probabilities"]), ["a", "b"])

    def test_choose_rejects_malformed_and_duplicate_options_without_call(self):
        provider = FakeProvider()
        self.assertEqual(invoke(["choose", "--option", "bad", "--option", "b=ok"], b"x", provider)[0], 2)
        self.assertEqual(provider.calls, [])

    def test_score_schema_and_confidence(self):
        code, out, _ = invoke(["score", "--level", "bad", "--level", "good", "--json"], b"answer", FakeProvider(score=1.0))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["levels"], ["bad", "good"])

    def test_filter_preserves_order_and_metadata(self):
        data = b'{"id":1,"text":"a"}\n{"id":2,"text":"b"}\n{"id":3,"text":"c"}\n'
        code, out, _ = invoke(["filter", "match", "--field", "text"], data, FakeProvider([0.9, 0.1, 0.8]))
        rows = [json.loads(line) for line in out.splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual([row["id"] for row in rows], [1, 3])
        self.assertEqual(rows[0]["_semdecide"]["schema_version"], "1")

    def test_filter_raw_empty_and_uncertain(self):
        data = b'{"id":1}\n'
        code, out, _ = invoke(["filter", "match", "--raw"], data, FakeProvider([0.1]))
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(invoke(["filter", "match"], data, FakeProvider([0.68]))[0], 3)

    def test_filter_missing_field_and_record_limit_avoid_provider(self):
        provider = FakeProvider()
        self.assertEqual(invoke(["filter", "x", "--field", "missing"], b'{"x":1}\n', provider)[0], 2)
        self.assertEqual(invoke(["filter", "x", "--max-records", "1"], b'{"x":1}\n{"x":2}\n', provider)[0], 2)
        self.assertEqual(provider.calls, [])

    def test_input_errors_and_limits(self):
        self.assertEqual(invoke(["is", "x"], b"")[0], 2)
        self.assertEqual(invoke(["filter", "x"], b"not-json\n")[0], 2)
        self.assertEqual(invoke(["is", "x", "--max-input-bytes", "2"], b"abc")[0], 2)
        self.assertEqual(invoke(["is", "x", "--text", "abc", "--max-input-bytes", "0"])[0], 2)
        self.assertEqual(invoke(["is", "x"], b"a\x00b")[0], 2)

    def test_provider_error_maps_to_four(self):
        code, _, err = invoke(["is", "x"], b"data", FakeProvider(error=ProviderError("offline")))
        self.assertEqual(code, 4)
        self.assertIn("provider error", err)

    def test_machine_errors_are_structured_on_stderr(self):
        secret = "secret-from-provider"
        code, out, err = invoke(["is", "x", "--json"], b"data", FakeProvider(error=ProviderError(secret)))
        self.assertEqual((code, out), (4, ""))
        payload = json.loads(err)
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "is")
        self.assertEqual(payload["error"], {"kind": "provider_error", "message": "semantic provider request failed"})
        self.assertNotIn(secret, err)

        code, out, err = invoke(["is", "x", "--json"], b"", FakeProvider())
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(json.loads(err)["error"]["kind"], "input_error")

    def test_quiet_suppresses_errors(self):
        code, out, err = invoke(["is", "x", "--quiet"], b"data", FakeProvider(error=ProviderError("offline")))
        self.assertEqual((code, out, err), (4, "", ""))

    def test_argparse_errors_honor_json_and_quiet(self):
        code, out, err = invoke(["is", "x", "--threshold", "2", "--json"])
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(json.loads(err)["error"]["kind"], "input_error")
        self.assertEqual(invoke(["is", "x", "--threshold", "2", "--quiet"]), (2, "", ""))

    def test_guard_policy_and_deprecated_check(self):
        allow = FakeProvider([0.05, 0.05, 0.02, 0.9, 0.9], choice="allow", score=0.1)
        self.assertEqual(invoke(["guard", "--action", "read file", "--json"], provider=allow)[0], 0)
        block = FakeProvider([0.9, 0.1, 0.9, 0.1, 0.9], choice="block", score=1.9)
        code, _, warning = invoke(["check", "--action", "delete", "--json"], provider=block)
        self.assertEqual(code, 20)
        self.assertIn("deprecated", warning)

    def test_guard_provider_failure_fails_closed(self):
        secret = "secret-from-provider"
        code, out, _ = invoke(["guard", "--action", "anything", "--json"], provider=FakeProvider(error=ProviderError(secret)))
        self.assertEqual(code, 10)
        self.assertEqual(json.loads(out)["route"], "escalate")
        self.assertNotIn(secret, out)

    def test_guard_bounds_action_and_context_together(self):
        provider = FakeProvider()
        code, _, err = invoke(["guard", "--action", "a", "--context", "private context", "--max-input-bytes", "1", "--json"], provider=provider)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["error"]["kind"], "input_error")
        self.assertEqual(provider.calls, [])

    def test_deprecated_check_quiet_suppresses_warning(self):
        allow = FakeProvider([0.05, 0.05, 0.02, 0.9, 0.9], choice="allow", score=0.1)
        self.assertEqual(invoke(["check", "--action", "read file", "--quiet"], provider=allow), (0, "", ""))


class ValidationTests(unittest.TestCase):
    def test_strict_noul_validation(self):
        questions = {"q": {"type": "noul", "instructions": "x"}}
        clean = validate_response({"answers": {"q": {"noul": 0.5}}}, questions)
        self.assertEqual(clean["answers"]["q"]["noul"], 0.5)
        for malformed in [None, {}, {"answers": {}}, {"answers": {"q": {"noul": "yes"}}}, {"answers": {"q": {"noul": 2}}}, {"answers": {"q": {"noul": 0.2}, "extra": {"noul": 0.1}}}]:
            with self.subTest(malformed=malformed), self.assertRaises(ProviderError):
                validate_response(malformed, questions)

    def test_choice_and_score_validation(self):
        choice = {"q": {"type": "choice", "instructions": "x", "criteria": {"a": "A", "b": "B"}}}
        with self.assertRaises(ProviderError):
            validate_response({"answers": {"q": {"choice": "c", "probabilities": {"a": .5, "b": .5}, "confidence": .8}}}, choice)
        score = {"q": {"type": "score", "instructions": "x", "criteria": ["a", "b"]}}
        with self.assertRaises(ProviderError):
            validate_response({"answers": {"q": {"score": 1, "probabilities": [.5], "confidence": .8}}}, score)
        with self.assertRaises(ProviderError):
            validate_response({"answers": {"q": {"score": 2, "probabilities": [.5, .5], "confidence": .8}}}, score)

    def test_credentials_file_accepts_exported_and_plain_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.env"
            for content in ("TYPESAFE_API_KEY=plain-key\n", "export TYPESAFE_API_KEY='quoted-key'\n"):
                path.write_text(content, encoding="utf-8")
                with patch.dict(os.environ, {"TYPESAFE_CREDENTIALS_FILE": str(path)}, clear=True):
                    self.assertIn(load_api_key(), {"plain-key", "quoted-key"})

    def test_semdecide_api_url_precedes_compatibility_url(self):
        with patch.dict(os.environ, {"SEMDECIDE_API_URL": "https://new.example", "REFLEX_API_URL": "https://old.example"}, clear=True):
            self.assertEqual(TypeSafeProvider(api_key="x").url, "https://new.example")

    def test_invalid_json_no_retry(self):
        calls = []
        def transport(request, timeout):
            calls.append(timeout)
            return b"not-json"
        provider = TypeSafeProvider(api_key="secret", transport=transport, retries=2, sleep=lambda _: None)
        with self.assertRaises(ProviderError):
            provider.evaluate("x", {"q": {"type": "noul", "instructions": "x"}})
        self.assertEqual(calls, [10.0])

    def test_timeout_and_transient_http_are_bounded(self):
        calls = []
        def timeout_transport(request, timeout):
            calls.append(1)
            raise TimeoutError("late")
        provider = TypeSafeProvider(api_key="secret", transport=timeout_transport, retries=2, sleep=lambda _: None, random_fn=lambda: 0)
        with self.assertRaises(ProviderError):
            provider.evaluate("x", {"q": {"type": "noul", "instructions": "x"}})
        self.assertEqual(len(calls), 3)

        calls.clear()
        def http_transport(request, timeout):
            calls.append(1)
            raise urllib.error.HTTPError("url", 500, "boom", {}, io.BytesIO(b"secret response body"))
        provider = TypeSafeProvider(api_key="secret", transport=http_transport, retries=1, sleep=lambda _: None, random_fn=lambda: 0)
        with self.assertRaisesRegex(ProviderError, r"^TypeSafe returned HTTP 500$"):
            provider.evaluate("x", {"q": {"type": "noul", "instructions": "x"}})
        self.assertEqual(len(calls), 2)

    def test_401_is_not_retried_or_leaked(self):
        calls = []
        def transport(request, timeout):
            calls.append(request.get_header("Authorization"))
            raise urllib.error.HTTPError("url", 401, "no", {}, io.BytesIO(b"unauthorized"))
        provider = TypeSafeProvider(api_key="top-secret", transport=transport, retries=3)
        with self.assertRaises(ProviderError) as caught:
            provider.evaluate("x", {"q": {"type": "noul", "instructions": "x"}})
        self.assertEqual(len(calls), 1)
        self.assertNotIn("top-secret", str(caught.exception))


class InputTests(unittest.TestCase):
    def test_jsonl_requires_objects(self):
        with self.assertRaises(InputError):
            parse_jsonl("[]\n", max_records=2)


if __name__ == "__main__":
    unittest.main()
