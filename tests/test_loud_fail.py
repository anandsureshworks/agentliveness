"""LoudFail tests. The load-bearing cases: (1) fire once per NEW incident, not
every tick (no alert fatigue); (2) a sink that raises must NEVER crash the run
it protects; (3) composes with LivenessContract.
"""
from agentliveness import (
    LoudFail, LivenessContract, exit_sink,
)


def _recorder():
    """A sink that records every (event, name, reason) it receives."""
    events = []
    def sink(event, name, reason):
        events.append((event, reason))
    return events, sink


def test_fires_once_per_incident_not_every_tick(tmp_path):
    events, sink = _recorder()
    lf = LoudFail("eng", str(tmp_path / "lf.json"), sinks=[sink])
    # four consecutive DOWN reports (e.g. a watchdog ticking every 5 min)
    assert lf.report(False) == "down"      # down-edge: fires
    assert lf.report(False) == "none"      # still down: silent
    assert lf.report(False) == "none"
    assert lf.report(False) == "none"
    assert [e[0] for e in events] == ["down"], "must fire exactly once on the down-edge"


def test_recovery_edge_fires(tmp_path):
    events, sink = _recorder()
    lf = LoudFail("eng", str(tmp_path / "lf.json"), sinks=[sink])
    lf.report(False)                       # down
    assert lf.report(True) == "recovered"  # up-edge: fires
    assert lf.report(True) == "none"       # still up: silent
    assert [e[0] for e in events] == ["down", "recovered"]


def test_incident_state_survives_across_instances(tmp_path):
    """'New incident' must be judged across scheduled PROCESSES, so the state is
    persisted — a fresh LoudFail pointed at the same file does not re-alert a
    still-down engine."""
    path = str(tmp_path / "lf.json")
    events1, s1 = _recorder()
    LoudFail("eng", path, sinks=[s1]).report(False)        # down-edge fires
    events2, s2 = _recorder()
    second = LoudFail("eng", path, sinks=[s2])             # brand new instance
    assert second.report(False) == "none", "still-down across processes must be silent"
    assert events2 == []


def test_sink_that_raises_never_crashes_the_run(tmp_path):
    """A notifier that throws (an osascript-class break) must be swallowed —
    the protected engine keeps running."""
    def boom(event, name, reason):
        raise RuntimeError("notification channel exploded")
    events, good = _recorder()
    lf = LoudFail("eng", str(tmp_path / "lf.json"), sinks=[boom, good])
    # report must NOT raise, and the GOOD sink must still fire despite boom first
    event = lf.report(False)
    assert event == "down"
    assert events == [("down", "unhealthy")], "good sink still ran after boom raised"
    assert lf.sink_errors and "exploded" in lf.sink_errors[0]


def test_exit_sink_records_code_without_exiting(tmp_path):
    """exit_sink signals a non-zero code via pending_exit instead of calling
    sys.exit inside report — the caller decides when to exit."""
    lf = LoudFail("eng", str(tmp_path / "lf.json"), sinks=[exit_sink(3)])
    assert lf.report(False) == "down"
    assert lf.pending_exit == 3            # recorded, run not killed mid-report


def test_composes_with_liveness_contract(tmp_path):
    """End-to-end: a fresh-but-empty file -> LivenessContract degraded ->
    LoudFail fires down once."""
    import json
    out = tmp_path / "engine.json"
    out.write_text(json.dumps({"norms": []}))      # fresh but empty
    contract = LivenessContract(out, max_age_s=3600,
                                producing=lambda d: bool(d.get("norms")))
    events, sink = _recorder()
    lf = LoudFail("engine", str(tmp_path / "lf.json"), sinks=[sink])
    v = contract.evaluate()
    assert not v.healthy
    assert lf.report(v) == "down"
    assert events[0][0] == "down" and "EMPTY" in events[0][1] or "producing" in events[0][1]


def test_default_log_sink_is_used_when_none_given(tmp_path, capsys):
    lf = LoudFail("eng", str(tmp_path / "lf.json"))   # no sinks -> default log_sink
    lf.report(False)
    err = capsys.readouterr().err
    assert "[loudfail] eng DOWN" in err
