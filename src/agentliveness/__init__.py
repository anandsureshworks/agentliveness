"""agentliveness — a reliability harness for scheduled / autonomous agent systems.

Make silent failure impossible: persist state across runs, prove liveness (not
just freshness), fail loud — and scan for the failure class before it ships.
"""
from .persistent_state import PersistentState, StateVersionError, ENVELOPE_VERSION
from .liveness import LivenessContract, Verdict
from .loud_fail import LoudFail, log_sink, notify_sink, exit_sink
from .audit import audit_source, audit_path, Finding

__all__ = [
    "PersistentState", "StateVersionError", "ENVELOPE_VERSION",
    "LivenessContract", "Verdict",
    "LoudFail", "log_sink", "notify_sink", "exit_sink",
    "audit_source", "audit_path", "Finding",
]
__version__ = "0.4.0"
