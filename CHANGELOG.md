# Changelog

## Unreleased

- Added a complete Chinese script style guide for topic-first and footage-first projects.
- Added a strict Script Writer Agent prompt with validated inputs, evidence states, six-file outputs, and recording-readiness gates.
- Added a film-first task mode for fixed-duration movie sources, cast/character verification, spoiler policy, and limited supplementary web assets.
- Added the `ORIGINAL_FILM` audio mode for retained synchronized film audio.
- Added a non-overwriting `film-init` command that fingerprints available source media and scaffolds blocked-safe film project outputs.
- Added a machine-readable long-form movie style profile derived from a legacy script without reusing its lost timecodes, unverified facts, or asset rights.
- Added human insight cards and `film-insights-validate` to separate fact claims, interpretations, editorial directions, and unresolved questions.
- Added `film-draft` in explicit `PREPARE_ONLY` mode to validate film inputs and build a traceable, self-contained model request package without claiming a draft was generated.
- Added provider-neutral `film-generate` with an optional OpenAI Responses API adapter, offline response-file mode, strict six-file cross-validation, generation receipts, and atomic non-overwriting output.
- Added a DeepSeek OpenAI-compatible Chat Completions provider with isolated credentials, explicit V4 model validation, thinking controls, and incomplete-response rejection.

## 0.1.0

- Added recursive video inventory with duplicate part detection.
- Added compact project overview contact sheets.
- Added conservative single-video technical preflight.
- Added optional local Whisper transcription.
- Added safe hard-link, symlink, and copy consolidation modes.
- Added editorial audio-mode vocabulary.
- Added CLI, tests, documentation, and GitHub Actions.
