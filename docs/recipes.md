# Primitives, dynamic requests, and recipes

SemDecide separates three concerns:

1. **Jev primitives:** Noul, Choice, and Score, with typed question and answer models.
2. **Caller-owned questions:** instructions, names, and criteria supplied by a person, script, or agent.
3. **Application policy:** what to do with answers. This belongs to the caller or an optional recipe, never to the primitive evaluation layer.

No recipe is required. `is`, `choose`, `score`, and `filter` remain available with their existing output and exit-code contracts.

## Python API

```python
from reflex_guard import ChoiceQuestion, NoulAnswer, NoulQuestion, evaluate

result = evaluate(
    state={"ticket": "I was charged twice"},
    questions={
        "urgent": NoulQuestion(
            instructions="Does this ticket require immediate attention?",
        ),
        "department": ChoiceQuestion(
            instructions="Which department should handle this ticket?",
            criteria={"billing": "Payments and invoices", "support": "Product problems"},
        ),
    },
)

urgent = result.answers["urgent"]
assert isinstance(urgent, NoulAnswer)
print(urgent.noul)
print(result.usage.input_tokens)
```

The default evaluator is OpenRouter and uses the caller's exported environment variables. The Python API does **not** implicitly load `.env`. To use TypeSafe or a test double, pass an evaluator callable:

```python
from reflex_guard.providers.typesafe import TypeSafeProvider

result = evaluate(
    state="Some input",
    questions={"urgent": NoulQuestion(instructions="Is this urgent?")},
    evaluator=TypeSafeProvider(timeout=10, retries=2).evaluate,
)
```

The callable accepts `(state, questions)` and returns `(response_dict, latency_ms)`. Its response is validated even if it is an injected evaluator rather than a built-in adapter.

### Validation and results

- Question definitions are strict Pydantic models with no unknown fields.
- Names, instructions, and criteria must contain non-whitespace text.
- Choice requires 2–255 named options; Score requires 2–255 ordered levels.
- State must be JSON-compatible and numeric values must be finite.
- Every requested question must have exactly one answer; unexpected answers are rejected.
- Probabilities and confidence are in `[0, 1]`. Probability distributions retain the existing sum tolerance of `0.02`.
- Selected choices must exist in their question; score distributions and bounds must match their rubric.
- The returned `EvaluationResult` contains `answers`, `model`, `usage`, and `latency_ms`.
- Answers are `NoulAnswer` (`noul`), `ChoiceAnswer` (`choice`, `probabilities`, `confidence`), or `ScoreAnswer` (`score`, `probabilities`, `confidence`). Score probability tuples serialize to JSON arrays.

Invalid local definitions raise Pydantic `ValidationError` before an evaluator is called. Invalid provider responses raise `ProviderError`. Request definitions are revalidated on evaluation, including nested models whose mutable containers may have changed since construction.

Models are frozen against field reassignment, not deeply immutable. Their JSON Schema is available through `model_json_schema()`.

## Dynamic CLI requests

```bash
semdecide evaluate --request examples/evaluation-request.json
cat examples/evaluation-request.json | semdecide evaluate --request -
```

`--request -` (stdin) is the default. The document contains `state`, `questions`, and an optional `schema_version` of `"1"`. Each question must include its `type`: `noul`, `choice`, or `score`. See the example file for a complete request.

An agent can construct a request on the fly. It does not need to install a recipe or generate Python. Discover the exact accepted schema without contacting a provider:

```bash
semdecide evaluate --schema
```

Output is JSON by default (`--json` is accepted for consistency):

```json
{
  "schema_version": "1",
  "command": "evaluate",
  "answers": {"urgent": {"noul": 0.12}},
  "model": "example-model",
  "usage": {"input_tokens": 20, "output_tokens": 3},
  "latency_ms": 50
}
```

Exit `0` means evaluation succeeded, **not** that any semantic proposition was true. There is no automatic threshold or uncertainty policy in this command. Exit `2` means invalid input; exit `4` means provider failure. Failures are structured JSON on stderr, with no partial output on stdout. `--quiet` suppresses both streams. Provider details and Pydantic input values are not included in CLI diagnostics.

`--provider`, `--timeout`, `--retries`, and `--max-input-bytes` work as on existing commands. OpenRouter's single-attempt behavior and missing-environment-variable behavior remain unchanged. CLI byte limits apply to the complete request document; Python callers own their input-size limits.

## Declarative recipes

A JSON recipe is a reusable **question set**, without embedded input or executable code:

```json
{
  "schema_version": "1",
  "name": "ticket-triage",
  "description": "Evaluate a ticket for caller-owned routing",
  "questions": {
    "urgent": {
      "type": "noul",
      "instructions": "Does this ticket require immediate attention?"
    }
  }
}
```

Run the full example:

```bash
semdecide recipe run examples/ticket-triage.json --text 'I was charged twice'
printf '%s' '{"ticket":"I was charged twice"}' \
  | semdecide recipe run examples/ticket-triage.json --state-json
semdecide recipe schema
```

Input defaults to text from stdin. `--text` and `--file` select other input sources; `--state-json` explicitly decodes any JSON value instead of treating the input as text. There is no implicit JSON guessing.

JSON recipe output and exit behavior match `evaluate`, with `command: "recipe"` and an additional `recipe` field containing the recipe's declared name. `--max-input-bytes` bounds each of the recipe definition and input separately. Recipe definitions are validated before input evaluation or any provider call.

### Project-local and user-wide recipes

You can always pass an explicit JSON file path. To invoke a recipe by name, place its definition at either:

1. `.semdecide/recipes/NAME.json` relative to the current working directory.
2. `$XDG_CONFIG_HOME/semdecide/recipes/NAME.json`, defaulting to `~/.config/semdecide/recipes/NAME.json`.

For example:

```bash
mkdir -p .semdecide/recipes
cp examples/ticket-triage.json .semdecide/recipes/ticket-triage.json
semdecide recipe run ticket-triage --text 'I was charged twice'
```

Project-local names take precedence over user-wide names. Paths ending in `.json` or containing a path separator are treated as explicit paths. `guard` is reserved for the built-in recipe; a JSON file called `guard.json` can still be selected explicitly. There is no automatic discovery or execution of Python plugins, and no installation command is required.

Review recipe instructions before using them: although JSON recipes cannot execute local code, they control the questions sent to the provider. Input still leaves the machine for the selected provider.

## The built-in guard recipe

```bash
semdecide recipe run guard --action 'Read the README' --context 'The user requested it'
# Existing interface remains available:
semdecide guard --action 'Read the README' --context 'The user requested it' --json
```

The recipe form defaults to JSON. The existing `guard` command retains its human-readable default. Both accept an action/context JSON object on stdin and preserve route exit codes: allow `0`, escalate `10`, block `20`. Invalid local input is `2`; handled provider failures escalate. The deprecated `check` alias remains available.

Guard's prompts, thresholds, result types, and policy live in `reflex_guard.recipes.guard`. The primitive evaluator does not import or know about them. Guard calls the same public `evaluate()` API as an external application.

`reflex_guard.Decision`, `reflex_guard.decide`, and the legacy `reflex_guard.client` API remain available for compatibility. Import guard policy functions directly from `reflex_guard.recipes.guard`; the former `reflex_guard.policy` module has been removed. Legacy guard model imports are resolved lazily so importing the core does not load the recipe.

## Custom interpretation in Python

JSON recipes deliberately do not include a rule language or executable hooks. For custom interpretation, compose the public API in your own Python application:

```python
from reflex_guard import NoulAnswer
from reflex_guard.recipes import load_recipe

result = load_recipe("examples/ticket-triage.json").run("Our production system is down")
urgent = result.answers["urgent"]
assert isinstance(urgent, NoulAnswer)
needs_review = urgent.noul >= 0.8  # Your policy, not a Jev default.
```

For a larger application, package this logic as your own module or CLI, just as guard composes questions and deterministic policy. Installing arbitrary executable recipe plugins into SemDecide is intentionally outside this initial interface.
