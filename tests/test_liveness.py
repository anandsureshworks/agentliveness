"""Liveness tests. The flagship case is fresh-but-dead: a file with a CURRENT
timestamp whose producer emits nothing must be reported degraded — the exact
gap a freshness-only monitor (age < max) misses.
"""
import json
import time


from agentliveness import LivenessContract, PersistentState


def _write(path, payload):
    path.write_text(json.dumps(payload))


def test_fresh_but_empty_is_degraded(tmp_path):
    """THE thesis of Phase 2: the file is brand new (fresh) but the payload is
    empty — a freshness check passes, liveness must FAIL."""
    p = tmp_path / "engine.json"
    _write(p, {"norms": []})            # just written → fresh; but empty
    c = LivenessContract(p, max_age_s=3600,
                         producing=lambda d: bool(d.get("norms")))
    v = c.evaluate()
    assert not v.healthy
    assert v.status == "degraded"
    assert "producing-signal" in v.reason or "EMPTY" in v.reason


def test_fresh_and_producing_is_healthy(tmp_path):
    p = tmp_path / "engine.json"
    _write(p, {"norms": [1, 2, 3]})
    c = LivenessContract(p, max_age_s=3600,
                         producing=lambda d: bool(d.get("norms")))
    v = c.evaluate()
    assert v.healthy and v.status == "healthy"
    assert bool(v) is True              # Verdict is truthy when healthy


def test_stale_is_degraded(tmp_path):
    """A stuck scheduler / dead writer: payload is fine but the file is old."""
    p = tmp_path / "engine.json"
    _write(p, {"norms": [1]})
    # evaluate 'now' far in the future so the file is past max_age
    v = LivenessContract(p, max_age_s=60).evaluate(now=time.time() + 9999)
    assert not v.healthy and "stale" in v.reason


def test_missing_when_warmed_is_degraded(tmp_path):
    v = LivenessContract(tmp_path / "nope.json", max_age_s=60).evaluate()
    assert not v.healthy and "missing" in v.reason


def test_missing_when_unwarmed_is_warming_not_degraded(tmp_path):
    """First boot must not cry wolf — unwarmed + missing = warming, healthy."""
    v = LivenessContract(tmp_path / "nope.json", max_age_s=60,
                         warmed=False).evaluate()
    assert v.healthy and v.status == "warming"


def test_reads_persistentstate_envelope(tmp_path):
    """Liveness understands a PersistentState envelope, not just bare JSON —
    the two primitives compose."""
    p = tmp_path / "state.json"
    PersistentState(p).save({"norms": [1, 2]})     # writes an envelope
    c = LivenessContract(p, max_age_s=3600,
                         producing=lambda d: bool(d.get("norms")))
    assert c.evaluate().healthy


def test_throwing_producing_predicate_fails_loud(tmp_path):
    p = tmp_path / "engine.json"
    _write(p, {"x": 1})
    def boom(_):
        raise KeyError("nope")
    v = LivenessContract(p, max_age_s=3600, producing=boom).evaluate()
    assert not v.healthy and "raised" in v.reason
