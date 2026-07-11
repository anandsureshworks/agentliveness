# agentliveness

[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13574/badge)](https://www.bestpractices.dev/projects/13574)

**Autonomous AI systems fail silently — fresh output over a dead engine. Predict less, detect more.**

A small, dependency-free reliability harness for scheduled / autonomous agent
systems. It makes the failure mode that birthed it impossible to ship silently:
state that looks alive but resets every run.

## The failure it prevents

Under a scheduler (launchd, cron, k8s CronJob) **every run is a fresh process.**
Any counter or accumulator held only in memory — initialized in `__init__`, never
restored from disk — silently resets to its starting value on every run. The code
reads correctly. In-process tests pass (one long-lived interpreter hides the bug).
In production it is dead, and nothing tells you.

This is real: a network monitor's adaptive-cadence counter was always `0` at
decision time because each scheduled process started fresh, so the adaptive
behaviour never engaged — invisible for weeks behind green tests and a fresh
timestamp.

## Phase 1 — `PersistentState`

Restart-safe state, durable by construction:

```python
from agentliveness import PersistentState

st = PersistentState("~/.myengine-state.json", default={"runs": 0})
data = st.load()
data["runs"] += 1
st.save(data)        # atomic; survives crash and process death
```

- **Atomic writes** (tmp + `os.replace`) — a crash mid-save never leaves a torn
  file that loads as garbage but looks fine.
- **Versioned envelope + `generated_at`** — schema drift fails loud; staleness is
  checkable.
- **Load-or-default** — a missing or corrupt file recovers as "first run" instead
  of crashing the engine.

## The test that is the thesis

`tests/test_restart.py` does not re-instantiate an object in one interpreter — it
spawns **real subprocesses** that increment, save, and exit, proving the counter
accumulates `0→1→2→3` across genuine process death. A test that runs in-process
would pass even with the bug; this one reproduces the production execution model.

```
pytest
```

## Phase 2 — `LivenessContract`

Freshness asks "was this written recently?" Liveness asks "is the thing that
writes it actually working?" — strictly stronger. A fresh file over a dead
producer passes a freshness check and fails a liveness contract.

```python
from agentliveness import LivenessContract

c = LivenessContract(
    path="~/.myengine.json",
    max_age_s=2 * 3600,
    producing=lambda payload: bool(payload.get("norms")),  # the 'actually working' signal
)
v = c.evaluate()
if not v.healthy:
    alert(v.reason)        # e.g. "fresh but EMPTY — producer emits nothing"
```

Bundles four invariants — **exists · fresh · non-empty · producing** — into one
verdict. A freshness-only monitor calls a fresh-but-empty file healthy; this
catches it. Warmup-honest: an unwarmed subsystem reports `warming`, not
`degraded`, so first boot does not cry wolf. Reads a `PersistentState` envelope
or bare JSON — the two primitives compose.

## Phase 3 — `LoudFail`

Detection without a response channel is an incident no one sees. `LoudFail`
routes a verdict to sinks (log / macOS notification / exit code) — but only on a
**state transition**, so a scheduled check that is still-down stays silent
instead of training you to mute it. And a sink that throws (a broken notifier) is
**swallowed**: it can never crash the run it is protecting.

```python
from agentliveness import LoudFail, log_sink, notify_sink

lf = LoudFail("my-agent", "~/.my-agent-loudfail.json",
              sinks=[log_sink(), notify_sink()])
lf.report(contract.evaluate())   # fires once on down-edge + once on recovery; never raises
```

Incident state is persisted (via `PersistentState`), so "new incident" is judged
across scheduled processes — the three primitives compose into one harness.

## Phase 4 — `agentliveness audit`

Catch the bug **before** it ships. A static scan (stdlib `ast` only) that flags
the never-restored-accumulator class in any agent repo: an attribute seeded as an
empty counter / list / dict / set in `__init__`, grown across calls, but never
restored from disk — alive in a long-lived process, silently reset every run
under a scheduler.

```sh
agentliveness audit path/to/agent           # scan a file or directory
agentliveness audit . --json                # machine-readable (for an empirical scan)
agentliveness audit . --exit-zero           # report only; don't fail CI
```

```
⚠ engine.py:3  AdaptiveMonitor.consecutive_quiet  (counter)
  self.consecutive_quiet is seeded as an empty counter in __init__ and
  accumulated (line 6), but never restored from persistence. Under a scheduler
  every run is a fresh process, so it resets to its seed value on every run.
```

Exit code is non-zero when findings exist, so it gates CI. It's **advisory** —
each finding is a candidate to either restore (`PersistentState`) or confirm
intentionally per-run. It is also a Python API: `from agentliveness import audit_path`.

## Roadmap

- **Phase 1:** `PersistentState` + the subprocess restart test. ✅
- **Phase 2:** `LivenessContract` — producing, not just fresh. ✅
- **Phase 3:** `LoudFail` — fire once per incident, never crash the run. ✅
- **Phase 4:** `agentliveness audit` — static scan for the failure class in any repo. ✅

MIT licensed.
