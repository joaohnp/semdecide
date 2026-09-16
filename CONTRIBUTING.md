# Contributing

Thanks for helping make semantic decisions easier to use from ordinary developer workflows.

## Development setup

```bash
git clone <your-fork-url>
cd reflex-guard
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

REFLEX supports Python 3.10 and newer. Runtime code should remain dependency-free unless a dependency provides clear security or correctness value that cannot reasonably be implemented with the standard library.

## Principles

1. **Code owns control flow.** Jev supplies typed semantic signals. Local code owns thresholds, routing, and side effects.
2. **Uncertainty stays visible.** Never silently turn a low-confidence result into a definitive answer.
3. **No hidden network behavior.** Commands must document what is sent to the provider and enforce explicit size limits.
4. **Stable machine interfaces.** JSON fields, JSONL behavior, and process exit codes are public API.
5. **No secrets in diagnostics.** API keys and authorization headers must never appear in output, logs, fixtures, or exceptions.
6. **Atomic questions.** Each semantic criterion should test one narrow judgment.

## Making a change

- Open an issue for large behavior or interface changes.
- Add tests for the happy path, failure path, and at least one boundary case.
- Keep live-provider tests opt-in. The default suite must be deterministic and free.
- Update `CHANGELOG.md` for user-visible changes.
- Update the spec or architecture document when changing a public contract.

Run before submitting:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m pip wheel . --no-deps -w dist
```

## Commit style

Use an imperative subject with a clear scope, for example:

```text
feat: add confidence-aware choice routing
fix: reject partial Jev batch responses
 docs: document JSON output schema
```

## Pull requests

A pull request should state:

- the user problem it solves
- public interface changes
- failure modes considered
- tests run and observed results
- any privacy, cost, or compatibility impact
