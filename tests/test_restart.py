"""The flagship test: state survives genuine PROCESS DEATH, not in-memory reuse.

This is the whole thesis. The bug PersistentState exists to prevent was
invisible to in-process tests precisely because re-instantiating an object in the
same interpreter does NOT reproduce the scheduler's "fresh process every run"
model. So this test spawns a real ``python`` subprocess that increments and saves,
lets it EXIT, then spawns another — proving the counter accumulates 0→1→2 across
process boundaries instead of resetting.

If you build only one test well, build this one.
"""
import json
import subprocess
import sys
from pathlib import Path

# A tiny program that loads the counter, increments, saves, prints it, exits.
# Run as a separate process so each invocation is a genuine fresh interpreter —
# the launchd/cron model, not an in-process loop.
_WORKER = """
import sys
sys.path.insert(0, {src!r})
from agentliveness import PersistentState
st = PersistentState({path!r}, default={{"runs": 0}})
data = st.load()
data["runs"] += 1
st.save(data)
print(data["runs"])
"""

SRC = str(Path(__file__).resolve().parent.parent / "src")


def _run_once(state_path: Path) -> int:
    """Spawn a fresh process that does one increment; return the new count."""
    prog = _WORKER.format(src=SRC, path=str(state_path))
    result = subprocess.run(
        [sys.executable, "-c", prog],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"worker failed: {result.stderr}"
    return int(result.stdout.strip())


def test_counter_survives_process_death(tmp_path):
    """0 → 1 → 2 → 3 across four SEPARATE processes. The bug would show as the
    counter stuck at 1 (every fresh process resets to default then +1)."""
    state = tmp_path / "counter-state.json"
    counts = [_run_once(state) for _ in range(4)]
    assert counts == [1, 2, 3, 4], (
        f"counter did not persist across processes: {counts} "
        f"(stuck/reset means in-memory-only state — the bug)"
    )


def test_envelope_has_version_and_timestamp(tmp_path):
    """Persisted file is a versioned envelope with generated_at — so schema
    drift is detectable and staleness is checkable."""
    state = tmp_path / "s.json"
    _run_once(state)
    env = json.loads(state.read_text())
    assert env["__envelope__"] is True
    assert env["version"] == 1
    assert "generated_at" in env and env["generated_at"].endswith("+00:00")
    assert env["payload"]["runs"] == 1


def test_corrupt_file_recovers_as_first_run(tmp_path):
    """A half-written / garbage file must not crash the engine — it loads as the
    default (recovery == first run), then the next save heals it."""
    from agentliveness import PersistentState
    state = tmp_path / "corrupt.json"
    state.write_text("{ this is not valid json")
    st = PersistentState(state, default={"runs": 0})
    assert st.load() == {"runs": 0}          # no raise
    st.save({"runs": 99})
    assert st.load() == {"runs": 99}          # healed


def test_newer_version_fails_loud(tmp_path):
    """A file written by a NEWER library version must raise, never silently
    mis-parse."""
    import pytest
    from agentliveness import PersistentState, StateVersionError
    state = tmp_path / "future.json"
    state.write_text(json.dumps({
        "__envelope__": True, "version": 999,
        "generated_at": "2026-01-01T00:00:00+00:00", "payload": {"x": 1},
    }))
    st = PersistentState(state)
    with pytest.raises(StateVersionError):
        st.load()
