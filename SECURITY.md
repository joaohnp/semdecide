# Security Policy

## Supported versions

Until the first stable release, security fixes are applied to the latest release only.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose credentials, private input, or unsafe execution behavior. Use GitHub private vulnerability reporting once the repository is published. Before publication, contact the maintainer privately.

Include:

- affected version or commit
- reproduction steps
- impact and realistic attack path
- whether a TypeSafe API key or submitted content can be exposed
- any suggested mitigation

## Security boundaries

This project sends selected input to the configured TypeSafe Jev API. Users must treat that as an external data-processing boundary.

This project does not:

- execute shell commands or agent tools
- replace authentication or deterministic authorization
- sandbox untrusted code
- prove that a semantic judgment is correct
- make low-confidence results safe to automate

Callers remain responsible for enforcing permissions and protecting irreversible operations independently.

## Credential handling

- Prefer `TYPESAFE_API_KEY` in the process environment or a mode-600 credentials file.
- Never pass API keys as command-line arguments.
- Never commit real credentials or captured authorization headers.
- Rotate any key pasted into chat, logs, issues, or terminal recordings.
