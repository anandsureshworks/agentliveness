# Security — agentliveness

## Attack Surface

### Network
- **None.** agentliveness makes zero network calls. All operation is local file I/O
  and in-process logic.
- No API keys, no secrets, no credentials, no telemetry.

### Dependencies
- **Runtime: none.** The library uses only the Python standard library
  (`json`, `os`, `tempfile`, `datetime`, `pathlib`, `time`, `dataclasses`).
  There is no third-party runtime dependency to audit or to carry a CVE.
- **pytest** (dev only): test framework, not shipped with the package.

### Input
- `PersistentState` reads a JSON file from a caller-supplied path. Content is
  parsed with `json.loads` only — no `eval`, no `exec`, no pickle, no code
  execution from file content.
- A malformed/corrupt file is handled as "no state yet" (returns the default),
  never executed and never raised into the caller's hot path.
- An envelope whose `version` exceeds the supported version fails **loud**
  (`StateVersionError`) rather than mis-parsing silently.
- `LivenessContract` reads a file and evaluates a caller-supplied `producing`
  predicate over the parsed payload. The predicate is the caller's own code;
  agentliveness does not synthesize or execute arbitrary strings.

### Output
- `PersistentState.save` writes a single JSON file to the caller-supplied path
  via an **atomic** temp-file + `os.replace`. A crash mid-write cannot leave a
  torn file. The temp file is created in the same directory and removed on error.
- No PII, no secrets are introduced by the library; payload content is entirely
  caller-supplied.

### File System
- Reads: the caller-supplied state path.
- Writes: the caller-supplied state path, plus a transient `*.tmp` sibling during
  atomic save (renamed or unlinked before return).
- Creates parent directories of the state path if missing.

## Reporting a Vulnerability
Please report suspected vulnerabilities **privately** via GitHub's private
vulnerability reporting: the repository's **Security** tab → **Report a
vulnerability** (enabled on this repo). That opens a private advisory thread with
the maintainer — please do not open a public issue for a suspected vulnerability.
Expect an acknowledgement within a few days.

There is no network service to attack; the realistic surface is malformed input
to `PersistentState.load` / `LivenessContract.evaluate`, both of which are
designed to fail safe (return default / return a degraded verdict) or fail loud
(`StateVersionError`), never to execute untrusted content.
