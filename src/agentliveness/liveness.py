"""LivenessContract — prove a subsystem is still PRODUCING, not just fresh.

The failure this exists for: a data file can carry a perfectly current
``generated_at`` while the subsystem that writes it is dead or stuck. Freshness
monitoring (age < max) passes; the producer has actually been emitting empty /
stuck / degraded output for weeks. (The real case: a ``baseline_not_ready``
diff sat behind a fresh timestamp — the file was new every cycle, the analysis
inside it never advanced. The disconnected-sensor shape.)

Freshness answers "was this written recently?" Liveness answers "is the thing
that writes it actually working?" — a strictly stronger question. A
LivenessContract bundles the invariants that, together, mean *producing*:

  * **exists** — the output is there at all;
  * **fresh** — younger than ``max_age_s`` (a stuck scheduler is caught here);
  * **non-empty** — the payload is not the empty/degraded shape (a running
    process emitting nothing is caught here, NOT by freshness);
  * **producing** — an optional caller-supplied predicate over the payload
    (e.g. "norms is non-empty", "diff != 'baseline_not_ready'") for the
    domain-specific "actually working" signal.

Warmup honesty: a contract may be ``warmed=False`` until the producer has had a
chance to run once. An unwarmed subsystem reports ``warming`` (not ``degraded``),
so first-boot does not cry wolf and train the operator to mute the alarm.

Usage::

    c = LivenessContract(
        path="~/.myengine.json",
        max_age_s=2 * 3600,
        producing=lambda payload: bool(payload.get("norms")),
    )
    v = c.evaluate()
    if not v.healthy:
        alert(v.reason)        # loud — see Phase 3 LoudFail
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class Verdict:
    """Result of evaluating a contract. ``healthy`` is the single bit a caller
    gates on; ``status`` and ``reason`` explain it for humans/logs."""
    healthy: bool
    status: str          # "healthy" | "degraded" | "warming"
    reason: str
    age_s: float | None = None

    def __bool__(self) -> bool:  # truthy iff healthy — `if contract.evaluate():`
        return self.healthy


def _payload_of(raw_text: str) -> Any:
    """Unwrap a PersistentState envelope if present, else return parsed JSON."""
    obj = json.loads(raw_text)
    if isinstance(obj, dict) and obj.get("__envelope__") and "payload" in obj:
        return obj["payload"]
    return obj


def _is_empty(payload: Any) -> bool:
    """Empty/degraded shape: None, or an empty container. A scalar (int/str/bool)
    is considered non-empty — the caller's `producing` predicate handles nuance."""
    if payload is None:
        return True
    if isinstance(payload, (dict, list, str, tuple, set)):
        return len(payload) == 0
    return False


class LivenessContract:
    """Declare what 'this subsystem is alive' means, then evaluate it."""

    def __init__(
        self,
        path: str | Path,
        max_age_s: float,
        producing: Callable[[Any], bool] | None = None,
        warmed: bool = True,
    ):
        self.path = Path(path).expanduser()
        self.max_age_s = max_age_s
        self.producing = producing
        self.warmed = warmed

    def evaluate(self, now: float | None = None) -> Verdict:
        now = now if now is not None else time.time()

        # exists
        try:
            stat = self.path.stat()
            raw = self.path.read_text()
        except (FileNotFoundError, OSError):
            if not self.warmed:
                return Verdict(True, "warming", "output not yet produced (warming up)")
            return Verdict(False, "degraded", f"missing: {self.path}")

        age = now - stat.st_mtime

        # fresh (stuck scheduler / dead writer caught here)
        if age > self.max_age_s:
            return Verdict(False, "degraded",
                           f"stale: age {age:.0f}s > max {self.max_age_s:.0f}s "
                           f"(producer not writing)", age_s=age)

        # parse
        try:
            payload = _payload_of(raw)
        except (ValueError, TypeError):
            return Verdict(False, "degraded", "output present but unparseable", age_s=age)

        # non-empty (running-but-emitting-nothing caught here, NOT by freshness)
        if _is_empty(payload):
            return Verdict(False, "degraded",
                           "fresh but EMPTY — file is current, producer emits nothing",
                           age_s=age)

        # producing (domain-specific 'actually working' signal)
        if self.producing is not None:
            try:
                if not self.producing(payload):
                    return Verdict(False, "degraded",
                                   "fresh and non-empty but producing-signal is false "
                                   "(subsystem stuck/degraded)", age_s=age)
            except Exception as exc:  # noqa: BLE001 — a throwing predicate is a fail, loud
                return Verdict(False, "degraded",
                               f"producing-signal raised: {exc}", age_s=age)

        return Verdict(True, "healthy", "producing", age_s=age)
