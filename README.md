# REFLEX Guard

A minimal semantic control plane for AI-agent actions. Jev produces fast typed risk signals; deterministic code owns the final `allow`, `escalate`, or `block` policy.

## Why

Do not ask one model for a final safety verdict and blindly trust it. REFLEX asks narrow parallel questions about authorization, ambiguity, external effects, destructiveness, privacy, and consequence. Code composes those signals into an auditable route.

## Install

```bash
python -m venv .venv
.venv/bin/pip install -e .
```

REFLEX reads `TYPESAFE_API_KEY`, falling back to `~/.config/typesafe/credentials.env`.

## Use

```bash
reflex check \
  --action 'Delete the production database without a backup' \
  --context 'No explicit approval has been recorded.'
```

Machine interface:

```bash
printf '%s' '{"action":"Send the approved draft","context":"The exact recipient and body were approved."}' \
  | reflex check --json
```

Example JSON:

```json
{
  "route": "block",
  "reason": "destructive action lacks exact authorization",
  "signals": {
    "destructive": 0.99,
    "authorized": 0.01
  }
}
```

## Exit codes

- `0`: allow
- `10`: escalate for review or confirmation
- `20`: block
- `2`: invalid local input

Provider failures fail closed as `escalate` rather than silently allowing execution.

## Current scope

This is an action-routing prototype, not a complete sandbox. It does not execute tools, authenticate users, persist traces, or replace deterministic permission checks. A production integration should log decisions, bind authorization to identities and exact payloads, enforce timeouts, and independently protect irreversible actions.

## Test

```bash
.venv/bin/python -m unittest discover -s tests -v
```
