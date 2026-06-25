"""LoudFail — make a failure land, exactly once, without ever crashing the run.

Detection is worthless without a response channel. A LivenessContract that
returns ``degraded`` into a return value or a log nobody reads is the
disconnected-sensor failure all over again — the sensor fired, nothing happened.
LoudFail is the part that makes the verdict *land*: it routes a failure to one or
more sinks (callable log, OS notification, process exit code).

Two hard rules, both learned the hard way:

  * **Fire once per NEW incident, not every tick.** A check that runs on a
    schedule and alerts every time it is still-down trains the operator to mute
    it — so the real alarm is ignored (the cockpit-watchdog lesson). LoudFail is
    transition-aware: it alerts on the down-edge and the recovery-edge, and is
    silent while the state is unchanged. Incident state is persisted via
    PersistentState so "new" survives across scheduled processes.

  * **Never crash the run it is protecting.** A notifier that raises (e.g. an
    osascript/shell quoting break) must not take down the very engine
    whose health it reports. Every sink is wrapped; a sink failure is itself
    captured and routed to the log sink, never propagated.

Usage::

    lf = LoudFail(
        name="my-agent",
        state_path="~/.my-agent-loudfail.json",
        sinks=[log_sink(logger.error), notify_sink()],   # composed
    )
    verdict = contract.evaluate()
    lf.report(verdict)        # fires only on a state transition; never raises
"""
from __future__ import annotations

import sys
import subprocess
from typing import Any, Callable, Iterable

from .persistent_state import PersistentState

# A sink is any callable taking (event: str, name: str, reason: str) -> None.
Sink = Callable[[str, str, str], None]


def log_sink(write: Callable[[str], None] = lambda m: print(m, file=sys.stderr)) -> Sink:
    """Sink that writes a one-line message via the given callable (default:
    stderr). Pass ``logger.error`` to route into a real logger."""
    def _sink(event: str, name: str, reason: str) -> None:
        verb = {"down": "DOWN", "recovered": "recovered"}.get(event, event)
        write(f"[loudfail] {name} {verb}: {reason}")
    return _sink


def notify_sink(title: str | None = None) -> Sink:
    """Sink that fires a macOS notification using the env-var + static
    AppleScript pattern so no message text can break the parser. A
    failure here is swallowed by the caller's sink-guard, never raised."""
    def _sink(event: str, name: str, reason: str) -> None:
        msg = f"{name} {event}: {reason}"
        subprocess.run(
            ["osascript", "-e",
             'display notification (system attribute "LF_MSG") '
             'with title (system attribute "LF_TITLE")'],
            env={"LF_MSG": msg, "LF_TITLE": title or "agentliveness", "PATH": _path()},
            check=False, capture_output=True, timeout=10,
        )
    return _sink


def exit_sink(code: int = 1) -> Sink:
    """Sink that sets a non-zero process exit code on a down event — for use in
    a scheduled wrapper whose exit status is itself monitored. Recovery does not
    change the code. (Records intent on the LoudFail; see ``pending_exit``.)"""
    def _sink(event: str, name: str, reason: str) -> None:
        if event == "down":
            raise _ExitRequested(code)   # caught by the guard, recorded, not propagated
    return _sink


def _path() -> str:
    import os
    return os.environ.get("PATH", "/usr/bin:/bin")


class _ExitRequested(Exception):
    def __init__(self, code: int):
        self.code = code


class LoudFail:
    """Transition-aware, crash-safe failure reporter."""

    def __init__(
        self,
        name: str,
        state_path: str,
        sinks: Iterable[Sink] | None = None,
    ):
        self.name = name
        self._state = PersistentState(state_path, default={"status": "healthy"})
        self.sinks: list[Sink] = list(sinks) if sinks else [log_sink()]
        self.pending_exit: int | None = None
        self.sink_errors: list[str] = []

    def report(self, verdict: Any) -> str:
        """Report a verdict. ``verdict`` may be an agentliveness Verdict or any
        object with ``.healthy`` / ``.reason``, or a plain bool. Returns the
        event fired ("down" | "recovered" | "none"). NEVER raises."""
        healthy, reason = self._coerce(verdict)
        prev = self._load_status()
        new = "healthy" if healthy else "down"

        if new == prev:
            event = "none"               # unchanged — stay silent (no fatigue)
        elif new == "down":
            event = "down"
        else:
            event = "recovered"

        if event != "none":
            self._fire(event, reason)
            self._save_status(new)
        return event

    # -- internals ------------------------------------------------------------
    def _fire(self, event: str, reason: str) -> None:
        for sink in self.sinks:
            try:
                sink(event, self.name, reason)
            except _ExitRequested as ex:
                self.pending_exit = ex.code     # record, do not exit here
            except Exception as exc:  # noqa: BLE001 — a sink must NEVER crash the run
                # Route the sink's own failure to a last-resort stderr line and
                # keep going. The protected engine keeps running no matter what.
                self.sink_errors.append(f"{sink}: {exc}")
                try:
                    print(f"[loudfail] sink failed (swallowed): {exc}", file=sys.stderr)
                except Exception:
                    pass

    def _coerce(self, verdict: Any) -> tuple[bool, str]:
        if isinstance(verdict, bool):
            return verdict, "" if verdict else "unhealthy"
        healthy = bool(getattr(verdict, "healthy", verdict))
        reason = str(getattr(verdict, "reason", "")) or ("ok" if healthy else "unhealthy")
        return healthy, reason

    def _load_status(self) -> str:
        data = self._state.load()
        return data.get("status", "healthy") if isinstance(data, dict) else "healthy"

    def _save_status(self, status: str) -> None:
        self._state.save({"status": status})
