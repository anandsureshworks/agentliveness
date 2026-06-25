# Contributing to agentliveness

Thanks for looking. agentliveness is deliberately **small and dependency-free** —
one capability, done well: make the silent-failure mode of scheduled/autonomous
agents (state that looks alive but resets every run) impossible to ship unseen.

Before opening a PR, please read the scope and the testing philosophy — they're
the whole point.

## Scope (what this is, and isn't)

- **One harness, three composing primitives:** `PersistentState` (restart-safe
  state) → `LivenessContract` (producing, not just fresh) → `LoudFail` (fire once
  per incident, never crash the run).
- **Non-goals:** a full observability platform, a metrics backend, a scheduler, a
  framework. Breadth that doesn't sharpen the thesis — *detect over predict,
  liveness ≠ freshness, fail loud* — will likely be declined, by design.
- **Hard constraints, non-negotiable:**
  - **Zero runtime dependencies** (stdlib only). `dev` extras may add test tools.
  - **Local-first, no secrets, no network.**
  - **Atomic writes** (tmp + `os.replace`) for anything that persists.

## Dev setup

Requires Python ≥ 3.9.

```sh
git clone https://github.com/anandsureshworks/agentliveness.git
cd agentliveness
python -m pip install -e ".[dev]"
pytest
```

## The testing rule (this is the thesis)

The bug this library exists to catch **passes in-process tests** — one long-lived
interpreter hides a counter that resets across real process death. So:

> **Tests for restart/liveness behaviour must exercise the production execution
> model** — spawn real subprocesses that persist, exit, and restart — not
> re-instantiate an object in one interpreter.

See `tests/test_restart.py` for the pattern. A PR that "tests" cross-run state
in a single process will be asked to reproduce the production model instead.

## Pull requests

- Keep them **small and focused** — one change, one reason.
- Include a test that **reproduces the failure** the change prevents or fixes.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Keep the zero-dependency / atomic-write / fail-loud invariants intact.
- Be kind — see [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md).

## Reporting a vulnerability

See [SECURITY.md](./SECURITY.md). Don't open a public issue for security reports.
