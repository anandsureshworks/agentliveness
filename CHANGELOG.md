# Changelog

All notable changes to agentliveness are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); this project
uses semantic versioning.

## [Unreleased]
### Security
- **Static security analysis (ruff flake8-bandit `S`)** — CI's `ruff check` now
  runs the bandit ruleset, scanning for common vulnerability patterns on every
  push/PR. Clean: the one intentional `subprocess` call (the loud_fail macOS
  notification sink) and the last-resort sink-guard swallow carry targeted,
  justified `noqa`s; tests keep bare asserts + real-subprocess spawns. Satisfies
  OpenSSF `static_analysis_common_vulnerabilities`.

### Changed
- **Docs/site branding** — the landing page (`docs/`) now carries the woven AS
  brand mark as its favicon and masthead, retiring the `>_` terminal glyph. Ties
  the product page into the `anandsureshworks` family mark. No library changes.

## [0.4.0] — 2026-06-24
### Added
- **Phase 4 — `agentliveness audit`**: a static scanner (stdlib `ast`, zero deps) that
  flags the never-restored-accumulator class — an attribute seeded as an empty
  counter/list/dict/set in `__init__`, accumulated across calls, but never
  restored from persistence. The bug the whole library exists to catch, found
  *before* it ships. Ships as the `agentliveness` CLI (`agentliveness audit <path>`, `--json`,
  `--exit-zero`) and a Python API (`audit_path`, `audit_source`, `Finding`).
- 8 tests: flags counter/list/set/dict-subscript accumulators; stays quiet when
  the attribute is restored (json / `PersistentState`) or never accumulated;
  swallows syntax errors; scans a directory. Dogfooded — clean on its own source.

### Why
Detection beats prediction — so detect the failure class *statically*, before a
scheduler ever runs the code. Also the empirical instrument for an outward scan
of open-source agent frameworks.

## [0.3.0] — 2026-06-03
### Added
- `LoudFail` — the response channel. Routes a verdict (or any healthy/reason) to
  sinks (`log_sink`, `notify_sink`, `exit_sink`) **once per state transition** —
  silent while unchanged (no alert fatigue), fires on the down-edge and the
  recovery-edge. A sink that raises is **swallowed**, never propagated: the
  notifier can never crash the run it protects. Incident state
  persisted via `PersistentState`, so "new incident" holds across scheduled
  processes. `notify_sink` uses the env-var + static-AppleScript pattern.
- 7 tests incl. fires-once-not-every-tick, recovery edge, sink-failure-swallowed,
  cross-process incident state, and end-to-end compose with `LivenessContract`.
  Delete-the-fix verified (un-guarded sink crashes; 5 down-ticks would fire 5×).

### Why
Detection without response is an unseen incident. Completes the
core triad: persist (P1) → detect (P2) → respond (P3).

## [0.2.0] — 2026-06-03
### Added
- `LivenessContract` — proves a subsystem is still *producing*, not merely that
  its output file is fresh. Bundles four invariants (exists · fresh · non-empty ·
  caller `producing` predicate) into a single `Verdict` (healthy / degraded /
  warming + reason). Warmup-honest: an unwarmed subsystem reports `warming`, not
  `degraded`, so first boot does not cry wolf. Reads a `PersistentState` envelope
  or bare JSON — the primitives compose.
- 7 liveness tests, including the flagship fresh-but-dead case: a freshness-only
  monitor calls a fresh-but-empty file healthy; `LivenessContract` correctly
  reports degraded.

### Why
Productizes a real production failure: a current `generated_at` over a dead
producer is the "fresh but dead" disconnected-sensor failure. Freshness ≠ liveness.

## [0.1.0] — 2026-06-03
### Added
- `PersistentState` — restart-safe state for scheduled/autonomous agents. Atomic
  writes (tmp + `os.replace`, fsync), a versioned envelope with `generated_at`,
  and load-or-default recovery (missing/corrupt file recovers as first run).
- The flagship subprocess restart test: spawns real processes that increment,
  save, and exit, proving the counter accumulates `0→1→2→3` across genuine
  process death — the production (launchd/cron) execution model, not in-process
  reuse. Delete-the-fix verified.
- MIT license, thesis-first README.

### Why
Productizes a real production failure: in-memory cross-run state silently
resets to its initial value every scheduled run, invisible to in-process tests.
