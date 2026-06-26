"""Tests for `agentliveness audit` — the never-restored-accumulator scanner.

Note: unlike test_restart.py, these are ordinary in-process unit tests. The
scanner is *pure static analysis* (no runtime/scheduler behaviour), so feeding it
source and asserting on findings is the production model. The subprocess rule in
CONTRIBUTING applies to restart/liveness behaviour, not to static analysis.
"""

from agentliveness.audit import audit_source, audit_path


def _attrs(findings):
    return {f.attr for f in findings}


def test_flags_counter_never_restored():
    src = """
class Engine:
    def __init__(self):
        self.count = 0          # seeded fresh
    def tick(self):
        self.count += 1         # accumulated, never loaded from disk
"""
    f = audit_source(src)
    assert _attrs(f) == {"count"}
    assert f[0].kind == "counter"
    assert f[0].cls == "Engine"
    assert f[0].accumulated_at        # the accumulation site(s) were recorded


def test_flags_list_and_set_accumulators():
    src = """
class Agent:
    def __init__(self):
        self.seen = []
        self.ids = set()
    def see(self, x):
        self.seen.append(x)
        self.ids.add(x)
"""
    assert _attrs(audit_source(src)) == {"seen", "ids"}


def test_flags_dict_subscript_accumulation():
    src = """
class Tally:
    def __init__(self):
        self.by_key = {}
    def bump(self, k):
        self.by_key[k] = self.by_key.get(k, 0) + 1
"""
    assert _attrs(audit_source(src)) == {"by_key"}


def test_clean_when_restored_from_json():
    src = """
import json
class Engine:
    def __init__(self, path):
        self.count = 0
        self.count = json.load(open(path))["count"]   # restored
    def tick(self):
        self.count += 1
"""
    assert audit_source(src) == []


def test_clean_when_restored_from_persistentstate():
    src = """
from agentliveness import PersistentState
class Engine:
    def __init__(self):
        self.total = 0
        self.state = PersistentState("~/.e.json", default={"total": 0})
        self.total = self.state.load()["total"]
    def add(self, n):
        self.total += n
"""
    assert audit_source(src) == []


def test_no_flag_for_non_accumulated_seed():
    # a threshold/config seeded at 0 but never grown is not the bug
    src = """
class Engine:
    def __init__(self):
        self.threshold = 0
        self.retries = 0
    def run(self):
        if self.threshold:
            pass
"""
    assert audit_source(src) == []


def test_syntax_error_is_swallowed_not_raised():
    assert audit_source("def (:\n") == []


def test_audit_path_scans_a_directory(tmp_path):
    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "buggy.py").write_text(
        "class C:\n    def __init__(self):\n        self.n = 0\n    def go(self):\n        self.n += 1\n"
    )
    findings = audit_path(tmp_path)
    assert len(findings) == 1
    assert findings[0].attr == "n"
    assert findings[0].file.endswith("buggy.py")
