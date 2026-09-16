# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog and releases follow semantic versioning.

## [Unreleased]

## [0.2.1] - 2026-09-16

### Fixed

- Replaced premature PyPI-style installation examples with version-pinned GitHub release artifact URLs.

## [0.2.0] - 2026-09-16

### Added

- Product spec for a Unix-native semantic decision CLI backed by TypeSafe Jev.
- Semantic predicate, choice, score, JSONL filter, and agent-guard recipe interfaces.
- Open-source contribution, security, conduct, architecture, and CI foundations.

### Changed

- Renamed the primary product and executable to SemDecide to avoid collision with the Reflex web framework.
- Repositioned the project from a standalone agent action firewall to a general semantic decision primitive for shell pipelines and CI.

## [0.1.0] - 2026-09-16

### Added

- Initial Jev-backed action guard prototype.
- Deterministic allow, escalate, and block policy.
- Machine-readable output and stable guard exit codes.
- Fail-closed provider behavior and credential-file support.
