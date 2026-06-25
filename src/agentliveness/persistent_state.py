"""PersistentState — restart-safe state for scheduled / autonomous agents.

The problem this exists for: under a scheduler (launchd, cron, k8s CronJob) every
run is a FRESH PROCESS. Any counter or accumulator held only in memory — born as
a constant in ``__init__`` and never restored from disk — silently resets to its
initial value every run. The code looks correct, passes in-process tests, and is
dead in production. (This is the failure that birthed the library: an adaptive
cadence counter that was always 0 at decision time because each launchd process
started fresh, so the feature never engaged — invisible for weeks behind green
tests and a fresh timestamp.)

PersistentState makes cross-run state durable by construction:

  * **atomic writes** (tmp + ``os.replace``) — a crash mid-save can never leave a
    half-written/corrupt file that loads as garbage and *looks* fine;
  * a **versioned envelope** with ``generated_at`` — schema drift is detected, not
    silently mis-parsed, and staleness is checkable;
  * **load-or-default** — a missing/corrupt file returns the caller's default
    instead of raising, so first run and recovery are the same code path.

Usage::

    st = PersistentState("~/.myengine-state.json", default={"runs": 0})
    data = st.load()
    data["runs"] += 1
    st.save(data)

The value is only as real as its disk round-trip — see the subprocess restart
test, which proves survival across genuine process death, not in-memory reuse.
"""
from __future__ import annotations

import json
import os
import tempfile
import datetime
from pathlib import Path
from typing import Any

ENVELOPE_VERSION = 1


class StateVersionError(RuntimeError):
    """Raised when an on-disk envelope's version is newer than this library
    understands — a loud failure, never a silent mis-parse."""


class PersistentState:
    """Atomic, versioned, restart-safe JSON state at a fixed path."""

    def __init__(self, path: str | os.PathLike, default: Any | None = None):
        self.path = Path(path).expanduser()
        self._default = default if default is not None else {}

    # -- read -----------------------------------------------------------------
    def load(self) -> Any:
        """Return the persisted payload, or a deep-ish copy of the default if the
        file is missing or unreadable. A corrupt file is treated as "no state
        yet" (recovery == first run) rather than crashing the engine — the whole
        point is that a scheduled run must not die because state rotted."""
        try:
            raw = self.path.read_text()
        except (FileNotFoundError, OSError):
            return self._fresh_default()
        try:
            env = json.loads(raw)
        except (ValueError, TypeError):
            return self._fresh_default()
        # Bare (un-enveloped) JSON written by an older/foreign writer: accept it
        # as the payload rather than lose it.
        if not isinstance(env, dict) or "__envelope__" not in env:
            return env
        version = env.get("version", 0)
        if version > ENVELOPE_VERSION:
            raise StateVersionError(
                f"{self.path}: envelope version {version} > supported "
                f"{ENVELOPE_VERSION}; upgrade the library, do not mis-read."
            )
        return env.get("payload", self._fresh_default())

    def load_meta(self) -> dict[str, Any] | None:
        """Return envelope metadata (version, generated_at) without the payload,
        or None if there is no envelope. Lets a caller assert freshness."""
        try:
            env = json.loads(self.path.read_text())
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None
        if isinstance(env, dict) and "__envelope__" in env:
            return {"version": env.get("version"),
                    "generated_at": env.get("generated_at")}
        return None

    # -- write ----------------------------------------------------------------
    def save(self, payload: Any) -> None:
        """Atomically persist ``payload`` inside a versioned envelope. Writes to a
        temp file in the same directory, fsyncs, then ``os.replace`` (atomic on
        POSIX) — so a crash at any instant leaves either the old complete file or
        the new complete file, never a torn one."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "__envelope__": True,
            "version": ENVELOPE_VERSION,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "payload": payload,
        }
        data = json.dumps(envelope, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)  # atomic
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- helpers --------------------------------------------------------------
    def _fresh_default(self) -> Any:
        # Return a copy so callers mutating the result can't corrupt our default.
        try:
            return json.loads(json.dumps(self._default))
        except (TypeError, ValueError):
            return self._default
